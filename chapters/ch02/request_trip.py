"""The customer's seat: asks planning for itineraries, and waits for the proposal as an event.

A request starts a thread. The script generates the thread's `correlationid`, and the Planner's
activator copies it to everything the request causes, so a proposal is matched to its
request by that label alone.
"""

import asyncio
import time
from datetime import date
from uuid import uuid4

from agentic_eda import console
from agentic_eda.broker import WireEvent, EventBroker
from agentic_eda.connect import event_broker
from agentic_eda.contracts import data_of
from travel_agency.event_types import ITINERARY_PROPOSED, ITINERARY_REQUESTED
from travel_agency.events.planning import (
    ItineraryProposed,
    ItineraryRequested,
    Money,
    OriginDestination,
    Stay,
)

SOURCE = "RequestTripScript"

# The demo's own output is the show; keep client libraries to real errors.
console.quiet_client_logs()


def lisbon_trip() -> ItineraryRequested:
    """The running example: New York to Lisbon for two, with three days in Madrid on the way."""
    return ItineraryRequested(
        trip_id=new_trip_id(),
        origin_destinations=[
            journey("NYC", "MAD", date(2027, 5, 10)),
            journey("MAD", "LIS", date(2027, 5, 13)),
            journey("LIS", "NYC", date(2027, 5, 17)),
        ],
        stays=[
            Stay(city="MAD", check_in=date(2027, 5, 10), check_out=date(2027, 5, 13), rooms=1),
            Stay(city="LIS", check_in=date(2027, 5, 13), check_out=date(2027, 5, 17), rooms=1),
        ],
        adults=2,
        children=[],
        budget=Money(amount=2800, currency="USD"),
        preferences="Quiet, walkable neighbourhoods. We would take a stop to save real money.",
        car_class=None,
    )


def journey(
    origin: str, destination: str, on: date, window: int | None = None
) -> OriginDestination:
    """A journey on a date, or within so many days before and after it."""
    return OriginDestination(
        origin=origin,
        destination=destination,
        departure_date=on,
        days_before=window,
        days_after=window,
    )


def new_trip_id() -> int:
    """The Booking Agent assigns trip ids from chapter 3; until then the script picks one."""
    return time.time_ns()


async def request_itineraries(broker: EventBroker, trip: ItineraryRequested) -> WireEvent:
    """Publish one request as the first event of a new thread."""
    request = await broker.publish(
        ITINERARY_REQUESTED,
        SOURCE,
        data_of(trip),
        attributes={"correlationid": str(uuid4())},
    )
    console.show("PUBLISHED", request)
    return request


def answers(request: WireEvent, event: WireEvent) -> bool:
    """A proposal answers a request when both carry the same thread's label."""
    return getattr(event, "correlationid", None) == request.correlationid


async def show_proposals(broker: EventBroker, requests: list[WireEvent], patience: float | None = None):
    """Show each request's proposal as it arrives, until all are answered or patience ends."""
    unanswered = list(requests)
    all_answered = asyncio.Event()

    async def show(event: WireEvent) -> None:
        request = next((r for r in unanswered if answers(r, event)), None)
        if request is None:
            return  # another thread's proposal
        unanswered.remove(request)
        print(flush=True)
        console.show("RECEIVED", event)
        for itinerary in ItineraryProposed.model_validate(event.data).itineraries:
            total = itinerary.total
            print(f"  {itinerary.rank}. {itinerary.label}: {total.amount:,.0f} {total.currency}")
        console.success(f"the proposal for {request.data['trip_id']} arrived on its request's thread.")
        if not unanswered:
            all_answered.set()

    await broker.subscribe(ITINERARY_PROPOSED, show)
    consuming = asyncio.create_task(broker.run())
    waited = 0
    while not all_answered.is_set() and (patience is None or waited < patience):
        try:
            await asyncio.wait_for(all_answered.wait(), timeout=15)
        except TimeoutError:
            waited += 15
            print(f"Still waiting for {len(unanswered)} proposal(s)...", flush=True)
    consuming.cancel()
    return unanswered


async def main() -> None:
    async with event_broker(SOURCE) as broker:
        request = await request_itineraries(broker, lisbon_trip())
        print("\nNothing is blocked; waiting for the proposal...\n", flush=True)
        await show_proposals(broker, [request])


if __name__ == "__main__":
    asyncio.run(main())
