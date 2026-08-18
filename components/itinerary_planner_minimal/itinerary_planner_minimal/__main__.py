"""Runs the Itinerary Planner Agent against the configured broker."""

import asyncio
import functools

from travel_agency import console
from travel_agency.connect import event_broker
from travel_agency.event_types import TRIP_REQUESTED

from .agent import SOURCE, plan


async def main() -> None:
    console.configure_logging()
    async with event_broker(SOURCE) as broker:
        await broker.subscribe(TRIP_REQUESTED, functools.partial(plan, broker))
        await broker.run()


if __name__ == "__main__":
    asyncio.run(main())
