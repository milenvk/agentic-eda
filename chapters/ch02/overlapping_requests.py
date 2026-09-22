"""Act 3: two customers at once, and one audit record that still reads as two stories.

Both requests are published before either is answered, so their events interleave on
the broker. Each proposal carries its request's `correlationid`, which is all it takes
to pull one thread out of the record afterwards.
"""

import asyncio
from datetime import date

from request_trip import SOURCE, new_trip_id, request_itineraries, show_proposals

from agentic_eda.connect import event_broker
from travel_agency.events.planning import ItineraryRequested, Money, Stop


def nairobi_trip() -> ItineraryRequested:
    return ItineraryRequested(
        trip_id=new_trip_id(),
        origin="São Paulo",
        stops=[Stop(city="Nairobi", arrive=date(2027, 7, 2), depart=date(2027, 7, 9))],
        travellers=1,
        budget=Money(amount=3500, currency="USD"),
        preferences="Close to wildlife, somewhere calm. Price matters more than speed.",
        car_class=None,
    )


def sydney_trip() -> ItineraryRequested:
    return ItineraryRequested(
        trip_id=new_trip_id(),
        origin="Tokyo",
        stops=[
            Stop(city="Sydney", arrive=date(2027, 7, 3), depart=date(2027, 7, 7)),
            Stop(city="Auckland", arrive=date(2027, 7, 7), depart=date(2027, 7, 11)),
        ],
        travellers=4,
        budget=None,  # no limit set
        preferences="A family of four. Near the water, nothing noisy at night, nonstop flights.",
        car_class=None,
    )


async def main() -> None:
    async with event_broker(SOURCE) as broker:
        requests = [
            await request_itineraries(broker, nairobi_trip()),
            await request_itineraries(broker, sydney_trip()),
        ]
        print("\nTwo threads are open. To read one of them from the audit record:\n", flush=True)
        for request in requests:
            print(f"  grep {request.correlationid} data/audit.log", flush=True)
        print(flush=True)
        await show_proposals(broker, requests)


if __name__ == "__main__":
    asyncio.run(main())
