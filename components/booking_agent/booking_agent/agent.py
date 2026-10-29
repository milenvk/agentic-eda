"""The Booking Agent: an ADK custom agent over the Trip.

Every activation is one of the Trip's operations. The agent dispatches on the inbound
event's class: a request, planning's proposal, and the trip's own events are one operation
call each, with no LLM; the customer's reply, written in the customer's words, runs an LLM
whose tools are the Trip's four reply operations themselves, bound by the library's
`StateOperations`. The LLM proposes an operation by calling its tool, the operation accepts
or refuses, and a refusal returns to the LLM as the tool's result. Nothing here knows about
the broker or the store: what the agent consumes and produces is declared where it is
hosted, in `app.py`, and the Trip under activation comes from the activator.
"""

import logging
from collections.abc import AsyncGenerator
from datetime import date

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.events import Event
from google.adk.models import BaseLlm

from agentic_eda import eda
from agentic_eda.adk import StateOperations
from travel_agency.events.booking import CustomerReplied, TripCreated, TripRequested, TripRequirements
from travel_agency.events.planning import Itinerary, ItineraryProposed

from .prompts import render
from .trip import Trip

log = logging.getLogger("BookingAgent")


async def reply_instruction(context: ReadonlyContext) -> str:
    """The prompt for reading one reply: the trip and the proposal it is about."""
    activation = eda.activation()
    trip: Trip = activation.state
    reply: CustomerReplied = activation.request
    proposal = next((p for p in trip.proposals if p.proposal_id == reply.proposal_id), None)
    pending = trip.pending_question
    return render(
        "reply",
        requirements=_requirements(trip.requirements),
        proposal_id=reply.proposal_id,
        itineraries="\n".join(_line(i) for i in proposal.itineraries) if proposal else "none",
        pending_question=pending.question if pending else "",  # no question: the line is left out
        today=date.today().isoformat(),
    )


def _requirements(requirements: TripRequirements) -> str:
    """The requirements as the LLM reads them: the journeys numbered in travel order, each with its date."""
    journeys = "\n".join(
        f"{n}. {j.origin} to {j.destination}, leaving {j.departure_date}"
        for n, j in enumerate(requirements.origin_destinations, 1)
    )
    stays = "; ".join(f"{s.city} {s.check_in} to {s.check_out}" for s in requirements.stays) or "none"
    budget = f"{requirements.budget.amount:,.0f} {requirements.budget.currency}" if requirements.budget else "none"
    return (
        f"{requirements.adults} adults, {len(requirements.children)} children, budget {budget}, "
        f"preferences: {requirements.preferences or 'none'}\nJourneys, in travel order:\n{journeys}\nStays: {stays}"
    )


def _line(itinerary: Itinerary) -> str:
    """One itinerary as the LLM reads it: what the customer would describe it by."""
    parts = []
    for item in itinerary.items:
        if item.kind == "flight":
            first, last = item.segments[0], item.segments[-1]
            when = f"{_time_of_day(first.departs.hour)} flight, {first.departs:%a %d %b %H:%M}"
            parts.append(f"{when}, {first.origin} to {last.destination}")
        else:
            parts.append(f"{item.hotel} in {item.city} {item.check_in} to {item.check_out}")
    total = itinerary.total
    return f"{itinerary.rank}. {itinerary.label}, {total.amount:,.0f} {total.currency}: {'; '.join(parts)}. {itinerary.rationale}"  # fmt: skip


def _time_of_day(hour: int) -> str:
    """The word a customer uses for a departure time."""
    return "morning" if hour < 12 else "afternoon" if hour < 17 else "evening" if hour < 21 else "night"  # fmt: skip


class BookingAgent(BaseAgent):
    """Dispatches on the event's class: code for the bookkeeping, the LLM for the reply."""

    reply: LlmAgent

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        activation = eda.activation()
        request, trip = activation.request, activation.state
        if isinstance(request, CustomerReplied):
            async for event in self.reply.run_async(ctx):
                yield event
        elif isinstance(request, TripRequested):
            activation.answer(trip.create(request))
        elif isinstance(request, ItineraryProposed):
            activation.answer(trip.record_proposal(request))
        elif isinstance(request, TripCreated):
            activation.answer(trip.request_planning())
        else:  # the trip's own ItineraryRejected or TripChanged: planning hears why
            activation.answer(trip.request_planning(reason=request.reason))


def build_agent(model: BaseLlm) -> BookingAgent:
    reply = LlmAgent(
        name="reply",
        model=model,
        include_contents="none",  # the session is the trace, never re-sent: the Trip is the state
        instruction=reply_instruction,
        tools=[StateOperations(Trip.approve, Trip.reject, Trip.change, Trip.request_clarification)],
    )
    return BookingAgent(name="booking_agent", reply=reply, sub_agents=[reply])
