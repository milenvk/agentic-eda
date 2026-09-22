"""Unit tests for the Kafka adapter: codec, minting, topics, lanes, and commit discipline.

aiokafka is replaced with fakes: no broker, no network.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from types import SimpleNamespace

import pytest
from aiokafka.structs import TopicPartition

from travel_agency import kafka_broker
from travel_agency.broker import Event
from travel_agency.kafka_broker import KafkaEventBroker, decode, encode, topic_for
from travel_agency.lanes import Watermark

BOOKING = TopicPartition("booking", 0)


class FakeProducer:
    """Records what the adapter sends instead of talking to Kafka."""

    last: "FakeProducer" = None

    def __init__(self, **config: object) -> None:
        self.config = config
        self.sent: list[tuple[str, bytes, bytes | None, list]] = []
        FakeProducer.last = self

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send_and_wait(
        self, topic: str, value: bytes, key: bytes | None = None, headers: list | None = None
    ) -> None:
        self.sent.append((topic, value, key, headers or []))


class FakeConsumer:
    """Serves the prepared batches to the adapter and records what it is told.

    ``prepared`` is filled by a test before the adapter constructs its consumer;
    each ``getmany`` returns the next batch, or nothing while paused.
    """

    last: "FakeConsumer" = None
    prepared: list[dict] = []

    def __init__(self, **config: object) -> None:
        self.config = config
        self.topics: tuple[str, ...] = ()
        self.listener = None
        self.calls: list[str] = []
        self.commits: list[dict] = []
        self._paused: set[TopicPartition] = set()
        FakeConsumer.last = self

    def subscribe(self, topics=(), listener=None) -> None:
        self.topics = tuple(topics)
        self.listener = listener

    async def start(self) -> None:
        self.calls.append("start")

    async def stop(self) -> None:
        self.calls.append("stop")

    def assignment(self) -> set[TopicPartition]:
        return {BOOKING}

    def paused(self) -> set[TopicPartition]:
        return set(self._paused)

    def pause(self, *partitions: TopicPartition) -> None:
        if partitions and not self._paused:
            self.calls.append("pause")
        self._paused.update(partitions)

    def resume(self, *partitions: TopicPartition) -> None:
        if partitions:
            self.calls.append("resume")
        self._paused.difference_update(partitions)

    async def getmany(self, *partitions, timeout_ms: int = 0, max_records=None) -> dict:
        await asyncio.sleep(0)  # a real fetch yields; the lanes get to run
        if self._paused or not FakeConsumer.prepared:
            return {}
        return FakeConsumer.prepared.pop(0)

    async def commit(self, offsets=None) -> None:
        self.calls.append("commit")
        self.commits.append(dict(offsets))


@pytest.fixture
def fake_kafka(monkeypatch):
    monkeypatch.setattr(kafka_broker, "AIOKafkaProducer", FakeProducer)
    monkeypatch.setattr(kafka_broker, "AIOKafkaConsumer", FakeConsumer)
    FakeConsumer.prepared = []
    FakeConsumer.last = None
    return FakeConsumer


def make_event(**overrides) -> Event:
    fields = dict(
        id="event-1",
        type="booking.TripRequested",
        source="test",
        data={"destination": "Lisbon"},
        time="2026-08-16T00:00:00+00:00",
        subject="trip",
    )
    fields.update(overrides)
    return Event(**fields)


def record(offset: int, event: Event, key: bytes | None = None) -> SimpleNamespace:
    message = encode(event)
    return SimpleNamespace(
        offset=offset, key=key, value=message.value, headers=list(message.headers.items())
    )


async def until(condition: Callable[[], object], timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        await asyncio.sleep(0)  # the loop's task gets its first turn before any check
        while not condition():
            await asyncio.sleep(0)


@asynccontextmanager
async def running(broker: KafkaEventBroker):
    """The delivery loop as a task, cancelled on the way out like a shutdown."""
    task = asyncio.create_task(broker.run())
    try:
        yield task
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def run_until(broker: KafkaEventBroker, condition: Callable[[], object]) -> None:
    """Run the loop until ``condition`` holds, or the loop ends on its own."""
    async with running(broker) as task:
        await until(lambda: condition() or task.done())
        if task.done():
            task.result()  # a handler's failure surfaces here


def test_the_topic_is_the_event_types_context():
    assert topic_for("booking.TripRequested") == "booking"
    assert topic_for("planning.ItineraryProposed") == "planning"


def test_encode_decode_round_trip():
    event = make_event(myextension="x")
    assert decode(record(0, event)) == event


def test_an_event_in_binary_mode_decodes_the_same_way():
    # A producer outside this system may send binary mode, where the attributes
    # travel as headers and the value holds the data alone.
    event = make_event()
    binary = SimpleNamespace(
        offset=0,
        key=None,
        headers=[
            ("ce_specversion", b"1.0"),
            ("ce_id", b"event-1"),
            ("ce_type", b"booking.TripRequested"),
            ("ce_source", b"test"),
            ("ce_time", b"2026-08-16T00:00:00+00:00"),
            ("ce_subject", b"trip"),
        ],
        value=json.dumps(event.data).encode(),
    )

    assert decode(binary) == event


def test_envelope_is_cloudevents_structured_json():
    message = encode(make_event())
    assert message.headers["content-type"] == b"application/cloudevents+json"
    envelope = json.loads(message.value)
    assert envelope["specversion"] == "1.0"
    assert envelope["id"] == "event-1"
    assert envelope["type"] == "booking.TripRequested"
    assert envelope["source"] == "test"
    assert envelope["data"] == {"destination": "Lisbon"}
    # attributes sit at the top level of the envelope, per the structured format
    assert envelope["subject"] == "trip"


async def test_publish_mints_id_time_and_datacontenttype(fake_kafka):
    async with KafkaEventBroker("kafka:9092", client_name="test") as broker:
        published = await broker.publish("booking.SomethingHappened", "test", {"a": 1})

    uuid.UUID(published.id)  # a real UUID was minted
    topic, raw, key, _headers = FakeProducer.last.sent[0]
    envelope = json.loads(raw)
    assert topic == "booking"
    assert key is None  # nothing asked for order
    assert envelope["id"] == published.id
    assert envelope["datacontenttype"] == "application/json"
    assert "time" in envelope


async def test_publish_keeps_what_the_caller_supplies(fake_kafka):
    async with KafkaEventBroker("kafka:9092", client_name="test") as broker:
        published = await broker.publish(
            "booking.SomethingHappened",
            "test",
            {"a": 1},
            id="chosen-id",
            attributes={"time": "2026-08-16T00:00:00+00:00", "subject": "chosen"},
        )

    assert published.id == "chosen-id"
    envelope = json.loads(FakeProducer.last.sent[0][1])
    assert envelope["id"] == "chosen-id"
    assert envelope["time"].startswith("2026-08-16T00:00:00")
    assert envelope["subject"] == "chosen"


async def test_the_partitionkey_becomes_the_record_key(fake_kafka):
    async with KafkaEventBroker("kafka:9092", client_name="test") as broker:
        await broker.publish(
            "booking.SomethingHappened", "test", {}, attributes={"partitionkey": "trip-1"}
        )

    assert FakeProducer.last.sent[0][2] == b"trip-1"
    assert FakeProducer.last.config["enable_idempotence"] is True


async def test_a_component_subscribes_to_the_topics_of_its_events_contexts(fake_kafka):
    broker = KafkaEventBroker("kafka:9092", client_name="AuditConsumer")

    async def handler(event: Event) -> None:
        pass

    await broker.subscribe("booking.TripRequested", handler)
    await broker.subscribe("booking.TripChanged", handler)
    await broker.subscribe("planning.ItineraryProposed", handler)
    await run_until(broker, lambda: fake_kafka.last and "start" in fake_kafka.last.calls)

    consumer = fake_kafka.last
    assert consumer.topics == ("booking", "planning")
    assert consumer.config["group_id"] == "AuditConsumer"
    assert consumer.config["enable_auto_commit"] is False


async def test_a_subscriber_starts_at_the_tail_by_default(fake_kafka):
    """A late subscriber receives what follows it and nothing earlier.

    Brokers without a durable log cannot hand history to a subscriber that
    arrives after the fact, so the default promises only what all of them do.
    """
    broker = KafkaEventBroker("kafka:9092", client_name="AuditConsumer")

    async def handler(event: Event) -> None:
        pass

    await broker.subscribe("booking.A", handler)
    await run_until(broker, lambda: fake_kafka.last is not None)

    assert fake_kafka.last.config["auto_offset_reset"] == "latest"


async def test_a_component_can_ask_for_the_history_the_broker_still_holds(fake_kafka):
    """The patterns that need history say so. Replay becomes a decision visible
    in the component's own code instead of a broker setting it never mentions."""
    broker = KafkaEventBroker("kafka:9092", client_name="Observer", start="beginning")

    async def handler(event: Event) -> None:
        pass

    await broker.subscribe("booking.A", handler)
    await run_until(broker, lambda: fake_kafka.last is not None)

    assert fake_kafka.last.config["auto_offset_reset"] == "earliest"


