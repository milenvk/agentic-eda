"""Runs the Itinerary Planner Agent against Kafka."""

import asyncio
import functools
import logging
import os

from travel_agency.event_types import TRIP_REQUESTED
from travel_agency.kafka_broker import KafkaEventBroker

from .agent import SOURCE, plan


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    # The Kafka client logs routine group and metadata chatter; keep the
    # agent's log readable and let only real client errors through.
    logging.getLogger("aiokafka").setLevel(logging.ERROR)
    async with KafkaEventBroker(
        os.environ["KAFKA_BOOTSTRAP_SERVERS"], client_name=SOURCE
    ) as broker:
        await broker.subscribe(TRIP_REQUESTED, functools.partial(plan, broker))
        await broker.run()


if __name__ == "__main__":
    asyncio.run(main())
