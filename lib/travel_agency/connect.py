"""Opening a broker: the one place any component names an implementation.

Every component's entry point calls ``event_broker`` and receives something it
can publish to and subscribe on. None of them names Kafka, reads a broker
address, or knows how the connection is closed. Swapping in another broker, or
a test double, is a change to this function alone.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from .broker import EventBrokerConnection
from .kafka_broker import KafkaEventBroker


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
