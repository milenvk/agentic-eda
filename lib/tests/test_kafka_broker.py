"""Unit tests for the Kafka adapter: codec, minting, and commit discipline.

aiokafka is replaced with fakes — no broker, no network.
"""

import json
import uuid
from types import SimpleNamespace

import pytest

from travel_agency import kafka_broker
from travel_agency.broker import Event
from travel_agency.kafka_broker import KafkaEventBroker, decode, encode, topic_for


class FakeProducer:
    """Records what the adapter sends instead of talking to Kafka."""

    last: "FakeProducer" = None

    def __init__(self, bootstrap_servers: str) -> None:
        self.bootstrap_servers = bootstrap_servers
        self.sent: list[tuple[str, bytes]] = []
        FakeProducer.last = self

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send_and_wait(self, topic: str, value: bytes) -> None:
        self.sent.append((topic, value))


class FakeConsumer:
    """Feeds prepared messages to the adapter and records the call order."""

    last: "FakeConsumer" = None

    def __init__(self, *topics: str, **config: object) -> None:
        self.topics = topics
        self.config = config
        self.messages: list[SimpleNamespace] = list(config.pop("_messages", []))
        self.calls: list[str] = []
        FakeConsumer.last = self

    async def start(self) -> None:
        self.calls.append("start")

    async def stop(self) -> None:
        self.calls.append("stop")

    async def commit(self) -> None:
        self.calls.append("commit")

    def __aiter__(self):
        return self._deliver()

    async def _deliver(self):
        for message in self.messages:
            yield message


@pytest.fixture
def fake_kafka(monkeypatch):
    monkeypatch.setattr(kafka_broker, "AIOKafkaProducer", FakeProducer)
    monkeypatch.setattr(kafka_broker, "AIOKafkaConsumer", FakeConsumer)


def make_event(**overrides) -> Event:
    fields = dict(
        id="event-1",
        type="com.travelagency.booking.TripRequested",
        source="test",
        payload={"destination": "Lisbon"},
        attributes={"time": "2026-08-16T00:00:00+00:00", "subject": "trip"},
    )
    fields.update(overrides)
    return Event(**fields)


def test_topic_mapping_is_identity():
    assert topic_for("com.travelagency.booking.TripRequested") == (
        "com.travelagency.booking.TripRequested"
    )


def test_encode_decode_round_trip():
    event = make_event(attributes={"time": "t", "subject": "s", "myextension": "x"})
    assert decode(encode(event)) == event


def test_envelope_is_cloudevents_structured_json():
    envelope = json.loads(encode(make_event()))
    assert envelope["specversion"] == "1.0"
    assert envelope["id"] == "event-1"
    assert envelope["type"] == "com.travelagency.booking.TripRequested"
    assert envelope["source"] == "test"
    assert envelope["data"] == {"destination": "Lisbon"}
    # attributes sit at the top level of the envelope, per the structured format
    assert envelope["subject"] == "trip"


async def test_publish_mints_id_time_and_datacontenttype(fake_kafka):
    async with KafkaEventBroker("kafka:9092", client_name="test") as broker:
        event_id = await broker.publish("SomethingHappened", "test", {"a": 1})

    uuid.UUID(event_id)  # a real UUID was minted
    topic, raw = FakeProducer.last.sent[0]
    envelope = json.loads(raw)
    assert topic == "SomethingHappened"
    assert envelope["id"] == event_id
    assert envelope["datacontenttype"] == "application/json"
    assert "time" in envelope


async def test_publish_keeps_what_the_caller_supplies(fake_kafka):
    async with KafkaEventBroker("kafka:9092", client_name="test") as broker:
        event_id = await broker.publish(
            "SomethingHappened",
            "test",
            {"a": 1},
            id="chosen-id",
            attributes={"time": "chosen-time", "subject": "chosen"},
        )

    assert event_id == "chosen-id"
    envelope = json.loads(FakeProducer.last.sent[0][1])
    assert envelope["id"] == "chosen-id"
    assert envelope["time"] == "chosen-time"
    assert envelope["subject"] == "chosen"


async def test_consumer_group_is_the_client_name_with_manual_commit(fake_kafka):
    broker = KafkaEventBroker("kafka:9092", client_name="AuditConsumer")

    async def handler(event: Event) -> None:
        pass

    await broker.subscribe("A", handler)
    await broker.subscribe("B", handler)
    await broker.run()

    consumer = FakeConsumer.last
    assert set(consumer.topics) == {"A", "B"}
    assert consumer.config["group_id"] == "AuditConsumer"
    assert consumer.config["enable_auto_commit"] is False


async def test_commit_happens_only_after_the_handler_finishes(fake_kafka):
    broker = KafkaEventBroker("kafka:9092", client_name="test")
    order: list[str] = []

    async def handler(event: Event) -> None:
        order.append(f"handled {event.id}")

    await broker.subscribe("com.travelagency.booking.TripRequested", handler)

    message = SimpleNamespace(value=encode(make_event()))
    consumer_config = {"_messages": [message]}

    original_init = FakeConsumer.__init__

    def init_with_message(self, *topics, **config):
        original_init(self, *topics, **{**config, **consumer_config})
        self.calls = order  # share one log with the handler to capture ordering

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(FakeConsumer, "__init__", init_with_message)
        await broker.run()

    assert order == ["start", "handled event-1", "commit", "stop"]


async def test_no_commit_when_the_handler_fails(fake_kafka):
    broker = KafkaEventBroker("kafka:9092", client_name="test")

    async def failing_handler(event: Event) -> None:
        raise RuntimeError("killed mid-inference")

    await broker.subscribe("com.travelagency.booking.TripRequested", failing_handler)

    message = SimpleNamespace(value=encode(make_event()))
    original_init = FakeConsumer.__init__

    def init_with_message(self, *topics, **config):
        original_init(self, *topics, **{**config, "_messages": [message]})

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(FakeConsumer, "__init__", init_with_message)
        with pytest.raises(RuntimeError):
            await broker.run()

    assert "commit" not in FakeConsumer.last.calls
    assert "stop" in FakeConsumer.last.calls  # the consumer still shuts down cleanly
