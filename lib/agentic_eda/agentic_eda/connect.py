"""Opening a broker or a store: the one place any component names an implementation.

Every component's entry point calls ``event_broker`` and receives something it
can publish to and subscribe on. None of them names Kafka, reads a broker
address, or knows how the connection is closed. Swapping in another broker, or
a test double, is a change to this function alone. ``state_store`` is the same
function for the StateStore port, called by the activator for an agent that
declared its state.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from .broker import EventBrokerConnection
from .kafka_broker import KafkaEventBroker
from .postgres_state_store import PostgresStateStore
from .state import StateStore


@asynccontextmanager
async def event_broker(
    client_name: str, start: str = "now"
) -> AsyncIterator[EventBrokerConnection]:
    """Open the configured broker for one component, and close it on the way out.

    ``client_name`` identifies the component to the broker. Where the broker
    lives is a deployment fact, read here from the environment.

    ``start`` chooses where a component reads from the first time it subscribes.
    The default, ``"now"``, delivers what is published from that moment onward,
    which is the one promise every broker can keep. ``"beginning"`` asks for the
    history the broker still holds, and an adapter backed by a broker without a
    durable log must refuse it rather than quietly starting from now.
    """
    async with KafkaEventBroker(
        os.environ["KAFKA_BOOTSTRAP_SERVERS"], client_name=client_name, start=start
    ) as broker:
        yield broker


@asynccontextmanager
async def state_store(client_name: str) -> AsyncIterator[StateStore]:
    """Open the configured state store for one component, and close it on the way out.

    The database's address and the table that holds the component's states are deployment
    facts, read from ``STATE_STORE_URL`` and ``STATE_STORE_TABLE``.
    """
    async with PostgresStateStore(
        os.environ["STATE_STORE_URL"], os.environ["STATE_STORE_TABLE"], client_name=client_name
    ) as store:
        yield store
