"""The Itinerary Planner Agent, in its chapter 1 form.

An agent is a loop that calls an LLM: this one consumes a trip request, reasons
over it once, and publishes the proposed itinerary. No framework — the
EventBroker interface is all it knows about the world outside the model.
"""

import logging
import os

import litellm

from travel_agency.broker import Event, EventBroker
from travel_agency.event_types import ITINERARY_PROPOSED

SOURCE = "ItineraryPlannerAgent"

PROMPT = """\
You are the itinerary planner of a travel agency. Propose a day-by-day itinerary
for the following trip request, with flight and hotel suggestions and a short
rationale for your choices:

{request}
"""

log = logging.getLogger(SOURCE)


async def plan(broker: EventBroker, event: Event) -> None:
    """Handle one TripRequested event: reason, then answer with a proposal.

    The reply carries the request event's id, which is how the requester matches
    the answer to its question.
    """
    log.info("planning trip %s ...", event.id)
    response = await litellm.acompletion(
        model=os.environ["LLM_MODEL"],
        messages=[{"role": "user", "content": PROMPT.format(request=event.payload)}],
    )
    itinerary = response.choices[0].message.content
    reply_id = await broker.publish(
        ITINERARY_PROPOSED,
        SOURCE,
        {"request_id": event.id, "itinerary": itinerary},
    )
    log.info("proposed itinerary %s for trip %s", reply_id, event.id)
