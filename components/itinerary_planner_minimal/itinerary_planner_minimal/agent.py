"""The Itinerary Planner Agent, in its chapter 1 form.

An agent is a loop that calls an LLM: this one consumes a planning request,
reasons over it once, and publishes the proposed itinerary. No framework — the
EventBroker interface is all it knows about the world outside the model.
"""

import asyncio
import json
import logging
import os
import time

import litellm

from agentic_eda.broker import WireEvent, EventBroker
from travel_agency.event_types import ITINERARY_PROPOSED

SOURCE = "ItineraryPlannerAgent"

# The proposal keeps the shape every later chapter uses: ranked itineraries, each
# with its items in travel order. This Planner proposes one itinerary.
PROMPT = """\
You are the itinerary planner of a travel agency. Propose one itinerary for the
trip request below. Answer with a JSON object of the form
{{"itineraries": [{{"label": "...", "rationale": "...", "items": [...]}}]}}
holding exactly one itinerary: a short "label" for what it optimises, a short
"rationale" for your choices, and "items" in travel order, each either
{{"kind": "flight", "from": "...", "to": "...", "date": "...", "notes": "..."}} or
{{"kind": "stay", "city": "...", "hotel": "...", "check_in": "...", "check_out": "..."}}.

{request}
"""

log = logging.getLogger(SOURCE)


async def plan(broker: EventBroker, event: WireEvent) -> None:
    """Handle one ItineraryRequested event: reason, then answer with a proposal.

    The reply carries the request event's id, which is how the requester matches
    the answer to its question.
    """
    log.info("planning trip %s ...", event.id)
    started = time.monotonic()
    response = await litellm.acompletion(
        model=os.environ["LLM_MODEL"],
        messages=[{"role": "user", "content": PROMPT.format(request=event.data)}],
        response_format={"type": "json_object"},
    )
    proposal = json.loads(response.choices[0].message.content)
    await _hold_until_planning_time(started)
    reply = await broker.publish(
        ITINERARY_PROPOSED,
        SOURCE,
        {"request_id": event.id, "itineraries": proposal["itineraries"]},
    )
    log.info("proposed itinerary %s for trip %s", reply.id, event.id)


async def _hold_until_planning_time(started: float) -> None:
    """The chapter's Planner spends 45 seconds on a request. A model that
    answers faster would end the durability demo before the reader can kill
    anything, so the reply is held until the mark. PLANNING_SECONDS in .env
    changes it; 0 removes the hold."""
    planning_seconds = float(os.environ.get("PLANNING_SECONDS", "45"))
    elapsed = time.monotonic() - started
    remaining = planning_seconds - elapsed
    if remaining > 0:
        log.info(
            "reasoning finished in %.1fs; holding the reply to simulate %.0fs latency",
            elapsed,
            planning_seconds,
        )
        await asyncio.sleep(remaining)
