"""Two example events for the library's own tests, so the suite needs no application.

They are a small copy of the book's running example: a request, and the proposal answering it.
"""

from pydantic import Field

from agentic_eda.contracts import EventContract, event

ITINERARY_REQUESTED = "planning.ItineraryRequested"
ITINERARY_PROPOSED = "planning.ItineraryProposed"


@event(ITINERARY_REQUESTED, order_per="trip_id")
class ItineraryRequested(EventContract):
    trip_id: str
    origin: str
    adults: int = Field(ge=1)


@event(ITINERARY_PROPOSED, order_per="trip_id")
class ItineraryProposed(EventContract):
    trip_id: str
    itineraries: list[str] = Field(min_length=1, max_length=3)


REQUEST = {"trip_id": "trip-1", "origin": "NYC", "adults": 2}
PROPOSAL = {"trip_id": "trip-1", "itineraries": ["by way of Madrid", "nonstop"]}
