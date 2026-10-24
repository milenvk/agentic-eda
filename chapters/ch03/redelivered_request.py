"""The same request delivered twice, as a broker that promises at-least-once delivery may do.

The script publishes one `booking.TripRequested` and then the very same event again, same id
and all. The Booking Agent creates one trip: the store keeps the request's event id under a
unique index, so the second delivery finds the trip the first one created, sees the event
already handled, and acknowledges it with no event produced a second time.
"""

import asyncio
from uuid import uuid4

from customer_channel import Conversation, lisbon_trip

from agentic_eda import console
from agentic_eda.connect import event_broker
from travel_agency import event_types

SOURCE = "RedeliveredRequestScript"

console.quiet_client_logs()


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
        # The trip goes on to planning like any other; what must not arrive is a second TripCreated.
        deadline = asyncio.get_running_loop().time() + 30
        while True:
            try:
                event = await asyncio.wait_for(
                    conversation.arrived.get(), timeout=deadline - asyncio.get_running_loop().time()
                )
            except TimeoutError:
                console.success(f"one trip, {created.data['trip_id']}: the redelivered request found the trip it had created.")  # fmt: skip
                break
            console.show("RECEIVED", event)
            if event.type == event_types.TRIP_CREATED:
                print("A second trip was created: the redelivery was not recognised.", flush=True)
                break
        listening.cancel()


if __name__ == "__main__":
    asyncio.run(main())
