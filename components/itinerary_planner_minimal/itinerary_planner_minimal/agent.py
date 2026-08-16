"""The Itinerary Planner Agent, in its chapter 1 form.

An agent is a loop that calls an LLM: this one consumes a trip request, reasons
over it once, and publishes the proposed itinerary. No framework — the
EventBroker interface is all it knows about the world outside the model.
"""

import asyncio
import logging
import os
import time

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
    started = time.monotonic()
    response = await litellm.acompletion(
        model=os.environ["LLM_MODEL"],
        messages=[{"role": "user", "content": PROMPT.format(request=event.payload)}],
    )
    itinerary = response.choices[0].message.content
    await _hold_until_planning_time(started)
    reply_id = await broker.publish(
        ITINERARY_PROPOSED,
        SOURCE,
        {"request_id": event.id, "itinerary": itinerary},
    )
    log.info("proposed itinerary %s for trip %s", reply_id, event.id)


async def _hold_until_planning_time(started: float) -> None:
    """The chapter's Planner spends 45 seconds on a request. A model that
    answers faster would end the durability demo before the reader can kill
    anything, so the reply is held until the mark. PLANNING_SECONDS in .env
    changes it; 0 removes the hold."""
    planning_seconds = float(os.environ.get("PLANNING_SECONDS", "45"))
    remaining = planning_seconds - (time.monotonic() - started)
    if remaining > 0:
        log.info(
            "reasoning finished early; holding the reply until the %.0fs mark",
            planning_seconds,
        )
        await asyncio.sleep(remaining)
