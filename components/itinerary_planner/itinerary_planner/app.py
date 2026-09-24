"""The app that hosts the Itinerary Planner Agent, with the activator attached to it."""

from fastapi import FastAPI

from agentic_eda import console, eda
from travel_agency.events.planning import ItineraryProposed, ItineraryRequested

from .agent import agent

console.configure_logging()

app = FastAPI(title="Itinerary Planner Agent")

# Everything event-driven about this component: what the agent consumes, what it
# produces, and the activator attached to the app that hosts it.
eda.attach(
    app,
    agent,
    consumes=eda.consumes(ItineraryRequested),
    produces=eda.produces(ItineraryProposed),
)
