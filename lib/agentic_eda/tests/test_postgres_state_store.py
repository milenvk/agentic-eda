"""The PostgreSQL adapter against a running database, named by STATE_STORE_URL.

Skipped without one: the chapter's `compose.tests.yaml` runs this file with a database.
"""

import os
from uuid import uuid4

import pytest

from agentic_eda.postgres_state_store import PostgresStateStore
from agentic_eda.state import StaleVersion

pytestmark = pytest.mark.skipif("STATE_STORE_URL" not in os.environ, reason="no database")


@pytest.fixture
async def store():
    # A table per test, so the suite runs against a database that keeps its rows.
    table = f"states_{uuid4().hex[:8]}"
    async with PostgresStateStore(os.environ["STATE_STORE_URL"], table, "tests") as opened:
        yield opened


async def test_a_request_creates_its_state_once(store):
    request = str(uuid4())
    id = await store.create(request)
    assert await store.create(request) == id
    assert await store.create(str(uuid4())) != id
    assert await store.load(id) == ({}, 0)
    assert await store.load(10**6) is None


async def test_a_commit_writes_the_state_and_records_its_cause_in_one_transaction(store):
    id = await store.create(str(uuid4()))
    await store.commit(id, {"status": "requested", "trip_id": id}, 0, "ev-1")

    assert await store.load(id) == ({"status": "requested", "trip_id": id}, 1)
    assert await store.handled(id, "ev-1") and not await store.handled(id, "ev-2")
    with pytest.raises(StaleVersion):
        await store.commit(id, {"status": "planning"}, 0, "ev-2")
    assert not await store.handled(id, "ev-2")  # the refused commit recorded nothing
