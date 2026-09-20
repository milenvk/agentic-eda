"""The Itinerary Planner Agent: a LangGraph graph, and what it consumes and produces."""

from travel_agency import eda
from travel_agency.events.planning import ItineraryProposed, ItineraryRequested
from travel_agency.hydration import hydration

from .graph import build_graph
from .prompts import ask
from .suppliers_clients import airline, hotels

agent = build_graph(ask=ask, airline=airline(), hotels=hotels(), hydration=hydration())

consumes = eda.consumes(ItineraryRequested)
produces = eda.produces(ItineraryProposed)
