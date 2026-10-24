"""A request that is no business request: it passes the contract and fails the Trip's rules.

The journeys are out of order, which no field constraint can catch, so the event validates at
the boundary and reaches the Booking Agent, whose `create` operation checks the rules in code
and answers `booking.TripRequestRejected` under the conversation's key. No trip is created and
planning is never asked.
"""

import asyncio
from uuid import uuid4

from customer_channel import Conversation, lisbon_trip

from agentic_eda import console
from agentic_eda.connect import event_broker
from travel_agency import event_types

SOURCE = "RejectedRequestScript"

console.quiet_client_logs()


async def main() -> None:
    async with event_broker(SOURCE, start="beginning") as broker:
        conversation = Conversation(broker)
        await conversation.listen()
        listening = asyncio.create_task(broker.run())

        request = lisbon_trip(conversation_id=str(uuid4()))
        request.origin_destinations.reverse()  # the way home first
        await conversation.say(request)
        print("\nThe event is valid against its contract; the Trip's rules are another matter...\n", flush=True)  # fmt: skip
        answer = await conversation.hear()
        if answer.type == event_types.TRIP_REQUEST_REJECTED:
            console.success(f"rejected under the conversation's key, with the reason: {answer.data['reason']}")  # fmt: skip
        listening.cancel()


if __name__ == "__main__":
    asyncio.run(main())
