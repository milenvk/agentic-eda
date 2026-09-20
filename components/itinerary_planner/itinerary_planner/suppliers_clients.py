"""The Planner's clients for its two suppliers, each reached over the supplier's own protocol.

A client translates: it asks in the supplier's terms and answers in the Planner's, so the
graph never sees a supplier's field names.
"""

import os
from datetime import date

import httpx
from mcp import Client as McpClient

from travel_agency.events.planning import Money

from .suppliers import Airline, FlightOffer, HotelOffer, Hotels

AIRLINE = "Airline Reservation System"
HOTELS = "Hotel Reservation System"


class AirlineClient:
    """The airline's REST API, on the Amadeus self-service shape."""

    def __init__(self, url: str) -> None:
        self._http = httpx.AsyncClient(base_url=url, timeout=30)

    async def search(
        self, origin: str, destination: str, on: date, travellers: int, max_stops: int
    ) -> list[FlightOffer]:
        found = await self._get(
            "/v2/shopping/flight-offers",
            originLocationCode=await self._city_code(origin),
            destinationLocationCode=await self._city_code(destination),
            departureDate=on.isoformat(),
            adults=travellers,
            nonStop=max_stops == 0,
        )
        return [_flight_offer(offer) for offer in found]

    async def _city_code(self, city: str) -> str:
        """The airline sells by city code, which covers every airport of the city."""
        locations = await self._get("/v1/reference-data/locations", keyword=city)
        if len(locations) != 1:
            raise LookupError(f"the airline knows no single city called {city}")
        return locations[0]["iataCode"]

    async def _get(self, path: str, **params) -> list[dict]:
        response = await self._http.get(path, params=params)
        response.raise_for_status()
        return response.json()["data"]


class HotelsClient:
    """The hotels' inventory, a tool on the supplier's MCP server."""

    def __init__(self, url: str) -> None:
        self._url = url

    async def availability(
        self, city: str, check_in: date, check_out: date, travellers: int
    ) -> list[HotelOffer]:
        question = {
            "city": city,
            "check_in": check_in.isoformat(),
            "check_out": check_out.isoformat(),
            "guests": travellers,
        }
        async with McpClient(self._url) as client:
            result = await client.call_tool("search_availability", question)
        if result.is_error:
            raise LookupError(result.content[0].text)
        return [_hotel_offer(city, offer) for offer in result.structured_content["offers"]]


def _flight_offer(offer: dict) -> FlightOffer:
    segments = offer["itineraries"][0]["segments"]
    return FlightOffer(
        offer_id=offer["id"],
        supplier=AIRLINE,
        origin=segments[0]["departure"]["iataCode"],
        destination=segments[-1]["arrival"]["iataCode"],
        departs=segments[0]["departure"]["at"],
        arrives=segments[-1]["arrival"]["at"],
        stops=len(segments) - 1,
        fare_conditions=", ".join(_in_words(rule) for rule in offer["fareRules"]),
        price=Money(amount=offer["price"]["total"], currency=offer["price"]["currency"]),
        valid_until=offer["expiresAt"],
    )


def _in_words(rule: dict) -> str:
    """A fare rule as a customer would read it: `exchange for 150`, `no refund`."""
    action = rule["category"].lower()
    if rule["notApplicable"]:
        return f"no {action}"
    penalty = rule["maxPenaltyAmount"]
    return f"{action} for {penalty:,.0f}" if penalty else f"free {action}"


def _hotel_offer(city: str, offer: dict) -> HotelOffer:
    return HotelOffer(
        offer_id=offer["offer_id"],
        supplier=HOTELS,
        city=city,
        hotel=offer["hotel"],
        area=offer["area"],
        check_in=offer["check_in"],
        check_out=offer["check_out"],
        rooms_left=offer["rooms_left"],
        cancellation=offer["cancellation"],
        total=Money(amount=offer["total"], currency=offer["currency"]),
        valid_until=offer["expires_at"],
    )


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
    url = os.environ.get("AIRLINE_URL")
    return AirlineClient(url) if url else _NotConnected("AIRLINE_URL")


def hotels() -> Hotels:
    """The Hotel Reservation System's inventory, an MCP server at `HOTEL_INVENTORY_URL`."""
    url = os.environ.get("HOTEL_INVENTORY_URL")
    return HotelsClient(url) if url else _NotConnected("HOTEL_INVENTORY_URL")
