"""The Booking Agent: an ADK custom agent over the Trip.

Every activation is one of the Trip's operations. The agent dispatches on the inbound
event's class: a request, planning's proposal, and the trip's own events are one operation
call each, with no LLM; the customer's reply, written in the customer's words, runs an LLM
whose tools are the Trip's four reply operations themselves, bound by the library's
`StateOperations`. The LLM proposes an operation by calling its tool, the operation accepts
or refuses, and a refusal returns to the LLM as the tool's result. A refusal on a code path
is the activation's answer, `Nothing` with the reason: a proposal answering a request the
Trip no longer has outstanding is acknowledged and changes nothing. Nothing here knows about
the broker or the store: what the agent consumes and produces is declared where it is
hosted, in `app.py`, and the Trip under activation comes from the activator.
"""

from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.events import Event
from google.adk.models import BaseLlm

from agentic_eda import eda
from agentic_eda.adk import StateOperations
from travel_agency.events.booking import CustomerReplied, TripCreated, TripRequested
from travel_agency.events.planning import ItineraryProposed

from .prompts import reply_prompt
from .trip import Trip


async def reply_instruction(context: ReadonlyContext) -> str:
    """The prompt for reading one reply: the trip under activation and the reply to it."""
    activation = eda.activation()
    return reply_prompt(activation.state, activation.request)


class BookingAgent(BaseAgent):
    """Dispatches on the event's class: code for the bookkeeping, the LLM for the reply."""

    reply: LlmAgent

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        activation = eda.activation()
        request, trip = activation.request, activation.state
        if isinstance(request, CustomerReplied):
            async for event in self.reply.run_async(ctx):
                yield event
            return
        try:
            if isinstance(request, TripRequested):
                activation.answer(trip.open(request))
            elif isinstance(request, ItineraryProposed):
                activation.answer(trip.record_proposal(request))
            elif isinstance(request, TripCreated):
                activation.answer(trip.request_planning())
            else:  # the trip's own ItineraryRejected or TripChanged: planning hears why
                activation.answer(trip.request_planning(reason=request.reason))
        except eda.Refused as refusal:
            # Only this agent changes the Trip, one event at a time, so what it refuses now
            # it would refuse again: saying so is the answer, and the event is done.
            activation.answer(eda.Nothing(reason=str(refusal)))


def build_agent(model: BaseLlm) -> BookingAgent:
    reply = LlmAgent(
        name="reply",
        model=model,
        include_contents="none",  # the session is the trace, never re-sent: the Trip is the state
        instruction=reply_instruction,
        tools=[StateOperations(Trip.approve, Trip.reject, Trip.change, Trip.request_clarification)],
    )
    return BookingAgent(name="booking_agent", reply=reply, sub_agents=[reply])
