"""The in-memory adapters keep the ports' promises as far as a test needs them."""

import asyncio

import pytest

from agentic_eda.memory_broker import InMemoryBroker
from agentic_eda.memory_state_store import InMemoryStateStore
from agentic_eda.state import StaleVersion


async def test_the_broker_delivers_in_publish_order_and_records_a_failing_handler():
    broker = InMemoryBroker()
    seen = []

    async def record(event):
        seen.append(event.id)

    async def fail(event):
        raise RuntimeError("no")

    await broker.subscribe("t.One", record)
    await broker.subscribe("t.One", fail)
    delivering = asyncio.create_task(broker.run())
    await broker.publish("t.One", "s", {}, id="a")
    await broker.publish("t.One", "s", {}, id="b")
    await broker.settled()
    delivering.cancel()

    assert seen == ["a", "b"]
    assert [event.id for event, _ in broker.failed] == ["a", "b"]
    assert broker.published[0].datacontenttype == "application/json"


async def test_the_store_finds_a_created_state_again_and_fences_a_stale_commit():
    store = InMemoryStateStore()
    assert await store.create("req-1") == 1
    assert await store.create("req-1") == 1  # the same request, the same state
    assert await store.create("req-2") == 2
    assert await store.load(1) == ({}, 0)
    assert await store.load(3) is None

    await store.commit(1, {"status": "requested"}, 0, "req-1")
    assert await store.load(1) == ({"status": "requested"}, 1)
    assert await store.handled(1, "req-1") and not await store.handled(1, "req-2")
    with pytest.raises(StaleVersion):
        await store.commit(1, {"status": "planning"}, 0, "ev-2")
