"""Unit tests for the event catalog: the @event binding and the planning contracts."""

import pytest
from pydantic import BaseModel, ValidationError

from travel_agency.event_types import ITINERARY_PROPOSED, ITINERARY_REQUESTED
from travel_agency.events import OWN_ID, EventModel, Nothing, binding_of, event
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


def test_the_decorator_binds_a_class_to_its_type_and_its_ordering():
    binding = binding_of(ItineraryProposed)
    assert binding.type == ITINERARY_PROPOSED
    assert binding.order_per == "trip_id"
    assert binding_of(ItineraryRequested).type == ITINERARY_REQUESTED


def test_an_instance_carries_its_class_binding():
    assert binding_of(ItineraryRequested.model_validate(REQUEST)).order_per == "trip_id"


def test_the_binding_adds_the_discriminator_a_union_needs():
    assert ItineraryProposed.model_fields["event_type"].default == ITINERARY_PROPOSED


def test_a_model_is_never_asked_to_fill_the_attributes():
    assert "attributes_" not in ItineraryProposed.model_json_schema()["properties"]
    assert ItineraryRequested.model_validate(REQUEST).attributes_ is None


def test_order_per_is_never_left_unsaid():
    with pytest.raises(TypeError, match="declare order_per"):
        event("planning.Something")


def test_order_per_names_a_field_the_class_has():
    with pytest.raises(TypeError, match="no field 'trip'"):

        @event("planning.Something", order_per="trip")
        class Something(EventModel):
            trip_id: str


def test_the_two_other_orderings_are_written_out():
    @event("booking.TripRequested", order_per=OWN_ID)
    class TripRequested(EventModel):
        origin: str

    @event("system.SweepDue", order_per=None)
    class SweepDue(EventModel):
        pass

    assert binding_of(TripRequested).order_per is OWN_ID
    assert binding_of(SweepDue).order_per is None


def test_the_function_form_binds_a_class_you_do_not_own():
    class TheirRequest(BaseModel):
        trip_id: str

    bound = event(TheirRequest, "planning.ItineraryRequested", order_per="trip_id")
    request = bound(trip_id="trip-1")

    assert isinstance(request, TheirRequest)  # the agent still receives its own class
    assert isinstance(request, EventModel)
    assert binding_of(bound).type == "planning.ItineraryRequested"
    assert binding_of(TheirRequest) is None  # the original is left as it was


def test_nothing_is_an_answer_with_a_reason():
    assert Nothing(reason="no advisories affect a reserved destination").event_type == "nothing"
    assert binding_of(Nothing) is None  # it is never published


def test_the_request_contract_rejects_a_trip_with_no_stops():
    with pytest.raises(ValidationError):
        ItineraryRequested.model_validate({**REQUEST, "stops": []})


def test_the_proposal_contract_holds_one_to_three_itineraries():
    ItineraryProposed.model_validate({"trip_id": "trip-1", "itineraries": [itinerary(1)]})
    with pytest.raises(ValidationError):
        ItineraryProposed.model_validate(
            {"trip_id": "trip-1", "itineraries": [itinerary(n) for n in range(1, 5)]}
        )
