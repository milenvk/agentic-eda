"""Kafka adapter for the EventBroker port.

Everything Kafka-specific lives here: topic naming, the CloudEvents wire codec,
consumer groups, and offset commits. No component imports aiokafka.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.abc import ConsumerRebalanceListener

from .broker import Event, EventHandler
from .console import format_event

# Every event a component publishes or receives passes through this adapter,
# so this one logger shows each component's side of the conversation.
log = logging.getLogger("EventBroker")

# The CloudEvents attributes that are fields of Event rather than entries in
# Event.attributes; everything else in an envelope is an attribute.
_ROOT_KEYS = frozenset({"specversion", "id", "source", "type", "data"})


def topic_for(event_type: str) -> str:
    """Map an event type to a Kafka topic — the adapter's business, never an agent's.

    Today the mapping is identity: one topic per event type, named after it.
    """
    return event_type


def encode(event: Event) -> bytes:
    """CloudEvents 1.0 structured JSON."""
    envelope = {
        "specversion": "1.0",
        "id": event.id,
        "source": event.source,
        "type": event.type,
        **event.attributes,
        "data": event.payload,
    }
    return json.dumps(envelope).encode()


def decode(raw: bytes) -> Event:
    envelope = json.loads(raw)
    return Event(
        id=envelope["id"],
        type=envelope["type"],
        source=envelope["source"],
        payload=envelope["data"],
        attributes={k: v for k, v in envelope.items() if k not in _ROOT_KEYS},
    )


class _AnnounceSubscription(ConsumerRebalanceListener):
    """Announce that a component is listening, once its partitions are assigned.

    Nothing else can tell a reader when a subscriber is live, and a subscriber
    receives only what is published after it subscribes.
    """

    def __init__(self, consumer: AIOKafkaConsumer, client_name: str = "") -> None:
        self._consumer = consumer
        self._client_name = client_name

    async def on_partitions_revoked(self, revoked) -> None:
        pass

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
    """

    def __init__(
        self, bootstrap_servers: str, client_name: str, start: str = "now"
    ) -> None:
        if start not in _START_POSITIONS:
            raise ValueError(
                f"start must be one of {sorted(_START_POSITIONS)}, not {start!r}"
            )
        self._bootstrap_servers = bootstrap_servers
        self._client_name = client_name
        self._start = start
        self._producer: AIOKafkaProducer | None = None
        self._handlers: dict[str, list[EventHandler]] = {}

    async def __aenter__(self) -> "KafkaEventBroker":
        self._producer = AIOKafkaProducer(bootstrap_servers=self._bootstrap_servers)
        await self._producer.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._producer.stop()

    async def publish(
        self,
        event_type: str,
        source: str,
        payload: dict,
        id: str | None = None,
        attributes: dict[str, str] | None = None,
    ) -> str:
        attributes = dict(attributes or {})
        attributes.setdefault("time", datetime.now(timezone.utc).isoformat())
        attributes.setdefault("datacontenttype", "application/json")
        event = Event(
            id=id or str(uuid.uuid4()),
            type=event_type,
            source=source,
            payload=payload,
            attributes=attributes,
        )
        await self._producer.send_and_wait(topic_for(event.type), encode(event))
        log.info("\n%s", format_event("PUBLISHED", event))
        return event.id

    async def subscribe(
        self,
        event_type: str,
        handler: EventHandler,
        mode: str = "broadcast",
    ) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    async def run(self) -> None:
        """Consume the subscribed topics until cancelled.

        An event's offset is committed only after its handlers finish, so a
        consumer that dies mid-handler never confirms the event — the broker
        delivers it again on restart.
        """
        consumer = AIOKafkaConsumer(
            bootstrap_servers=self._bootstrap_servers,
            group_id=self._client_name,
            enable_auto_commit=False,
            auto_offset_reset=_START_POSITIONS[self._start],
            metadata_max_age_ms=5_000,  # discover topics created after startup quickly
        )
        consumer.subscribe(
            topics=[topic_for(event_type) for event_type in self._handlers],
            listener=_AnnounceSubscription(consumer, self._client_name),
        )
        await consumer.start()
        try:
            async for message in consumer:
                event = decode(message.value)
                log.info("\n%s", format_event("RECEIVED", event))
                for handler in self._handlers.get(event.type, []):
                    await handler(event)
                await consumer.commit()
        finally:
            await consumer.stop()
