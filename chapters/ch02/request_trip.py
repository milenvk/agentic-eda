"""The customer's seat: asks planning for itineraries, and waits for the proposal as an event.

A request starts a thread. The script mints the thread's `correlationid`, and the Planner's
container copies it to everything the request causes, so a proposal is matched to its
request by that label alone. The `partitionkey` is the trip's id: one trip's events stay
in order, and two trips never wait for each other.
"""

import asyncio
from datetime import date
from uuid import uuid4

from travel_agency import console
from travel_agency.broker import Event, EventBroker
from travel_agency.connect import event_broker
from travel_agency.event_types import ITINERARY_PROPOSED, ITINERARY_REQUESTED
from travel_agency.events import data_of
from travel_agency.events.planning import ItineraryProposed, ItineraryRequested, Money, Stop

SOURCE = "RequestTripScript"

# The demo's own output is the show; keep client libraries to real errors.
console.quiet_client_logs()


def lisbon_trip() -> ItineraryRequested:
    """The running example: New York to Lisbon for two, with three days in Madrid on the way."""
    return ItineraryRequested(
        trip_id=new_trip_id(),
        origin="New York",
        stops=[
            Stop(city="Madrid", arrive=date(2027, 5, 10), depart=date(2027, 5, 13)),
            Stop(city="Lisbon", arrive=date(2027, 5, 13), depart=date(2027, 5, 17)),
        ],
        travellers=2,
        budget=Money(amount=2800, currency="USD"),
        preferences="Quiet, walkable neighbourhoods. We would take a stop to save real money.",
        car_class=None,
    )


def new_trip_id() -> str:
    return f"trip-{uuid4().hex[:8]}"


async def request_itineraries(broker: EventBroker, trip: ItineraryRequested) -> Event:
    """Publish one request as the first event of a new thread."""
    request = await broker.publish(
        ITINERARY_REQUESTED,
        SOURCE,
        data_of(trip),
        attributes={"correlationid": str(uuid4()), "partitionkey": trip.trip_id},
    )
    console.show("PUBLISHED", request)
    return request


def answers(request: Event, event: Event) -> bool:
    """A proposal answers a request when both carry the same thread's label."""
    return getattr(event, "correlationid", None) == request.correlationid


async def show_proposals(broker: EventBroker, requests: list[Event], patience: float | None = None):
    """Show each request's proposal as it arrives, until all are answered or patience ends."""
    unanswered = list(requests)
    all_answered = asyncio.Event()

    async def show(event: Event) -> None:
        request = next((r for r in unanswered if answers(r, event)), None)
        if request is None:
            return  # another thread's proposal
        unanswered.remove(request)
        print(flush=True)
        console.show("RECEIVED", event)
        for itinerary in ItineraryProposed.model_validate(event.data).itineraries:
            total = itinerary.total
            print(f"  {itinerary.rank}. {itinerary.label}: {total.amount:,.0f} {total.currency}")
        console.success(f"the proposal for {request.partitionkey} arrived on its request's thread.")
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