def test_an_unknown_starting_point_is_refused():
    """Silently falling back to the default would hide the one thing the caller
    was explicit about."""
    with pytest.raises(ValueError, match="beginning"):
        KafkaEventBroker("kafka:9092", client_name="Observer", start="earliest")


async def test_a_subscriber_announces_itself_once_it_is_listening(caplog):
    """A subscriber receives only what follows it, so anything about to publish
    needs to know when it is listening. Assignment is that moment, and the demo's
    third act tells the reader to wait for this line."""

    async def commit() -> None:
        pass

    listener = kafka_broker._PartitionListener("AuditConsumer", Watermark(), commit)

    with caplog.at_level(logging.INFO, logger="EventBroker"):
        await listener.on_partitions_assigned([BOOKING])

    assert "AuditConsumer is subscribed and waiting for events" in caplog.text


async def test_a_revoked_partition_is_committed_and_then_forgotten():
    """The partitions are still the consumer's during the callback, which is the
    last moment it may commit them; whatever finishes later belongs to the new owner."""
    commits: list[str] = []
    watermark = Watermark()

    async def commit() -> None:
        commits.append(str(watermark.advanced()))

    listener = kafka_broker._PartitionListener("test", watermark, commit)
    watermark.fetched(BOOKING, 0)
    watermark.fetched(BOOKING, 1)
    watermark.finished(BOOKING, 0)

    await listener.on_partitions_revoked([BOOKING])
    watermark.finished(BOOKING, 1)

    assert commits == [str({BOOKING: 1})]
    assert watermark.advanced() == {}


