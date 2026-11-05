"""The customer changes their mind: a question, a change of dates, and a second proposal.

The second act of the demo. The first reply says too little to act on, so booking asks a
question; the second reply answers it with a change, which the Trip applies to every journey
before planning is asked again; the third approves the new proposal.
"""

import asyncio

from customer_channel import (
    APPROVAL,
    SOURCE,
    Conversation,
    approved,
    converse,
    hang_up,
    open_trip,
)

from agentic_eda.connect import event_broker

# A customer's words, in the order the conversation goes.
REPLIES = [
    "Thanks, got it.",  # too little to act on: a question comes back
    "Could we leave a day later? The fares on that day are too high.",  # a change, and a re-plan
    APPROVAL,  # an approval, by description
]


async def main() -> None:
    async with event_broker(SOURCE, start="beginning") as broker:
        conversation = Conversation(broker)
        await conversation.listen()
        listening = asyncio.create_task(broker.run())

        opened = await open_trip(conversation)
        if opened is None:
            return
        trip_id, ready = opened
        outcome = await converse(conversation, trip_id, ready, REPLIES)
        if outcome is not None:
            approved(outcome)
        await hang_up(listening)


if __name__ == "__main__":
    asyncio.run(main())
