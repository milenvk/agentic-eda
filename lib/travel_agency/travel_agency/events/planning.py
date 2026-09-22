"""The planning context's events: a request for itineraries, and the proposal answering it."""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from ..event_types import ITINERARY_PROPOSED, ITINERARY_REQUESTED
from . import EventModel, event


class Money(BaseModel):
    amount: float
    currency: str


class Stop(BaseModel):
    """One place the trip stays, in travel order."""

    city: str
    arrive: date
    depart: date


@event(ITINERARY_REQUESTED, order_per="trip_id")
class ItineraryRequested(EventModel):
    """Someone asks planning for itineraries. Whoever asks writes it."""

    trip_id: str
    origin: str
    stops: list[Stop] = Field(min_length=1)
    travellers: int = Field(ge=1)
    budget: Money | None  # None says the customer set no limit
    preferences: str  # in the customer's own words
    car_class: str | None  # None says no car is wanted


class Offer(BaseModel):
    """What a supplier quoted for an item, and until when the quote holds."""

    supplier: str
    offer_id: str
    price: Money
    valid_until: datetime


class FlightItem(BaseModel):
    kind: Literal["flight"]
    origin: str
    destination: str
    departs: datetime
    arrives: datetime
    fare_conditions: str
    offer: Offer | None


class StayItem(BaseModel):
    kind: Literal["stay"]
    city: str
    hotel: str
    check_in: date
    check_out: date
    cancellation: str
    offer: Offer | None


class Itinerary(BaseModel):
    """One ranked way to make the trip, its items in travel order."""

    rank: int = Field(ge=1)
    label: str  # what it optimises: cheapest, fastest, best value
    rationale: str
    items: list[Annotated[FlightItem | StayItem, Field(discriminator="kind")]] = Field(
        min_length=1
    )
    total: Money


@event(ITINERARY_PROPOSED, order_per="trip_id")
class ItineraryProposed(EventModel):
    """Planning's answer to one request: two or three ranked itineraries."""

    trip_id: str
    itineraries: list[Itinerary] = Field(min_length=1, max_length=3)