async def test_commit_happens_only_after_the_handler_finishes(fake_kafka):
    broker = KafkaEventBroker("kafka:9092", client_name="test")

    async def handler(event: Event) -> None:
        fake_kafka.last.calls.append(f"handled {event.id}")  # one log with the consumer's

    await broker.subscribe("booking.TripRequested", handler)
    fake_kafka.prepared.append({BOOKING: [record(0, make_event())]})
    await run_until(broker, lambda: fake_kafka.last and fake_kafka.last.commits)

    consumer = fake_kafka.last
    assert consumer.calls == ["start", "handled event-1", "commit", "stop"]
    assert consumer.commits == [{BOOKING: 1}]


async def test_other_types_on_the_topic_are_acknowledged_untouched(fake_kafka):
    """A context topic carries every type of its context. A type nobody here
    subscribed to is committed like any other, and no handler sees it."""
    broker = KafkaEventBroker("kafka:9092", client_name="test")
    seen: list[str] = []

    async def handler(event: Event) -> None:
        seen.append(event.type)

    await broker.subscribe("booking.TripRequested", handler)
    fake_kafka.prepared.append(
        {BOOKING: [record(0, make_event(type="booking.TripChanged"))]}
    )
    await run_until(broker, lambda: fake_kafka.last and fake_kafka.last.commits)

    assert seen == []
    assert fake_kafka.last.commits == [{BOOKING: 1}]


async def test_both_sides_of_the_conversation_are_logged(fake_kafka, caplog):
    caplog.set_level(logging.INFO, logger="EventBroker")
    broker = KafkaEventBroker("kafka:9092", client_name="test")

    async with broker:
        await broker.publish("booking.SomethingHappened", "test", {"a": 1})
    assert "PUBLISHED" in caplog.text

    async def handler(event: Event) -> None:
        pass

    await broker.subscribe("booking.TripRequested", handler)
    fake_kafka.prepared.append({BOOKING: [record(0, make_event())]})
    await run_until(broker, lambda: fake_kafka.last and fake_kafka.last.commits)
    assert "RECEIVED" in caplog.text


async def test_no_commit_when_the_handler_fails(fake_kafka):
    broker = KafkaEventBroker("kafka:9092", client_name="test")

    async def failing_handler(event: Event) -> None:
        raise RuntimeError("killed mid-inference")

    await broker.subscribe("booking.TripRequested", failing_handler)
    fake_kafka.prepared.append({BOOKING: [record(0, make_event())]})

    with pytest.raises(RuntimeError, match="mid-inference"):
        await run_until(broker, lambda: False)

    assert "commit" not in fake_kafka.last.calls
    assert "stop" in fake_kafka.last.calls  # the consumer still shuts down cleanly


