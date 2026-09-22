"""Kafka adapter for the EventBroker port.

Everything Kafka-specific lives here: topic naming, the CloudEvents wire codec,
consumer groups, and offset commits. No component imports aiokafka.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from functools import partial

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.abc import ConsumerRebalanceListener
from aiokafka.structs import ConsumerRecord, TopicPartition
from cloudevents.core.bindings import kafka
from cloudevents.core.v1.event import CloudEvent

from .broker import Event, EventHandler
from .console import format_event
from .lanes import Lanes, Watermark

# Every event a component publishes or receives passes through this adapter,
# so this one logger shows each component's side of the conversation.
log = logging.getLogger("EventBroker")


def topic_for(event_type: str) -> str:
    """Map an event type to a Kafka topic: the adapter's business, never an agent's.

    One topic per bounded context, named by the type's prefix: every ``booking``
    event is on the ``booking`` topic. A broker keeps order per key within one
    topic, and all of an aggregate's events belong to one context, so one topic
    per context is what keeps them in order. The type travels inside the event,
    and the consumer dispatches on it.
    """
    context, _, _ = event_type.partition(".")
    return context


def encode(event: Event) -> kafka.KafkaMessage:
    """CloudEvents 1.0 structured JSON, written by the CloudEvents SDK.

    The binding puts the whole event in the record's value, marks it with the
    format's content type, and takes the record key from the ``partitionkey``
    attribute, which is the ordering rule this adapter keeps.
    """
    # Python objects, not their JSON forms: the SDK wants `time` as a datetime and
    # writes the RFC 3339 string itself.
    attributes = event.model_dump(exclude={"data"}, exclude_none=True)
    return kafka.to_structured_event(CloudEvent(attributes, event.data))


def decode(record: ConsumerRecord) -> Event:
    """Read a record as an event, whichever content mode it arrived in.

    A producer outside this system may send binary mode (``ce_`` headers); the
    binding detects the mode, and the attributes and data map one to one.
    """
    message = kafka.KafkaMessage(dict(record.headers or ()), record.key, record.value)
    envelope = kafka.from_kafka_event(message)
    return Event(**envelope.get_attributes(), data=envelope.get_data())


class _PartitionListener(ConsumerRebalanceListener):
    """What the adapter does when the group hands partitions out.

    On assignment it announces that the component is listening: nothing else
    can tell a reader when a subscriber is live, and a subscriber receives only
    what is published after it subscribes. On revocation it commits what has
    finished, while the partitions are still its own to commit, and forgets them.
    """

    def __init__(
        self,
        client_name: str,
        watermark: Watermark,
        commit: Callable[[], Awaitable[None]],
    ) -> None:
        self._client_name = client_name
        self._watermark = watermark
        self._commit = commit

    async def on_partitions_revoked(self, revoked) -> None:
        await self._commit()
        self._watermark.forget(revoked)

    async def on_partitions_assigned(self, assigned) -> None:
        # A subscriber receives only what follows it, so the moment it is listening
        # is the moment that matters to anyone about to publish.
        log.info("%s is subscribed and waiting for events", self._client_name)


# Where a component that has never subscribed before begins reading. "now" is the
# default because it is the one promise every broker can keep; "beginning" asks for
# history, which only a log-backed broker can serve.
_START_POSITIONS = {"now": "latest", "beginning": "earliest"}


class KafkaEventBroker:
    """Satisfies the EventBroker port against a Kafka cluster.

    ``client_name`` identifies the component and becomes its consumer group:
    distinct components each receive every event, while replicas sharing a name
    compete for them.

    ``start`` chooses where a brand-new consumer group begins. It has no effect
    once the group has read anything, because from then on the component resumes
    from its own committed position.

    ``max_in_flight`` caps the events one process handles at once, across every
    partition key. Events sharing a partition key are still handled one at a time and in order.
    """

    def __init__(
        self,
        bootstrap_servers: str,
        client_name: str,
        start: str = "now",
        max_in_flight: int = 64,
    ) -> None:
        if start not in _START_POSITIONS:
            raise ValueError(
                f"start must be one of {sorted(_START_POSITIONS)}, not {start!r}"
            )
        self._bootstrap_servers = bootstrap_servers
        self._client_name = client_name
        self._start = start
        self._max_in_flight = max_in_flight
        self._producer: AIOKafkaProducer | None = None
        self._handlers: dict[str, list[EventHandler]] = {}

    async def __aenter__(self) -> "KafkaEventBroker":
        # Idempotence keeps a retried send from landing twice, or out of order.
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers, enable_idempotence=True
        )
        await self._producer.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._producer.stop()

    async def publish(
        self,
        event_type: str,
        source: str,
        data: dict,
        id: str | None = None,
        attributes: dict[str, str] | None = None,
    ) -> Event:
        attributes = dict(attributes or {})
        attributes.setdefault("time", datetime.now(timezone.utc).isoformat())
        attributes.setdefault("datacontenttype", "application/json")
        event = Event(
            id=id or str(uuid.uuid4()),
            type=event_type,
            source=source,
            data=data,
            **attributes,
        )
        # The codec takes the record key from the partition key: events sharing one
        # land on one partition, and the broker keeps a partition in order.
        message = encode(event)
        await self._producer.send_and_wait(
            topic_for(event.type),
            message.value,
            key=message.key.encode() if isinstance(message.key, str) else message.key,
            headers=list(message.headers.items()),
        )
        log.info("\n%s", format_event("PUBLISHED", event))
        return event

    async def subscribe(
        self,
        event_type: str,
        handler: EventHandler,
        mode: str = "broadcast",
    ) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    async def run(self) -> None:
        """Consume the subscribed topics until cancelled.

        Every turn of the loop does three things, and none of them waits for
        the others: fetch a batch, hand each record to its key's lane, and
        commit what has finished. A record is committed only after its handlers
        return, and only up to the watermark, so a consumer that dies
        mid-handler never confirms the event: the broker delivers it again on
        restart.
        """
        consumer = AIOKafkaConsumer(
            bootstrap_servers=self._bootstrap_servers,
            group_id=self._client_name,
            enable_auto_commit=False,
            auto_offset_reset=_START_POSITIONS[self._start],
            metadata_max_age_ms=5_000,  # discover topics created after startup quickly
        )
        lanes = Lanes(self._max_in_flight)
        watermark = Watermark()
        commit = partial(self._commit_finished, consumer, watermark)
        consumer.subscribe(
            topics=sorted({topic_for(event_type) for event_type in self._handlers}),
            listener=_PartitionListener(self._client_name, watermark, commit),
        )
        await consumer.start()
        try:
            while True:
                room = self._max_in_flight - lanes.in_flight
                if room > 0:
                    consumer.resume(*consumer.paused())
                else:
                    # Polling never stops, or the group would drop this consumer.
                    # A paused partition returns nothing until a lane frees.
                    consumer.pause(*consumer.assignment())
                # The client refuses a batch size of zero; while paused, the one is never filled.
                batches = await consumer.getmany(timeout_ms=200, max_records=max(room, 1))
                for partition, records in batches.items():
                    for record in records:
                        watermark.fetched(partition, record.offset)
                        # No key means no order: the record gets a lane of its own.
                        lanes.submit(
                            record.key or (partition, record.offset),
                            partial(self._handle, watermark, partition, record),
                        )
                await commit()
                lanes.check()
        finally:
            await lanes.close()
            await consumer.stop()

    async def _handle(
        self, watermark: Watermark, partition: TopicPartition, record: ConsumerRecord
    ) -> None:
        event = decode(record)
        handlers = self._handlers.get(event.type, [])
        if handlers:  # a topic carries its whole context; other types pass by untouched
            log.info("\n%s", format_event("RECEIVED", event))
            for handler in handlers:
                await handler(event)
        watermark.finished(partition, record.offset)

    async def _commit_finished(self, consumer: AIOKafkaConsumer, watermark: Watermark) -> None:
        offsets = watermark.advanced()
        if offsets:
            await consumer.commit(offsets)
