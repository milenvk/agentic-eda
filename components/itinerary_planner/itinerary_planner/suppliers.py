"""What the Planner asks of its suppliers, and the offers they answer with."""

from datetime import date, datetime
from typing import Protocol

from pydantic import BaseModel

from travel_agency.events.planning import Money


class FlightOffer(BaseModel):
    offer_id: str
    supplier: str
    origin: str
    destination: str
    departs: datetime
    arrives: datetime
    stops: int
    fare_conditions: str
    price: Money
    valid_until: datetime


class HotelOffer(BaseModel):
    offer_id: str
    supplier: str
    city: str
    hotel: str
    area: str
    check_in: date
    check_out: date
    rooms_left: int
    cancellation: str
    total: Money
    valid_until: datetime


class Airline(Protocol):
    async def search(
        self, origin: str, destination: str, on: date, travellers: int, max_stops: int
    ) -> list[FlightOffer]: ...


class Hotels(Protocol):
    async def availability(
        self, city: str, check_in: date, check_out: date, travellers: int
    ) -> list[HotelOffer]: ...