class Gated:
    """A handler that blocks each event until the test releases it by id."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.gates: dict[str, asyncio.Event] = {}

    async def __call__(self, event: Event) -> None:
        self.started.append(event.id)
        await self.gates.setdefault(event.id, asyncio.Event()).wait()

    def release(self, *ids: str) -> None:
        for event_id in ids:
            self.gates.setdefault(event_id, asyncio.Event()).set()


def batch(*items: tuple[int, str, bytes | None]) -> dict:
    """Records for one partition: (offset, event id, record key)."""
    return {BOOKING: [record(offset, make_event(id=id), key) for offset, id, key in items]}


async def test_events_sharing_a_key_are_handled_one_at_a_time_in_order(fake_kafka):
    broker = KafkaEventBroker("kafka:9092", client_name="test")
    handler = Gated()
    await broker.subscribe("booking.TripRequested", handler)
    fake_kafka.prepared.append(batch((0, "a", b"trip-1"), (1, "b", b"trip-1"), (2, "c", b"trip-1")))

    async with running(broker):
        await until(lambda: handler.started == ["a"])
        handler.release("a")
        await until(lambda: handler.started == ["a", "b"])
        handler.release("b", "c")
        await until(lambda: fake_kafka.last.commits == [{BOOKING: 1}, {BOOKING: 3}])


async def test_events_of_different_keys_are_handled_concurrently(fake_kafka):
    broker = KafkaEventBroker("kafka:9092", client_name="test")
    handler = Gated()
    await broker.subscribe("booking.TripRequested", handler)
    fake_kafka.prepared.append(batch((0, "a", b"trip-1"), (1, "b", b"trip-2"), (2, "c", b"trip-3")))

    async with running(broker):
        await until(lambda: handler.started == ["a", "b", "c"])  # none waited for another
        handler.release("a", "b", "c")
        await until(lambda: fake_kafka.last.commits and fake_kafka.last.commits[-1] == {BOOKING: 3})


async def test_an_event_without_a_key_gets_a_lane_of_its_own(fake_kafka):
    broker = KafkaEventBroker("kafka:9092", client_name="test")
    handler = Gated()
    await broker.subscribe("booking.TripRequested", handler)
    fake_kafka.prepared.append(batch((0, "a", None), (1, "b", None)))

    async with running(broker):
        await until(lambda: handler.started == ["a", "b"])
        handler.release("a", "b")


async def test_the_commit_follows_the_watermark_not_the_fastest_lane(fake_kafka):
    """Offsets 0 and 2 finish while 1 is still running: only 0 is confirmed.
    Everything from 1 on would come back after a crash, 2 included."""
    broker = KafkaEventBroker("kafka:9092", client_name="test")
    handler = Gated()
    await broker.subscribe("booking.TripRequested", handler)
    fake_kafka.prepared.append(batch((0, "a", b"trip-1"), (1, "b", b"trip-2"), (2, "c", b"trip-3")))

    async with running(broker):
        await until(lambda: len(handler.started) == 3)
        handler.release("a", "c")
        await until(lambda: fake_kafka.last.commits == [{BOOKING: 1}])
        handler.release("b")
        await until(lambda: fake_kafka.last.commits == [{BOOKING: 1}, {BOOKING: 3}])


async def test_a_full_consumer_pauses_fetching_and_resumes_when_a_lane_frees(fake_kafka):
    broker = KafkaEventBroker("kafka:9092", client_name="test", max_in_flight=2)
    handler = Gated()
    await broker.subscribe("booking.TripRequested", handler)
    fake_kafka.prepared.append(batch((0, "a", b"trip-1"), (1, "b", b"trip-2")))
    fake_kafka.prepared.append(batch((2, "c", b"trip-3")))

    async with running(broker):
        await until(lambda: "pause" in fake_kafka.last.calls)
        await until(lambda: handler.started == ["a", "b"])
        for _ in range(5):
            await asyncio.sleep(0)
        assert handler.started == ["a", "b"]  # the third record is not fetched while full
        handler.release("a")
        await until(lambda: handler.started == ["a", "b", "c"])
        assert fake_kafka.last.calls.index("resume") > fake_kafka.last.calls.index("pause")
        handler.release("b", "c")
