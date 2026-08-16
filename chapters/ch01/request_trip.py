"""Plays the customer at the front door: requests a trip, then waits — without
blocking anything — for the itinerary to arrive as an event.

Chapter 2's Booking Agent takes over this front-door role; until then, this
script stands in for it.
"""

import asyncio
import logging
import os

from travel_agency import console
from travel_agency.broker import Event
from travel_agency.event_types import ITINERARY_PROPOSED, TRIP_REQUESTED
from travel_agency.kafka_broker import KafkaEventBroker

SOURCE = "RequestTripScript"

# The Kafka client logs routine metadata chatter at WARNING (for example
# "Topic ... not found" before the first reply ever creates the topic).
# Keep only real errors; the demo's own output is the show.
logging.getLogger("aiokafka").setLevel(logging.ERROR)

# The running example from chapter 1: the Lisbon trip for two.
TRIP = {
    "origin": "New York (JFK)",
    "destination": "Lisbon",
    "travelers": 2,
    "notes": "Ten days in June, with a three-day side trip to Madrid.",
}


def is_reply_to(request_id: str, event: Event) -> bool:
    """A reply names the event it answers — chapter 2 calls this causation."""
    return event.payload.get("request_id") == request_id


async def main() -> None:
    async with KafkaEventBroker(
        os.environ["KAFKA_BOOTSTRAP_SERVERS"], client_name=SOURCE
    ) as broker:
        request_id = await broker.publish(TRIP_REQUESTED, SOURCE, TRIP)
        console.show("PUBLISHED", Event(request_id, TRIP_REQUESTED, SOURCE, TRIP))
        print("\nNothing is blocked; waiting for the reply event...\n", flush=True)

        received = asyncio.Event()

        async def show_reply(event: Event) -> None:
            if is_reply_to(request_id, event):
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
                print("Still waiting; the planner is reasoning...", flush=True)
        consuming.cancel()


if __name__ == "__main__":
    asyncio.run(main())
