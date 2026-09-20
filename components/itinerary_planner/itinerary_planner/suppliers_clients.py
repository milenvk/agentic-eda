"""The Planner's clients for its two suppliers, each reached over the supplier's own protocol."""

import os
from datetime import date

from .suppliers import Airline, FlightOffer, HotelOffer, Hotels


class _NotConnected:
    """Stands where a client will be until its supplier's address is configured."""

    def __init__(self, setting: str) -> None:
        self._setting = setting

    def _refuse(self):
        raise RuntimeError(f"{self._setting} is not set, so this supplier cannot be reached")

    async def search(
        self, origin: str, destination: str, on: date, travellers: int, max_stops: int
    ) -> list[FlightOffer]:
        self._refuse()

    async def availability(
        self, city: str, check_in: date, check_out: date, travellers: int
    ) -> list[HotelOffer]:
        self._refuse()


def airline() -> Airline:
    """The Airline Reservation System, at `AIRLINE_URL`."""
    if not os.environ.get("AIRLINE_URL"):
        return _NotConnected("AIRLINE_URL")
    raise NotImplementedError


def hotels() -> Hotels:
    """The Hotel Reservation System's inventory, at `HOTEL_INVENTORY_URL`."""
    if not os.environ.get("HOTEL_INVENTORY_URL"):
        return _NotConnected("HOTEL_INVENTORY_URL")
    raise NotImplementedError
