"""Unit tests for the planning context's two contracts."""

import pytest
from pydantic import ValidationError

from agentic_eda.events import binding_of
from travel_agency.event_types import ITINERARY_PROPOSED, ITINERARY_REQUESTED
from travel_agency.events.planning import ItineraryProposed, ItineraryRequested

REQUEST = {
    "trip_id": "trip-1",
    "origin": "New York",
    "stops": [{"city": "Lisbon", "arrive": "2026-10-01", "depart": "2026-10-04"}],
    "travellers": 2,
    "budget": {"amount": 2900, "currency": "USD"},
    "preferences": "quiet, walkable, we'd take a train to save real money",
    "car_class": None,
}


def itinerary(rank: int) -> dict:
    return {
        "rank": rank,
        "label": "best value",
        "rationale": "one stop saves enough for the better hotel",
        "items": [
            {
                "kind": "stay",
                "city": "Lisbon",
                "hotel": "Casa do Bairro",
                "check_in": "2026-10-01",
                "check_out": "2026-10-04",
                "cancellation": "free until 48 hours before arrival",
                "offer": None,
            }
        ],
        "total": {"amount": 2650, "currency": "USD"},
    }


def test_each_contract_is_bound_to_its_type_and_ordered_within_its_trip():
    assert binding_of(ItineraryRequested).type == ITINERARY_REQUESTED
    assert binding_of(ItineraryProposed).type == ITINERARY_PROPOSED
    assert binding_of(ItineraryRequested).order_per == "trip_id"
    assert binding_of(ItineraryProposed).order_per == "trip_id"


def test_the_request_contract_rejects_a_trip_with_no_stops():
    with pytest.raises(ValidationError):
        ItineraryRequested.model_validate({**REQUEST, "stops": []})


def test_the_proposal_contract_holds_one_to_three_itineraries():
    ItineraryProposed.model_validate({"trip_id": "trip-1", "itineraries": [itinerary(1)]})
    with pytest.raises(ValidationError):
        ItineraryProposed.model_validate(
            {"trip_id": "trip-1", "itineraries": [itinerary(n) for n in range(1, 5)]}
        )
