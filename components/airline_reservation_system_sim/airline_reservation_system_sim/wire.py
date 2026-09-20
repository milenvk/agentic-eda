"""The airline's messages: a printable subset of the Amadeus self-service shape."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class Wire(BaseModel):
    """Field names are camelCase on the wire, as the supplier's are."""

    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True)


class Reply[T](Wire):
    """Every body, in either direction, is wrapped in `data`."""

    data: T


class Location(Wire):
    sub_type: Literal["CITY"] = "CITY"
    name: str
    iata_code: str  # the city code, covering every airport of the city


class Endpoint(Wire):
    iata_code: str  # an airport
    at: datetime


class Segment(Wire):
    """One flight, from takeoff to landing."""

    departure: Endpoint
    arrival: Endpoint
    carrier_code: str
    number: str


class Itinerary(Wire):
    segments: list[Segment]  # two of them say the journey has a stop


class Price(Wire):
    currency: str
    total: float  # for every traveller together


class FareRule(Wire):
    category: Literal["EXCHANGE", "REFUND"]
    max_penalty_amount: float | None = None
    not_applicable: bool = False  # True says the fare does not allow it at all


class FlightOffer(Wire):
    type: Literal["flight-offer"] = "flight-offer"
    id: str
    itineraries: list[Itinerary]  # always one: every search is one way
    price: Price
    branded_fare: str
    fare_rules: list[FareRule]
    expires_at: datetime


class Pricing(Wire):
    type: Literal["flight-offers-pricing"] = "flight-offers-pricing"
    flight_offers: list[FlightOffer]


class Name(Wire):
    first_name: str
    last_name: str


class Traveler(Wire):
    id: str
    name: Name


class TicketingAgreement(Wire):
    option: Literal["DELAY_TO_CANCEL"] = "DELAY_TO_CANCEL"
    date_time: datetime  # the hold lapses then, and the order with it


class FlightOrder(Wire):
    type: Literal["flight-order"] = "flight-order"
    id: str | None = None  # the airline's, so a request has none
    flight_offers: list[FlightOffer]
    travelers: list[Traveler]
    ticketing_agreement: TicketingAgreement | None = None
