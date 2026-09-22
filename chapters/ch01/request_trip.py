"""Plays planning's caller: asks for an itinerary, then waits — without
blocking anything — for the proposal to arrive as an event.

Chapter 3's Booking Agent takes over this role; until then, this script stands
in for it.
"""

import asyncio

from agentic_eda import console
from agentic_eda.broker import Event
from agentic_eda.connect import event_broker
from travel_agency.event_types import ITINERARY_PROPOSED, ITINERARY_REQUESTED

SOURCE = "RequestTripScript"

# The demo's own output is the show; keep client libraries to real errors.
console.quiet_client_logs()

# The running example from chapter 1: the request the opening failure loses.
TRIP = {
    "origin": "New York (JFK)",
    "destination": "Lisbon",
    "travelers": 2,
    "duration": "one week",
    "departing": "in two weeks",
    "notes": "Three days in Madrid on the way out.",
}


def is_reply_to(request_id: str, event: Event) -> bool:
    """A reply names the event it answers — chapter 2 calls this causation."""
    return event.data.get("request_id") == request_id


async def main() -> None:
    async with event_broker(SOURCE) as broker:
        request = await broker.publish(ITINERARY_REQUESTED, SOURCE, TRIP)
        console.show("PUBLISHED", request)
        print("\nNothing is blocked; waiting for the reply event...\n", flush=True)

        received = asyncio.Event()

        async def show_reply(event: Event) -> None:
            if is_reply_to(request.id, event):
                print(flush=True)
                console.show("RECEIVED", event)
                print(flush=True)
                console.success("SUCCESS: the itinerary arrived as the reply event.")
                print(
                    "The reply's request_id names our request;"
                    " that is how this script matched it.",
                    flush=True,
                )
                received.set()

        await broker.subscribe(ITINERARY_PROPOSED, show_reply)
        consuming = asyncio.create_task(broker.run())
        while True:
            try:
                await asyncio.wait_for(received.wait(), timeout=15)
                break
            except TimeoutError:
                print("Haven't received the itinerary yet...", flush=True)
        consuming.cancel()


if __name__ == "__main__":
    asyncio.run(main())
