"""The customer channel, as a script: it asks for a trip and replies in a customer's words.

Until the Front Desk arrives in chapter 4, this script writes `booking.TripRequested` and
`booking.CustomerReplied` in booking's published language, and shows what booking publishes
back. The script generates the workflow's `correlationid` and matches every event by it; the
trip's id it learns from `booking.TripCreated`, since the store assigns it.

Run on its own, it is the demo's first act: one request, one proposal, one reply that approves
an itinerary. The other acts import the channel from here and send their own replies.
"""

import asyncio
import sys
from contextlib import suppress
from datetime import date, timedelta
from uuid import uuid4

from agentic_eda import console
from agentic_eda.broker import EventBroker, WireEvent
from agentic_eda.connect import event_broker
from agentic_eda.publishing import publish_fact
from travel_agency import event_types
from travel_agency.events.booking import (
    CustomerReplied,
    ProposalReady,
    TripRequested,
)
from travel_agency.events.planning import Money, OriginDestination, Stay

SOURCE = "CustomerChannelScript"
PATIENCE = 300  # seconds to wait for one event; planning on a local model takes a while

# The events the channel reads, and the one that ends the conversation.
TO_THE_CUSTOMER = [
    event_types.TRIP_CREATED,
    event_types.TRIP_REQUEST_REJECTED,
    event_types.PROPOSAL_READY,
    event_types.CLARIFICATION_REQUESTED,
    event_types.ITINERARY_APPROVED,
    event_types.ITINERARY_REJECTED,
    event_types.TRIP_CHANGED,
]
ENDS_THE_WORKFLOW = {event_types.TRIP_REQUEST_REJECTED, event_types.ITINERARY_APPROVED}
# A rejection or a change sends the trip back to planning: the next thing to wait for is a proposal.
BACK_TO_PLANNING = {event_types.ITINERARY_REJECTED, event_types.TRIP_CHANGED}

# The customer's words that approve an itinerary by description rather than by number.
APPROVAL = "The cheapest one, please."

CITY_NAMES = {"NYC": "New York", "MAD": "Madrid", "LIS": "Lisbon"}

# The demo's own output is the show; keep client libraries to real errors.
console.quiet_client_logs()


def lisbon_trip(conversation_id: str) -> TripRequested:
    """The running example: New York to Lisbon for two, with three days in Madrid on the way."""
    leaving = date.today() + timedelta(days=180)
    return TripRequested(
        conversation_id=conversation_id,
        origin_destinations=[
            journey("NYC", "MAD", leaving),
            journey("MAD", "LIS", leaving + timedelta(days=3)),
            journey("LIS", "NYC", leaving + timedelta(days=7)),
        ],
        stays=[
            Stay(city="MAD", check_in=leaving, check_out=leaving + timedelta(days=3), rooms=1),
            Stay(city="LIS", check_in=leaving + timedelta(days=3), check_out=leaving + timedelta(days=7), rooms=1),  # fmt: skip
        ],
        adults=2,
        children=[],
        budget=Money(amount=3500, currency="USD"),
        preferences="Quiet, walkable neighbourhoods. We would take a stop to save real money.",
        car_class=None,
    )


def journey(origin: str, destination: str, on: date) -> OriginDestination:
    return OriginDestination(origin=origin, destination=destination, departure_date=on)


def in_words(request: TripRequested) -> str:
    """The request as a customer would say it, before it becomes an event."""
    legs = ", ".join(
        f"{CITY_NAMES.get(j.origin, j.origin)} to {CITY_NAMES.get(j.destination, j.destination)}"
        f" on {j.departure_date.day} {j.departure_date:%B %Y}"
        for j in request.origin_destinations
    )
    budget = f"{request.budget.amount:,.0f} {request.budget.currency}"
    return f"{request.adults} adults, {legs}, with a budget of {budget}."


