"""A request delivered twice: the third act of the demo.

The script publishes one `booking.TripRequested` and then the very same event again, same id
and all, as a broker that promises at-least-once delivery may do. One trip is created: the
second delivery finds the row the first one created, and the activator logs it as already
handled without running the agent. The run stops once the proposal is in, with the command
that reads the trip's row.
"""

import asyncio
import sys
from uuid import uuid4

from customer_channel import SOURCE, Conversation, hang_up, lisbon_trip, row_command, show_itineraries

from agentic_eda import console
from agentic_eda.connect import event_broker
from travel_agency import event_types


async def main() -> None:
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
        print(f"\nThe trip, in PostgreSQL:\n  {row_command(trip_id)}\n", flush=True)
        await hang_up(listening)


if __name__ == "__main__":
    asyncio.run(main())
