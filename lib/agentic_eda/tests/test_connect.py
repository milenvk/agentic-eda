"""Unit tests for the broker factory: it opens the configured broker and closes it.

The adapter is replaced with a fake, so no broker and no network are involved.
"""

import pytest

from agentic_eda import connect


class FakeBroker:
    """Records how the factory opened it, and whether it was closed."""

    def __init__(
        self, bootstrap_servers: str, client_name: str, start: str = "now"
    ) -> None:
        self.bootstrap_servers = bootstrap_servers
        self.client_name = client_name
        self.start = start
        self.closed = False

    async def __aenter__(self) -> "FakeBroker":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self.closed = True


@pytest.fixture
def fake_adapter(monkeypatch):
    monkeypatch.setattr(connect, "KafkaEventBroker", FakeBroker)
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")


async def test_component_supplies_only_its_own_name(fake_adapter):
    async with connect.event_broker("AuditConsumer") as broker:
        assert broker.client_name == "AuditConsumer"
        assert broker.bootstrap_servers == "kafka:9092"


async def test_a_component_reads_from_now_unless_it_asks_otherwise(fake_adapter):
    """The portable promise is the default, so a component that says nothing
    about history behaves the same on every broker."""
    async with connect.event_broker("AuditConsumer") as broker:
        assert broker.start == "now"

    async with connect.event_broker("Observer", start="beginning") as observer:
        assert observer.start == "beginning"


async def test_broker_is_closed_on_the_way_out(fake_adapter):
    async with connect.event_broker("AuditConsumer") as broker:
        assert not broker.closed

    assert broker.closed


async def test_broker_is_closed_when_the_component_fails(fake_adapter):
    with pytest.raises(RuntimeError):
        async with connect.event_broker("AuditConsumer") as broker:
            raise RuntimeError("the component died mid-run")

    assert broker.closed
