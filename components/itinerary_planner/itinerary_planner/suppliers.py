"""What the Planner asks of its suppliers, and the offers they answer with."""

from datetime import date, datetime
from typing import Protocol

from pydantic import BaseModel

from travel_agency.events.planning import Child, FlightSegment, Money, OriginDestination, Stay


class FlightOffer(BaseModel):
    offer_id: str
    supplier: str
    segments: list[FlightSegment]  # in travel order
    stops: int
    fare_conditions: str
    price: Money
    valid_until: datetime

    @property
    def departs(self) -> datetime:
        return self.segments[0].departs

    @property
    def arrives(self) -> datetime:
        return self.segments[-1].arrives


class HotelOffer(BaseModel):
    offer_id: str
    supplier: str
    city: str
    hotel: str
    area: str
    room: str
    check_in: date
    check_out: date
    rooms_left: int
    rate_plan: str
    cancellation: str
    total: Money
    valid_until: datetime


class Airline(Protocol):
    async def search(
        self, journey: OriginDestination, adults: int, children: list[Child], max_stops: int
    ) -> list[FlightOffer]: ...


class Hotels(Protocol):
    async def availability(
        self, stay: Stay, adults: int, children: list[Child]
    ) -> list[HotelOffer]: ...
