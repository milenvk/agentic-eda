"""Two example events for the framework's own tests, so the suite needs no application.

They are a small copy of the book's running example: a request, and the proposal answering it.
"""

from pydantic import Field

from agentic_eda.events import EventModel, event

ITINERARY_REQUESTED = "planning.ItineraryRequested"
ITINERARY_PROPOSED = "planning.ItineraryProposed"


@event(ITINERARY_REQUESTED, order_per="trip_id")
class ItineraryRequested(EventModel):
    trip_id: str
    origin: str
    travellers: int = Field(ge=1)


@event(ITINERARY_PROPOSED, order_per="trip_id")
class ItineraryProposed(EventModel):
    trip_id: str
    itineraries: list[str] = Field(min_length=1, max_length=3)


REQUEST = {"trip_id": "trip-1", "origin": "New York", "travellers": 2}
PROPOSAL = {"trip_id": "trip-1", "itineraries": ["by way of Madrid", "nonstop"]}
