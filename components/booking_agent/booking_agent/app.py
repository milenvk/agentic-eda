"""The app that hosts the Booking Agent: ADK's own, with the activator attached to it."""

import os
from pathlib import Path

from google.adk.cli.fast_api import get_fast_api_app
from google.adk.models.lite_llm import LiteLlm

from agentic_eda import console, eda
from travel_agency.events.booking import (
    ClarificationRequested,
    CustomerReplied,
    ItineraryApproved,
    ItineraryRejected,
    ProposalReady,
    TripChanged,
    TripCreated,
    TripRequested,
    TripRequestRejected,
)
from travel_agency.events.planning import ItineraryProposed, ItineraryRequested

from .agent import build_agent
from .trip import Trip

console.configure_logging()

agent = build_agent(LiteLlm(model=os.environ["LLM_MODEL"], temperature=0))

# ADK's own app, as its documentation serves an agent; the activator runs in its lifespan.
app = get_fast_api_app(agents_dir=str(Path(__file__).parent), web=False)

# Everything event-driven about this component: what the agent consumes, what it produces,
# the state it owns, and the activator attached to the app that hosts it.
eda.attach(
    app,
    agent,
    consumes=eda.consumes(
        TripRequested, TripCreated, ItineraryProposed, CustomerReplied, ItineraryRejected, TripChanged
    ),
    produces=eda.produces(
        TripCreated,
        TripRequestRejected,
        ItineraryRequested,
        ProposalReady,
        ItineraryApproved,
        ItineraryRejected,
        TripChanged,
        ClarificationRequested,
    ),
    state=eda.state(Trip, key="trip_id"),
)