class Conversation:
    """One workflow as the channel sees it: what it publishes, and what comes back for it."""

    def __init__(self, broker: EventBroker, correlation_id: str | None = None) -> None:
        self.broker = broker
        self.correlation_id = correlation_id or str(uuid4())
        self.arrived: asyncio.Queue[WireEvent] = asyncio.Queue()

    async def listen(self) -> None:
        for event_type in TO_THE_CUSTOMER:
            await self.broker.subscribe(event_type, self._receive)

    async def _receive(self, event: WireEvent) -> None:
        if getattr(event, "correlationid", None) == self.correlation_id:
            await self.arrived.put(event)

    async def say(self, fact, caused_by: str | None = None) -> WireEvent:
        attributes = {"correlationid": self.correlation_id}
        if caused_by is not None:
            attributes["causationid"] = caused_by
        event = await publish_fact(self.broker, SOURCE, fact, attributes)
        console.show("PUBLISHED", event)
        return event

    async def hear(self) -> WireEvent:
        """The next event booking publishes for this workflow."""
        waited = 0
        while True:
            try:
                event = await asyncio.wait_for(self.arrived.get(), timeout=15)
            except TimeoutError:
                waited += 15
                if waited >= PATIENCE:
                    console.success(f"nothing arrived in {PATIENCE} seconds; giving up.")
                    sys.exit(1)
                print("Still waiting...", flush=True)
                continue
            print(flush=True)
            console.show("RECEIVED", event)
            return event


def show_itineraries(ready: WireEvent) -> None:
    for itinerary in ProposalReady.model_validate(ready.data).itineraries:
        total = itinerary.total
        print(f"  {itinerary.rank}. {itinerary.label}: {total.amount:,.0f} {total.currency}")


async def open_trip(conversation: Conversation) -> tuple[int, WireEvent] | None:
    """Ask for the trip and wait for the first proposal; None when booking refused the request."""
    request = lisbon_trip(conversation_id=str(uuid4()))
    print(f"\nThe customer asks for: {in_words(request)}\n", flush=True)
    await conversation.say(request)
    print("\nNothing is blocked; waiting for booking's answer...\n", flush=True)
    answer = await conversation.hear()
    if answer.type == event_types.TRIP_REQUEST_REJECTED:
        console.success("booking refused the request, and no itinerary was planned for it.")
        return None
    trip_id = answer.data["trip_id"]
    console.success(f"the trip is {trip_id}: the store assigned the id, booking announced it.")
    ready = await conversation.hear()
    show_itineraries(ready)
    return trip_id, ready


async def converse(conversation: Conversation, trip_id: int, ready: WireEvent, replies: list[str]) -> WireEvent | None:  # fmt: skip
    """Send the replies one by one, each once the previous outcome is in; the approval, or None."""
    question = None  # the question the next reply answers, when booking asked one
    for words in replies:
        print(f'\nThe customer replies: "{words}"\n', flush=True)
        reply = CustomerReplied(trip_id=trip_id, proposal_id=ready.data["proposal_id"], words=words, answering=question)  # fmt: skip
        await conversation.say(reply, caused_by=ready.id)
        outcome = await conversation.hear()
        question = outcome.data["question"] if outcome.type == event_types.CLARIFICATION_REQUESTED else None  # fmt: skip
        if outcome.type in BACK_TO_PLANNING:
            print("\nBack to planning; waiting for the next proposal...\n", flush=True)
            ready = await conversation.hear()
            show_itineraries(ready)
        if outcome.type in ENDS_THE_WORKFLOW:
            return outcome
    console.success("the customer ran out of replies before approving.")
    return None


def approved(outcome: WireEvent) -> None:
    console.success(
        f"itinerary {outcome.data['rank']} of proposal {outcome.data['proposal_id']} is approved."
    )


async def hang_up(listening: asyncio.Task) -> None:
    """Stop reading, and let the broker leave the group before the connection closes."""
    listening.cancel()
    with suppress(asyncio.CancelledError):
        await listening


def row_command(trip_id: int) -> str:
    return f'docker compose exec postgres psql -U agency -c "select id, status, version from trips where id = {trip_id}"'  # fmt: skip


async def main() -> None:
    # Booking answers a request within a second, before a fresh subscription has settled, so
    # the channel asks for history: it then reads what was published while it was joining.
    async with event_broker(SOURCE, start="beginning") as broker:
        conversation = Conversation(broker)
        await conversation.listen()
        listening = asyncio.create_task(broker.run())

        opened = await open_trip(conversation)
        if opened is None:
            return
        trip_id, ready = opened
        outcome = await converse(conversation, trip_id, ready, [APPROVAL])
        if outcome is not None:
            approved(outcome)
            print(
                f"\nThe whole workflow, in the audit record:\n"
                f"  grep {conversation.correlation_id} data/audit.log | wc -l\n"
                f"\nThe trip, in PostgreSQL:\n"
                f"  {row_command(trip_id)}\n",
                flush=True,
            )
        await hang_up(listening)


if __name__ == "__main__":
    asyncio.run(main())
