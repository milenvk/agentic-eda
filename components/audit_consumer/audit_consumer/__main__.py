"""Runs the Audit Consumer against the configured broker."""

import asyncio
import functools
import os

from travel_agency import console
from travel_agency.connect import event_broker
from travel_agency.event_types import ITINERARY_PROPOSED, TRIP_REQUESTED

from .consumer import SOURCE, record


async def main() -> None:
    console.configure_logging()
    handler = functools.partial(record, os.environ.get("AUDIT_LOG", "/data/audit.log"))
    async with event_broker(SOURCE) as broker:
        # One subscription per event type the system has so far; chapter 3
        # replaces this list with a single subscribe-all.
        await broker.subscribe(TRIP_REQUESTED, handler)
        await broker.subscribe(ITINERARY_PROPOSED, handler)
        await broker.run()


if __name__ == "__main__":
    asyncio.run(main())
