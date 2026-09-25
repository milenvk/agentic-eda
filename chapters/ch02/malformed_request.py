"""Act 2: a request that breaks its contract, published by a careless writer.

Nothing stops a publisher from writing bad data: the port takes any dictionary. The
contract is enforced where the event is consumed, at the Planner's activator, which
rejects the event before the agent or the model ever sees it.
"""

import asyncio
from uuid import uuid4

from request_trip import SOURCE, new_trip_id, show_proposals

from agentic_eda import console
from agentic_eda.connect import event_broker
from travel_agency.event_types import ITINERARY_REQUESTED

PATIENCE_SECONDS = 30

# No stops, no travellers, and a budget that is not money.
NOT_A_TRIP = {
    "trip_id": new_trip_id(),
    "origin": "New York",
    "stops": [],
    "travellers": 0,
    "budget": "cheap",
    "preferences": "Surprise me.",
    "car_class": None,
}


async def main() -> None:
    async with event_broker(SOURCE) as broker:
        request = await broker.publish(
            ITINERARY_REQUESTED,
            SOURCE,
            NOT_A_TRIP,
            attributes={"correlationid": str(uuid4()), "partitionkey": str(NOT_A_TRIP["trip_id"])},
        )
        console.show("PUBLISHED", request)
        print("\nThe broker took it. Waiting to see whether planning does...\n", flush=True)

        unanswered = await show_proposals(broker, [request], patience=PATIENCE_SECONDS)
        if unanswered:
            console.success(
                "no proposal came: the Planner's activator rejected the event at its boundary."
            )
            print("Its log says which fields broke the contract.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
