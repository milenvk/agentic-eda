"""The Airline Reservation System simulator: a REST flight supplier on the Amadeus shape.

A caller finds a city's code, searches offers, confirms an offer's price, holds seats with
an order, retrieves the order, and cancels it. The airline honours only the offers it made,
at the price it quoted, until they expire. An order is a hold: it lapses unless ticketed.
"""

import asyncio
import os
from datetime import UTC, date, datetime, timedelta
from itertools import count
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query

from travel_agency.sims import world
from travel_agency.sims.world import City

from . import flights
from .wire import FlightOffer, FlightOrder, Location, Pricing, Reply, TicketingAgreement

HOLD_MINUTES = int(os.environ.get("HOLD_MINUTES", "15"))
# Every answer waits this long, which is how a slow supplier is staged.
RESPONSE_DELAY_SECONDS = float(os.environ.get("RESPONSE_DELAY_SECONDS", "0"))

app = FastAPI(title="Airline Reservation System (simulator)")

offers: dict[str, FlightOffer] = {}
orders: dict[str, FlightOrder] = {}
order_numbers = count(1)


@app.middleware("http")
async def slow_vendor(request, call_next):
    await asyncio.sleep(RESPONSE_DELAY_SECONDS)
    return await call_next(request)


@app.get("/v1/reference-data/locations")
def find_locations(keyword: str) -> Reply[list[Location]]:
    cities = world.find_cities(keyword)
    return Reply(data=[Location(name=city.name, iata_code=city.code) for city in cities])


@app.get("/v2/shopping/flight-offers")
def search_flight_offers(
    origin: Annotated[str, Query(alias="originLocationCode")],
    destination: Annotated[str, Query(alias="destinationLocationCode")],
    on: Annotated[date, Query(alias="departureDate")],
    adults: Annotated[int, Query(ge=1, le=9)] = 1,
    non_stop: Annotated[bool, Query(alias="nonStop")] = False,
) -> Reply[list[FlightOffer]]:
    found = flights.search(_city(origin), _city(destination), on, adults, non_stop)
    offers.update({offer.id: offer for offer in found})
    return Reply(data=found)


@app.post("/v1/shopping/flight-offers/pricing")
def confirm_price(body: Reply[Pricing]) -> Reply[Pricing]:
    confirmed = [_still_offered(offer.id) for offer in body.data.flight_offers]
    return Reply(data=Pricing(flight_offers=confirmed))


@app.post("/v1/booking/flight-orders", status_code=201)
def create_order(body: Reply[FlightOrder]) -> Reply[FlightOrder]:
    order = FlightOrder(
        id=f"{flights.CARRIER}{next(order_numbers):06d}",
        flight_offers=[_still_offered(offer.id) for offer in body.data.flight_offers],
        travelers=body.data.travelers,
        ticketing_agreement=TicketingAgreement(
            date_time=datetime.now(UTC) + timedelta(minutes=HOLD_MINUTES)
        ),
    )
    orders[order.id] = order
    return Reply(data=order)


@app.get("/v1/booking/flight-orders/{order_id}")
def retrieve_order(order_id: str) -> Reply[FlightOrder]:
    return Reply(data=_held(order_id))


@app.delete("/v1/booking/flight-orders/{order_id}", status_code=204)
def cancel_order(order_id: str) -> None:
    del orders[_held(order_id).id]


def _city(code: str) -> City:
    city = world.CITIES.get(code.upper())
    if city is None:
        raise HTTPException(400, f"{code} is no city code; see /v1/reference-data/locations")
    return city


def _still_offered(offer_id: str) -> FlightOffer:
    """The offer as the airline made it, whatever the caller sent back."""
    offer = offers.get(offer_id)
    if offer is None:
        raise HTTPException(400, f"the airline never made the offer {offer_id}")
    if offer.expires_at <= datetime.now(UTC):
        raise HTTPException(400, f"the offer {offer_id} has expired; search again")
    return offer


def _held(order_id: str) -> FlightOrder:
    order = orders.get(order_id)
    if order is None or order.ticketing_agreement.date_time <= datetime.now(UTC):
        orders.pop(order_id, None)  # a lapsed hold is gone, as if it had been cancelled
        raise HTTPException(404, f"no order {order_id} is held")
    return order
