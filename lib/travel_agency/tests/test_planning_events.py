"""Unit tests for the planning context's two contracts."""

import pytest
from pydantic import ValidationError

from agentic_eda.contracts import binding_of
from travel_agency.event_types import ITINERARY_PROPOSED, ITINERARY_REQUESTED
from travel_agency.events.planning import ItineraryProposed, ItineraryRequested

REQUEST = {
    "trip_id": 1,
    "origin_destinations": [
        {"origin": "NYC", "destination": "LIS", "departure_date": "2026-10-01"},
        {"origin": "LIS", "destination": "NYC", "departure_date": "2026-10-04"},
    ],
    "stays": [{"city": "LIS", "check_in": "2026-10-01", "check_out": "2026-10-04", "rooms": 1}],
    "adults": 2,
    "children": [],
    "budget": {"amount": 2900, "currency": "USD"},
    "preferences": "quiet, walkable, we'd take a stop to save real money",
    "car_class": None,
}
STAY = {
    "kind": "stay",
    "city": "LIS",
    "hotel": "Casa do Bairro",
    "rooms": 1,
    "room": "double",
    "check_in": "2026-10-01",
    "check_out": "2026-10-04",
    "rate_plan": "FLEXIBLE",
    "cancellation": "free until 48 hours before arrival",
    "offer": None,
    "backup": None,
}


def itinerary(rank: int) -> dict:
    return {
        "rank": rank,
        "label": "best value",
        "rationale": "one stop saves enough for the better hotel",
        "items": [STAY],
        "total": {"amount": 2650, "currency": "USD"},
    }


def test_each_contract_is_bound_to_its_type_and_ordered_within_its_trip():
    assert binding_of(ItineraryRequested).type == ITINERARY_REQUESTED
    assert binding_of(ItineraryProposed).type == ITINERARY_PROPOSED
    assert binding_of(ItineraryRequested).order_per == "trip_id"
    assert binding_of(ItineraryProposed).order_per == "trip_id"


def test_the_request_contract_rejects_a_trip_with_no_journey():
    with pytest.raises(ValidationError):
        ItineraryRequested.model_validate({**REQUEST, "origin_destinations": []})


def test_a_trip_may_be_one_way_and_need_no_hotel():
    one_way = {**REQUEST, "origin_destinations": REQUEST["origin_destinations"][:1], "stays": []}
    assert ItineraryRequested.model_validate(one_way).stays == []


def test_a_journey_may_start_up_to_three_days_earlier_or_later():
    def flying(**window) -> dict:
        return {**REQUEST, "origin_destinations": [{**REQUEST["origin_destinations"][0], **window}]}

    exactly = ItineraryRequested.model_validate(flying()).origin_destinations[0]
    assert (exactly.days_before, exactly.days_after) == (None, None)  # optional, and unset

    ItineraryRequested.model_validate(flying(days_before=3, days_after=1))
    with pytest.raises(ValidationError):
        ItineraryRequested.model_validate(flying(days_after=4))


def test_an_infant_has_a_seat_or_is_held_and_an_older_child_always_has_a_seat():
    def party(adults: int, *children: tuple[int, bool]) -> dict:
        ages = [{"age": age, "own_seat": own_seat} for age, own_seat in children]
        return {**REQUEST, "adults": adults, "children": ages}

    ItineraryRequested.model_validate(party(1, (0, False)))  # held
    ItineraryRequested.model_validate(party(1, (0, True), (1, True), (1, True)))  # all seated
    with pytest.raises(ValidationError, match="holds one infant"):
        ItineraryRequested.model_validate(party(1, (0, False), (1, False)))
    with pytest.raises(ValidationError, match="seat of their own"):
        ItineraryRequested.model_validate(party(2, (7, False)))


def test_a_stay_may_have_a_backup_and_the_backup_one_of_its_own():
    second = {**STAY, "hotel": "Grand Avenida"}
    first = {**STAY, "hotel": "Pensão Central", "backup": second}
    proposed = {**itinerary(1), "items": [{**STAY, "backup": first}]}

    proposal = ItineraryProposed.model_validate(
        {"trip_id": 1, "proposal_id": "p-1", "itineraries": [proposed]}
    )

    assert proposal.itineraries[0].items[0].backup.backup.hotel == "Grand Avenida"


def test_the_proposal_contract_holds_one_to_three_itineraries():
    ItineraryProposed.model_validate({"trip_id": 1, "proposal_id": "p-1", "itineraries": [itinerary(1)]})
    with pytest.raises(ValidationError):
        ItineraryProposed.model_validate(
            {"trip_id": 1, "proposal_id": "p-1", "itineraries": [itinerary(n) for n in range(1, 5)]}
        )
