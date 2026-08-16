"""Runs the Itinerary Planner Agent against Kafka."""

import asyncio
import functools
import os

from travel_agency import console
from travel_agency.event_types import TRIP_REQUESTED
from travel_agency.kafka_broker import KafkaEventBroker

from .agent import SOURCE, plan


async def main() -> None:
    console.configure_logging()
    async with KafkaEventBroker(
        os.environ["KAFKA_BOOTSTRAP_SERVERS"], client_name=SOURCE
    ) as broker:
        await broker.subscribe(TRIP_REQUESTED, functools.partial(plan, broker))
        await broker.run()


if __name__ == "__main__":
    asyncio.run(main())
