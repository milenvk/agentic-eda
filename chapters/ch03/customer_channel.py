"""The customer channel, as a script: it asks for a trip and replies in a customer's words.

Until the Front Desk arrives in chapter 4, this script writes `booking.TripRequested` and
`booking.CustomerReplied` in booking's published language, and shows what booking publishes
back. The script generates the workflow's `correlationid` and matches every event by it; the
trip's id it learns from `booking.TripCreated`, since the store assigns it. One conversation:
the request, the proposal, and four replies, one per outcome, each sent once the previous
outcome has arrived.
"""

import asyncio
import sys
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

# A customer's words, one reply per outcome, in the order the conversation goes.
REPLIES = [
    "Sounds good.",  # too little to act on: a question comes back
    "Could we leave a day later? The fares on that day are too high.",  # a change, and a re-plan
    "No, all of these are too expensive for what they offer.",  # a rejection, and a re-plan
    "The one with the morning flight, please.",  # an approval, by description
]

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


class Conversation:
    """One workflow as the channel sees it: what it publishes, and what comes back for it."""

    def __init__(self, broker: EventBroker) -> None:
        self.broker = broker
        self.correlation_id = str(uuid4())
        self.arrived: asyncio.Queue[WireEvent] = asyncio.Queue()

    async def listen(self) -> None:
        for event_type in TO_THE_CUSTOMER:
            await self.broker.subscribe(event_type, self._receive)

    async def _receive(self, event: WireEvent) -> None:
        if getattr(event, "correlationid", None) == self.correlation_id:
            await self.arrived.put(event)

    async def say(self, fact, causation: WireEvent | None = None) -> WireEvent:
        attributes = {"correlationid": self.correlation_id}
        if causation is not None:
            attributes["causationid"] = causation.id
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


async def main() -> None:
    # Booking answers a request within a second, before a fresh subscription has settled, so
    # the channel asks for history: it then reads what was published while it was joining.
    async with event_broker(SOURCE, start="beginning") as broker:
        conversation = Conversation(broker)
        await conversation.listen()
        listening = asyncio.create_task(broker.run())

        request = await conversation.say(lisbon_trip(conversation_id=str(uuid4())))
        print("\nNothing is blocked; waiting for booking's answer...\n", flush=True)
        answer = await conversation.hear()
        if answer.type == event_types.TRIP_REQUEST_REJECTED:
            console.success("booking rejected the request, and no itinerary was planned for it.")
            return
        trip_id = answer.data["trip_id"]
        console.success(f"the trip is {trip_id}: the store assigned the id, booking announced it.")

        ready = await conversation.hear()
        show_itineraries(ready)
        for words in REPLIES:
            print(f'\nThe customer replies: "{words}"\n', flush=True)
            reply = CustomerReplied(trip_id=trip_id, proposal_id=ready.data["proposal_id"], words=words)  # fmt: skip
            await conversation.say(reply, causation=ready)
            outcome = await conversation.hear()
            if outcome.type in BACK_TO_PLANNING:
                print("\nBack to planning; waiting for the next proposal...\n", flush=True)
                ready = await conversation.hear()
                show_itineraries(ready)
            if outcome.type in ENDS_THE_WORKFLOW:
                break
        else:
            console.success("the customer ran out of replies before approving.")
            return
        console.success(
            f"itinerary {outcome.data['rank']} of proposal {outcome.data['proposal_id']} is approved."
        )
        print(
            f"\nThe whole workflow, in the audit record:\n"
            f"  grep {conversation.correlation_id} data/audit.log\n",
            flush=True,
        )
        listening.cancel()


if __name__ == "__main__":
    asyncio.run(main())
