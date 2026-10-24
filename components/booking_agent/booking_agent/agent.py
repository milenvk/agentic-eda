"""The Booking Agent: an ADK custom agent over the Trip.

Every activation is one of the Trip's operations. The agent dispatches on the inbound
event's class: a request, planning's proposal, and the trip's own events are one operation
call each, with no LLM; the customer's reply, written in the customer's words, runs an LLM
whose tools are the Trip's four reply operations. The LLM proposes an operation by calling
its tool, the operation accepts or refuses, and a refusal returns to the LLM as the tool's
result. Nothing here knows about the broker or the store: what the agent consumes and
produces is declared where it is hosted, in `app.py`, and the Trip under activation comes
from the activator.
"""

import logging
from collections.abc import AsyncGenerator, Callable
from datetime import date

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.events import Event
from google.adk.models import BaseLlm
from google.adk.tools import ToolContext

from agentic_eda import eda
from agentic_eda.contracts import EventContract
from travel_agency.events.booking import CustomerReplied, TripRequested
from travel_agency.events.planning import Itinerary, ItineraryProposed, Money

from .prompts import render
from .trip import Refused, Trip

log = logging.getLogger("BookingAgent")

# --- the reply's tools, each landing in one of the Trip's operations


def _decide(tool_context: ToolContext, operation: Callable[[Trip], EventContract]) -> str:
    """Run one reply operation on the Trip under activation.

    An accepted operation is the activation's answer and ends the LLM's turn: there is nothing
    to say after it. A refusal returns to the LLM as the tool's result, and it chooses again.
    """
    activation = eda.activation()
    try:
        event = operation(activation.state)
    except (Refused, ValueError, TypeError) as refusal:
        log.info("the LLM's tool call was refused: %s", refusal)
        return f"refused: {refusal}"
    activation.answer(event)
    tool_context.actions.skip_summarization = True  # the decision is made; no more LLM calls
    log.info("the LLM decided: %s", type(event).__name__)
    return "done"


async def approve(proposal_id: str, rank: int, tool_context: ToolContext) -> str:
    """Approve one itinerary of the proposal, by its rank: 1 is the first one listed."""
    return _decide(tool_context, lambda trip: trip.approve(proposal_id, int(rank)))


async def reject(proposal_id: str, reason: str, tool_context: ToolContext) -> str:
    """Reject every itinerary of the proposal, with the customer's reason in their words."""
    return _decide(tool_context, lambda trip: trip.reject(proposal_id, reason))


async def change(
    reason: str,
    tool_context: ToolContext,
    departure_dates: list[str] | None = None,
    budget: float | None = None,
) -> str:
    """Change the trip: new departure dates (one per journey, in travel order, as YYYY-MM-DD),
    a new budget in the trip's currency, or both, with the customer's reason."""
    return _decide(
        tool_context,
        lambda trip: trip.change(
            reason,
            departure_dates=[date.fromisoformat(day) for day in departure_dates]
            if departure_dates
            else None,
            budget=Money(amount=budget, currency=trip.requirements.budget.currency)
            if budget is not None and trip.requirements.budget
            else None,
        ),
    )


async def request_clarification(
    proposal_id: str, question: str, tool_context: ToolContext, options: list[str] | None = None
) -> str:
    """Ask the customer one question when their words settle neither approval, rejection,
    nor a change; options, when a few answers would settle it."""
    return _decide(
        tool_context, lambda trip: trip.request_clarification(proposal_id, question, options)
    )


async def reply_instruction(context: ReadonlyContext) -> str:
    """The prompt for reading one reply: the trip and the proposal it is about."""
    activation = eda.activation()
    trip: Trip = activation.state
    reply: CustomerReplied = activation.request
    proposal = next((p for p in trip.proposals if p.proposal_id == reply.proposal_id), None)
    pending = trip.pending_question
    return render(
        "reply",
        requirements=trip.requirements.model_dump_json(),
        proposal_id=reply.proposal_id,
        itineraries="\n".join(_line(i) for i in proposal.itineraries) if proposal else "none",
        pending=f"You already asked: {pending.question} Read the reply as its answer." if pending else "",  # fmt: skip
        today=date.today().isoformat(),
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
        else:  # the trip's own TripCreated, ItineraryRejected, or TripChanged
            activation.answer(trip.request_planning())


def build_agent(model: BaseLlm) -> BookingAgent:
    reply = LlmAgent(
        name="reply",
        model=model,
        include_contents="none",  # the session is the trace, never re-sent: the Trip is the state
        instruction=reply_instruction,
        tools=[approve, reject, change, request_clarification],
    )
    return BookingAgent(name="booking_agent", reply=reply, sub_agents=[reply])
