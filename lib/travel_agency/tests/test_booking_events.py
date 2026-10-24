"""Unit tests for the booking context's contracts: their keys, and what they carry."""

import pytest
from pydantic import ValidationError

from agentic_eda.contracts import binding_of, data_of, key_of
from travel_agency import event_types
from travel_agency.events.booking import (
    ClarificationRequested,
    CustomerReplied,
    ItineraryApproved,
    TripCreated,
    TripRequested,
    TripRequirements,
)
from travel_agency.events.planning import ItineraryRequested

REQUIREMENTS = {
    "origin_destinations": [
        {"origin": "NYC", "destination": "LIS", "departure_date": "2027-05-10"},
        {"origin": "LIS", "destination": "NYC", "departure_date": "2027-05-17"},
    ],
    "stays": [{"city": "LIS", "check_in": "2027-05-10", "check_out": "2027-05-17", "rooms": 1}],
    "adults": 2,
    "children": [],
    "budget": {"amount": 3500, "currency": "USD"},
    "preferences": "quiet and walkable",
    "car_class": None,
}


def test_a_request_is_keyed_by_the_conversation_since_no_trip_exists_yet():
    request = TripRequested(conversation_id="conv-7", **REQUIREMENTS)
    assert binding_of(request).type == event_types.TRIP_REQUESTED
    assert key_of(request) == "conv-7"
    assert "trip_id" not in TripRequested.model_fields


@pytest.mark.parametrize(
    "cls, fields",
    [
        (TripCreated, {"conversation_id": "conv-7", "requirements": REQUIREMENTS}),
        (CustomerReplied, {"proposal_id": "p-1", "words": "the morning one"}),
        (ItineraryApproved, {"proposal_id": "p-1", "rank": 1}),
        (ClarificationRequested, {"proposal_id": "p-1", "question": "which?", "options": None}),
    ],
)
def test_every_event_about_a_trip_is_keyed_by_the_trip(cls, fields):
    assert key_of(cls(trip_id=42, **fields)) == "42"


def test_the_requirements_state_what_planning_is_asked():
    """The planning request takes a trip's requirements as they are, plus the trip's id."""
    requirements = TripRequirements.model_validate(REQUIREMENTS)
    request = ItineraryRequested(trip_id=42, **requirements.model_dump())
    assert data_of(request) == {"trip_id": 42, **REQUIREMENTS}  # no reason until a re-plan
    again = ItineraryRequested(trip_id=42, reason="a day later", **requirements.model_dump())
    assert data_of(again)["reason"] == "a day later"


def test_the_requirements_keep_the_party_rule():
    with pytest.raises(ValidationError, match="one infant at most"):
        TripRequirements.model_validate(
            {**REQUIREMENTS, "adults": 1, "children": [{"age": 1, "own_seat": False}] * 2}
        )
