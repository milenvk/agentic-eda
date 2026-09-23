"""Stands in for the shop: publishes one review, and waits for its triage as an event.

The review's words are the command's arguments, or a default when there are none.
"""

import asyncio
import sys
from uuid import uuid4

from agentic_eda import console
from agentic_eda.broker import Event
from agentic_eda.connect import event_broker
from agentic_eda.events import data_of
from review_triage.events import REVIEW_RECEIVED, REVIEW_TRIAGED, ReviewReceived

SOURCE = "SendReviewScript"
A_REVIEW = "The left shoe split at the seam after two weeks. I would like a replacement."

# The script's own output is the show; keep client libraries to real errors.
console.quiet_client_logs()


async def main() -> None:
    review = ReviewReceived(
        review_id=f"review-{uuid4().hex[:8]}",
        product="Trail Runner 2",
        text=" ".join(sys.argv[1:]) or A_REVIEW,
    )
    async with event_broker(SOURCE) as broker:
        sent = await broker.publish(
            REVIEW_RECEIVED,
            SOURCE,
            data_of(review),
            attributes={"correlationid": str(uuid4()), "partitionkey": review.review_id},
        )
        console.show("PUBLISHED", sent)
        print("\nNothing is blocked; waiting for the triage...\n", flush=True)

        triaged = asyncio.Event()

        async def show(event: Event) -> None:
            # The activator copies a request's correlationid to everything it causes.
            if getattr(event, "correlationid", None) == sent.correlationid:
                console.show("RECEIVED", event)
                triaged.set()

        await broker.subscribe(REVIEW_TRIAGED, show)
        consuming = asyncio.create_task(broker.run())
        await triaged.wait()
        consuming.cancel()


if __name__ == "__main__":
    asyncio.run(main())
