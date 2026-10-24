"""Runs the Audit Consumer against the configured broker."""

import asyncio
import functools
import os

from agentic_eda import console
from agentic_eda.connect import event_broker
from travel_agency import event_types

from .consumer import SOURCE, record

# One subscription per event type the system has so far; chapter 4 replaces this list
# with a single subscribe-all.
EVENT_TYPES = [
    event_types.TRIP_REQUESTED,
    event_types.TRIP_REQUEST_REJECTED,
    event_types.TRIP_CREATED,
    event_types.ITINERARY_REQUESTED,
    event_types.ITINERARY_PROPOSED,
    event_types.PROPOSAL_READY,
    event_types.CUSTOMER_REPLIED,
    event_types.ITINERARY_APPROVED,
    event_types.ITINERARY_REJECTED,
    event_types.TRIP_CHANGED,
    event_types.CLARIFICATION_REQUESTED,
]


async def main() -> None:
    console.configure_logging()
    handler = functools.partial(record, os.environ.get("AUDIT_LOG", "/data/audit.log"))
    async with event_broker(SOURCE) as broker:
        for event_type in EVENT_TYPES:
            await broker.subscribe(event_type, handler)
        await broker.run()


if __name__ == "__main__":
    asyncio.run(main())
