"""Unit tests for the Planner's supplier clients, against stand-ins answering as each supplier does.

The suppliers' own suites test the simulators. Here the subject is the translation: a
question in the supplier's terms, and its answer in the Planner's.
"""

import asyncio
from datetime import date

import httpx
import pytest
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from itinerary_planner import suppliers_clients
from itinerary_planner.suppliers_clients import AirlineClient, HotelsClient
from travel_agency.events.planning import Child, OriginDestination, Stay

TO_LISBON = OriginDestination(
    origin="NYC",
    destination="LIS",
    departure_date=date(2026, 10, 1),
    days_before=0,
    days_after=0,
)
IN_LISBON = Stay(city="LIS", check_in=date(2026, 10, 1), check_out=date(2026, 10, 4), rooms=1)

ONE_STOP_OFFER = {
    "type": "flight-offer",
    "id": "WW393+WW233-20261001-BASIC-2ADT0CHD0INF",
    "itineraries": [
        {
            "segments": [
                {
                    "departure": {"iataCode": "EWR", "at": "2026-10-01T11:00:00Z"},
                    "arrival": {"iataCode": "LHR", "at": "2026-10-01T18:27:00Z"},
                    "carrierCode": "WW",
                    "number": "393",
                },
                {
                    "departure": {"iataCode": "LHR", "at": "2026-10-01T19:57:00Z"},
                    "arrival": {"iataCode": "LIS", "at": "2026-10-01T22:27:00Z"},
                    "carrierCode": "WW",
                    "number": "233",
                },
            ]
        }
    ],
    "price": {"currency": "USD", "total": 814.87},
    "brandedFare": "BASIC",
    "fareRules": [
        {"category": "EXCHANGE", "maxPenaltyAmount": 150.0, "notApplicable": False},
        {"category": "REFUND", "maxPenaltyAmount": None, "notApplicable": True},
    ],
    "expiresAt": "2026-09-20T22:30:00Z",
}


def airline_answering(asked: list[httpx.Request]) -> AirlineClient:
    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        if request.url.params["destinationLocationCode"] == "XXX":
            return httpx.Response(400, json={"detail": "XXX is no city code"})
        return httpx.Response(200, json={"data": [ONE_STOP_OFFER]})

    client = AirlineClient("http://airline")
    stand_in = httpx.MockTransport(answer)
    client._http = httpx.AsyncClient(transport=stand_in, base_url="http://airline")
    return client


async def test_the_airline_is_asked_in_its_own_terms():
    asked = []
    family = [
        Child(age=1, own_seat=False),  # the airline's infant
        Child(age=1, own_seat=True),  # seated, so the airline's child
        Child(age=7, own_seat=True),
        Child(age=15, own_seat=True),  # the airline's adult, from 12 on
    ]
    await airline_answering(asked).search(TO_LISBON, 2, family, max_stops=0)

    assert dict(asked[-1].url.params) == {
        "originLocationCode": "NYC",  # the city's code, covering JFK and Newark
        "destinationLocationCode": "LIS",
        "departureDate": "2026-10-01",
        "adults": "3",
        "children": "2",
        "infants": "1",
        "nonStop": "true",
    }


async def test_a_flight_offer_is_answered_in_the_planners_terms():
    (offer,) = await airline_answering([]).search(TO_LISBON, 2, [], max_stops=1)

    first, onward = offer.segments
    assert (first.carrier, first.number, onward.number) == ("WW", "393", "233")
    assert (first.origin, first.destination, onward.destination) == ("EWR", "LHR", "LIS")
    assert offer.stops == 1
    assert offer.departs.isoformat() == "2026-10-01T11:00:00+00:00"  # the first takeoff
    assert offer.arrives.isoformat() == "2026-10-01T22:27:00+00:00"  # the last landing
    assert offer.fare_conditions == "exchange for 150, no refund"
    assert (offer.price.amount, offer.price.currency) == (814.87, "USD")
    assert offer.offer_id == ONE_STOP_OFFER["id"]  # the supplier's offer, as made


async def test_the_airlines_refusal_is_an_error_carrying_its_reason():
    nowhere = TO_LISBON.model_copy(update={"destination": "XXX"})
    with pytest.raises(LookupError, match="XXX is no city code"):
        await airline_answering([]).search(nowhere, 2, [], max_stops=1)


def hotels_answering() -> HotelsClient:
    supplier = MCPServer("a stand-in for the hotels")

    @supplier.tool()
    def search_availability(
        city: str, check_in: date, check_out: date, rooms: int, adults: int, child_ages: list[int]
    ) -> dict[str, list[dict]]:
        if city == "XXX":
            raise ToolError("no single city is called XXX")
        guests = adults + len(child_ages)
        offer = {
            "offer_id": f"LIS1-20261001-3N-FLEXIBLE-{rooms}R{guests}G",
            "hotel": "Pátio das Andorinhas",
            "area": "Alfama, quiet hillside lanes",
            "stars": 3,
            "check_in": check_in.isoformat(),
            "check_out": check_out.isoformat(),
            "rooms_left": 1,
            "room": "family" if guests > 2 else "double",
            "rate_plan": "FLEXIBLE",
            "cancellation": "free cancellation until 48 hours before arrival",
            "total": 397.36 * rooms,
            "currency": "USD",
            "expires_at": "2026-09-20T22:30:00Z",
        }
        return {"offers": [offer]}

    return HotelsClient(supplier)  # an MCP client connects to a server object as to a URL


async def test_a_room_offer_is_answered_in_the_planners_terms():
    (offer,) = await hotels_answering().availability(IN_LISBON, 2, [Child(age=7, own_seat=True)])

    assert (offer.city, offer.hotel, offer.rooms_left) == ("LIS", "Pátio das Andorinhas", 1)
    assert (offer.room, offer.rate_plan) == ("family", "FLEXIBLE")
    assert offer.offer_id.endswith("1R3G")  # the rooms and the guests, as they were asked for
    assert (offer.check_in, offer.check_out) == (date(2026, 10, 1), date(2026, 10, 4))
    assert (offer.total.amount, offer.total.currency) == (397.36, "USD")
    assert offer.supplier == "Hotel Reservation System"


async def test_the_hotels_refusal_is_an_error_carrying_their_reason():
    nowhere = IN_LISBON.model_copy(update={"city": "XXX"})
    with pytest.raises(LookupError, match="XXX"):
        await hotels_answering().availability(nowhere, 2, [])


def test_each_client_is_chosen_by_its_setting(monkeypatch):
    monkeypatch.setenv("AIRLINE_URL", "http://airline:8000")
    monkeypatch.setenv("HOTEL_INVENTORY_URL", "http://hotels:8000/mcp")

    assert isinstance(suppliers_clients.airline(), AirlineClient)
    assert isinstance(suppliers_clients.hotels(), HotelsClient)


@pytest.mark.parametrize("setting", ["AIRLINE_URL", "HOTEL_INVENTORY_URL"])
def test_a_supplier_that_is_not_configured_says_which_setting_is_missing(setting, monkeypatch):
    monkeypatch.delenv(setting, raising=False)
    client = suppliers_clients.airline() if setting == "AIRLINE_URL" else suppliers_clients.hotels()
    with pytest.raises(RuntimeError, match=setting):
        asyncio.run(
            client.search(TO_LISBON, 1, [], 0)
            if setting == "AIRLINE_URL"
            else client.availability(IN_LISBON, 1, [])
        )
