"""Unit tests for the @event binding: a class, its type on the wire, and its ordering."""

import pytest
from examples import (
    ITINERARY_PROPOSED,
    ITINERARY_REQUESTED,
    REQUEST,
    ItineraryProposed,
    ItineraryRequested,
)
from pydantic import BaseModel

from agentic_eda.events import OWN_ID, EventModel, Nothing, binding_of, event

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
