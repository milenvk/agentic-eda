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

from pydantic import Field

from agentic_eda.contracts import (
    OWN_ID,
    EventContract,
    Nothing,
    binding_of,
    data_of,
    event,
    meanings_of,
)

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
        class Something(EventContract):
            trip_id: str


def test_the_two_other_orderings_are_written_out():
    @event("booking.TripRequested", order_per=OWN_ID)
    class TripRequested(EventContract):
        origin: str

    @event("system.SweepDue", order_per=None)
    class SweepDue(EventContract):
        pass

    assert binding_of(TripRequested).order_per is OWN_ID
    assert binding_of(SweepDue).order_per is None


def test_the_function_form_binds_a_class_you_do_not_own():
    class TheirRequest(BaseModel):
        trip_id: str

    bound = event(TheirRequest, "planning.ItineraryRequested", order_per="trip_id")
    request = bound(trip_id="trip-1")

    assert isinstance(request, TheirRequest)  # the agent still receives its own class
    assert isinstance(request, EventContract)
    assert binding_of(bound).type == "planning.ItineraryRequested"
    assert binding_of(TheirRequest) is None  # the original is left as it was


def test_an_unset_optional_field_is_left_out_of_the_published_data():
    class Budget(BaseModel):
        amount: float
        note: str | None = None

    @event("planning.Asked", order_per="trip_id")
    class Asked(EventContract):
        trip_id: str
        budget: Budget | None  # required, so published, null included
        car_class: str | None = None  # optional, so left out while unset

    assert data_of(Asked(trip_id="t-1", budget=None)) == {"trip_id": "t-1", "budget": None}
    stated = Asked(trip_id="t-1", budget=Budget(amount=2800), car_class="compact")
    assert data_of(stated) == {
        "trip_id": "t-1",
        "budget": {"amount": 2800.0},
        "car_class": "compact",
    }
    assert Asked.model_validate(data_of(stated)) == stated  # nothing is lost on the way


def test_a_contracts_meanings_are_its_docstrings_and_descriptions_as_text():
    class Budget(BaseModel):
        """An amount in one currency."""

        amount: float
        currency: str = Field(description="ISO 4217 code, such as USD.")

    class Traveller(BaseModel):  # nothing is said about it, so it is left out
        age: int

    @event("planning.Asked", order_per="trip_id")
    class Asked(EventContract):
        """Someone asks for a plan."""

        trip_id: str
        budget: Budget | None = Field(description="Null means no limit.")
        travellers: list[Traveller]

    assert meanings_of(Asked).splitlines() == [
        "Asked: Someone asks for a plan.",
        "  budget: Null means no limit.",
        "Budget: An amount in one currency.",
        "  currency: ISO 4217 code, such as USD.",
    ]


def test_the_only_default_a_contract_may_have_is_none():
    class Room(BaseModel):
        beds: int = 2

    with pytest.raises(TypeError, match="Asked.priority has a default"):

        @event("planning.Asked", order_per=None)
        class Asked(EventContract):
            priority: str = "normal"

    with pytest.raises(TypeError, match="Room.beds has a default"):

        @event("planning.Stayed", order_per=None)
        class Stayed(EventContract):
            rooms: list[Room]  # a class inside a contract is part of the contract


def test_nothing_is_an_answer_with_a_reason():
    assert Nothing(reason="no advisories affect a reserved destination").event_type == "nothing"
    assert binding_of(Nothing) is None  # it is never published
