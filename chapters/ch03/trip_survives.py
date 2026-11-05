"""The trip survives the infrastructure: a request delivered twice, and a restart mid-conversation.

The third act of the demo, in two runs. `request` publishes one `booking.TripRequested` and
then the very same event again, same id and all, as a broker that promises at-least-once
delivery may do; one trip is created, and the run stops once the proposal is in. The reader
then restarts the Booking Agent, which empties its in-memory session store. `reply` sends the
approval: the agent loads the Trip from the store and approves as if nothing had happened.
The conversation's ids travel between the two runs in a small file under `data/`.
"""

import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

from customer_channel import (
    APPROVAL,
    SOURCE,
    Conversation,
    approved,
    converse,
    hang_up,
    lisbon_trip,
    row_command,
    show_itineraries,
)

from agentic_eda import console
from agentic_eda.broker import WireEvent
from agentic_eda.connect import event_broker
from travel_agency import event_types

SAVED = Path("data/trip_survives.json")


async def request() -> None:
    async with event_broker(SOURCE, start="beginning") as broker:
        conversation = Conversation(broker)
        await conversation.listen()
        listening = asyncio.create_task(broker.run())

        first = await conversation.say(lisbon_trip(conversation_id=str(uuid4())))
        again = await broker.publish(
            first.type,
            first.source,
            first.data,
            id=first.id,  # the same event: a redelivery, not a second request
            attributes={"correlationid": first.correlationid, "partitionkey": first.partitionkey},
        )
        console.show("PUBLISHED", again)
        print("\nTwo deliveries of one request; waiting to see how many trips they make...\n", flush=True)  # fmt: skip

        created = await conversation.hear()
        trip_id = created.data["trip_id"]
        while True:  # the trip goes on to planning; what must not arrive is a second TripCreated
            event = await conversation.hear()
            if event.type == event_types.TRIP_CREATED:
                print("A second trip was created: the redelivery was not recognised.", flush=True)
                sys.exit(1)
            if event.type == event_types.PROPOSAL_READY:
                break
        show_itineraries(event)
        console.success(f"one trip, {trip_id}: the redelivered request found the trip it had created.")  # fmt: skip

        SAVED.write_text(json.dumps({
            "correlation_id": conversation.correlation_id,
            "trip_id": trip_id,
            "proposal": event.model_dump(mode="json"),
        }))
        print(
            f"\nThe trip before the restart:\n"
            f"  {row_command(trip_id)}\n"
            f"\nNow restart the Booking Agent, which forgets every session it had:\n"
            f"  docker compose restart booking-agent\n"
            f"\nThen let the customer reply:\n"
            f"  docker compose --profile demo up -d --build --force-recreate demo-survives-reply\n",
            flush=True,
        )
        await hang_up(listening)


async def reply() -> None:
    if not SAVED.exists():
        print("No conversation to continue: run the request step first.", flush=True)
        sys.exit(1)
    saved = json.loads(SAVED.read_text())
    async with event_broker(SOURCE, start="beginning") as broker:
        conversation = Conversation(broker, correlation_id=saved["correlation_id"])
        await conversation.listen()
        listening = asyncio.create_task(broker.run())

        ready = WireEvent.model_validate(saved["proposal"])  # the proposal, as it arrived
        outcome = await converse(conversation, saved["trip_id"], ready, [APPROVAL])
        if outcome is not None:
            approved(outcome)
            print(
                f"\nThe trip after the restart, one version on:\n"
                f"  {row_command(saved['trip_id'])}\n",
                flush=True,
            )
        await hang_up(listening)


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else ""
    if step not in {"request", "reply"}:
        print("usage: trip_survives.py request | reply", flush=True)
        sys.exit(2)
    asyncio.run(request() if step == "request" else reply())
