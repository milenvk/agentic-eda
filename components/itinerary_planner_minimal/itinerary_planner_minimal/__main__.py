"""Runs the Itinerary Planner Agent against Kafka."""

import asyncio
import functools
import logging
import os
import warnings

from travel_agency.event_types import TRIP_REQUESTED
from travel_agency.kafka_broker import KafkaEventBroker

from .agent import SOURCE, plan


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    # The Kafka client, LiteLLM, and its HTTP client all log routine chatter;
    # keep the agent's log to its own lines and the event cards.
    logging.getLogger("aiokafka").setLevel(logging.ERROR)
    logging.getLogger("LiteLLM").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # LiteLLM's response parsing trips a cosmetic pydantic warning with some
    # providers (Ollama among them); it carries no information for us.
    warnings.filterwarnings("ignore", message="Pydantic serializer warnings")
    async with KafkaEventBroker(
        os.environ["KAFKA_BOOTSTRAP_SERVERS"], client_name=SOURCE
    ) as broker:
        await broker.subscribe(TRIP_REQUESTED, functools.partial(plan, broker))
        await broker.run()


if __name__ == "__main__":
    asyncio.run(main())
