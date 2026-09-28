"""Unit tests for the airline simulator, called over HTTP as a customer of it would."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from airline_reservation_system_sim import app as airline

LISBON_TRIP = {
    "originLocationCode": "NYC",
    "destinationLocationCode": "LIS",
    "departureDate": "2026-10-01",
    "adults": 2,
}
TORONTO_TO_MARRAKECH = {"originLocationCode": "YTO", "destinationLocationCode": "RAK"}
TRAVELERS = [{"id": "1", "name": {"firstName": "Ada", "lastName": "Lovelace"}}]


@pytest.fixture
def client() -> TestClient:
    airline.offers.clear()
    airline.orders.clear()
    return TestClient(airline.app)


def search(client: TestClient, **changes) -> list[dict]:
    response = client.get("/v2/shopping/flight-offers", params={**LISBON_TRIP, **changes})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def order_for(offer: dict) -> dict:
    return {"data": {"type": "flight-order", "flightOffers": [offer], "travelers": TRAVELERS}}


def segments(offer: dict) -> list[dict]:
    return offer["itineraries"][0]["segments"]


def test_a_city_is_found_by_name_with_the_code_covering_its_airports(client):
    found = client.get("/v1/reference-data/locations", params={"keyword": "new york"}).json()
    assert found["data"] == [{"subType": "CITY", "name": "New York", "iataCode": "NYC"}]


def test_the_same_search_finds_the_same_offers_at_the_same_prices(client):
    def facts(offers):
        return [(o["id"], o["price"]["total"], segments(o)) for o in offers]

    assert facts(search(client)) == facts(search(client))
    assert facts(search(client)) != facts(search(client, departureDate="2026-10-02"))


def test_a_stop_is_the_cheaper_and_slower_way_to_fly(client):
    offers = search(client)
    nonstop = [o for o in offers if len(segments(o)) == 1 and o["brandedFare"] == "BASIC"]
    one_stop = [o for o in offers if len(segments(o)) == 2 and o["brandedFare"] == "BASIC"]

    assert nonstop and one_stop
    assert max(o["price"]["total"] for o in one_stop) < min(o["price"]["total"] for o in nonstop)
    assert {segments(o)[0]["departure"]["iataCode"] for o in offers} <= {"JFK", "EWR"}
    assert all(len(segments(o)) == 1 for o in search(client, nonStop=True))


def test_a_connection_is_made_at_one_airport_with_time_to_change_planes(client):
    # Neither city is a hub and an ocean lies between them, so every journey has a stop.
    offers = search(client, **TORONTO_TO_MARRAKECH)
    assert offers
    assert search(client, **TORONTO_TO_MARRAKECH, nonStop=True) == []
    for offer in offers:
        first, onward = segments(offer)
        assert first["arrival"]["iataCode"] == onward["departure"]["iataCode"]
        landed = datetime.fromisoformat(first["arrival"]["at"])
        assert datetime.fromisoformat(onward["departure"]["at"]) - landed >= timedelta(minutes=90)


def test_a_fare_says_what_a_change_and_a_refund_are_charged(client):
    basic = next(o for o in search(client) if o["brandedFare"] == "BASIC")
    flex = next(o for o in search(client) if o["brandedFare"] == "FLEX")

    assert basic["fareRules"][1] == {
        "category": "REFUND",
        "maxPenaltyAmount": None,
        "notApplicable": True,
    }
    assert flex["price"]["total"] > basic["price"]["total"]
    assert flex["price"]["currency"] == "USD"


def test_a_child_flies_for_less_and_a_held_infant_for_a_tenth(client):
    def cheapest(**party) -> float:
        return min(o["price"]["total"] for o in search(client, **party))

    couple = cheapest(adults=2)
    adult_fare = couple / 2

    assert cheapest(adults=2, children=1) == pytest.approx(couple + 0.75 * adult_fare, abs=0.02)
    assert cheapest(adults=2, infants=1) == pytest.approx(couple + 0.1 * adult_fare, abs=0.02)
    assert search(client, adults=2, children=1, infants=1)[0]["id"].endswith("2ADT1CHD1INF")


def test_an_adult_holds_one_infant_at_most(client):
    asked = {**LISBON_TRIP, "adults": 1, "infants": 2}
    response = client.get("/v2/shopping/flight-offers", params=asked)
    assert response.status_code == 400
    assert "infant" in response.json()["detail"]


def test_an_airport_code_keeps_the_journey_to_that_airport(client):
    from_newark = search(client, originLocationCode="EWR")
    assert from_newark
    assert {segments(o)[0]["departure"]["iataCode"] for o in from_newark} == {"EWR"}


def test_an_unknown_city_code_is_refused_with_where_to_find_one(client):
    response = client.get(
        "/v2/shopping/flight-offers", params={**LISBON_TRIP, "destinationLocationCode": "XXX"}
    )
    assert response.status_code == 400
    assert "/v1/reference-data/locations" in response.json()["detail"]


def test_a_price_is_confirmed_for_an_offer_the_airline_made(client):
    offer = search(client)[0]
    tampered = {**offer, "price": {"currency": "USD", "total": 1.0}}
    body = {"data": {"type": "flight-offers-pricing", "flightOffers": [tampered]}}

    confirmed = client.post("/v1/shopping/flight-offers/pricing", json=body).json()
    assert confirmed["data"]["flightOffers"][0]["price"] == offer["price"]  # as it was quoted

    tampered["id"] = "an-offer-nobody-made"
    assert client.post("/v1/shopping/flight-offers/pricing", json=body).status_code == 400


def test_an_expired_offer_is_refused(client):
    offer = search(client)[0]
    airline.offers[offer["id"]].expires_at = datetime.now(UTC) - timedelta(seconds=1)
    body = {"data": {"type": "flight-offers-pricing", "flightOffers": [offer]}}

    response = client.post("/v1/shopping/flight-offers/pricing", json=body)
    assert response.status_code == 400
    assert "expired" in response.json()["detail"]


def test_an_order_holds_seats_until_it_is_cancelled(client):
    body = order_for(search(client)[0])

    created = client.post("/v1/booking/flight-orders", json=body)
    assert created.status_code == 201
    order = created.json()["data"]
    assert order["ticketingAgreement"]["option"] == "DELAY_TO_CANCEL"
    assert order["travelers"] == TRAVELERS

    path = f"/v1/booking/flight-orders/{order['id']}"
    assert client.get(path).json()["data"] == order
    assert client.delete(path).status_code == 204
    assert client.get(path).status_code == 404


def test_a_hold_lapses_by_itself(client):
    body = order_for(search(client)[0])
    order = client.post("/v1/booking/flight-orders", json=body).json()["data"]

    held = airline.orders[order["id"]]
    held.ticketing_agreement.date_time = datetime.now(UTC) - timedelta(seconds=1)

    assert client.get(f"/v1/booking/flight-orders/{order['id']}").status_code == 404
