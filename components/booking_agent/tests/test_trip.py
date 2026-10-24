"""The Trip alone: its rules and its operations, as plain Python."""

from datetime import date, timedelta

import pytest
from conftest import NEXT_YEAR, proposal, requirements, trip_request, usd

from booking_agent import trip as trip_module
from booking_agent.trip import Refused, Trip
from travel_agency.events.booking import (
    ClarificationRequested,
    ItineraryApproved,
    ItineraryRejected,
    ProposalReady,
    TripChanged,
    TripCreated,
    TripRequestRejected,
)
from travel_agency.events.planning import ItineraryRequested


def proposed_trip() -> Trip:
    """A trip with one proposal on the table, the state every reply is read in."""
    trip = Trip(trip_id=42)
    trip.create(trip_request())
    trip.request_planning()
    trip.record_proposal(proposal(42))
    return trip


# --- creation and planning


def test_a_request_that_passes_the_checks_becomes_the_trip():
    trip = Trip(trip_id=42)
    created = trip.create(trip_request())
    assert isinstance(created, TripCreated)
    assert (created.trip_id, created.conversation_id) == (42, "conv-1")
    assert trip.status == "requested" and trip.requirements == requirements()


@pytest.mark.parametrize(
    "changes, problem",
    [
        ({"origin_destinations": [requirements().origin_destinations[0].model_copy(update={"departure_date": date.today()})]}, "after today"),  # fmt: skip
        ({"origin_destinations": list(reversed(requirements().origin_destinations))}, "date order"),
        ({"stays": [requirements().stays[0].model_copy(update={"check_out": date(NEXT_YEAR, 5, 10)})]}, "check out after"),  # fmt: skip
        ({"budget": usd(0)}, "more than nothing"),
    ],
)
def test_a_request_that_fails_a_check_is_rejected_and_creates_nothing(changes, problem):
    trip = Trip(trip_id=42)
    rejected = trip.create(trip_request(**changes))
    assert isinstance(rejected, TripRequestRejected) and problem in rejected.reason
    assert trip.status == "new" and trip.requirements is None


def test_the_planning_request_carries_the_requirements_and_the_reason_once():
    trip = Trip(trip_id=42)
    trip.create(trip_request())
    request = trip.request_planning()
    assert isinstance(request, ItineraryRequested)
    assert (request.trip_id, request.reason, trip.status) == (42, None, "planning")
    assert request.origin_destinations == requirements().origin_destinations

    trip.record_proposal(proposal(42))
    trip.reject("p-1", "too expensive")
    assert trip.request_planning().reason == "too expensive"
    trip.record_proposal(proposal(42, "p-2"))
    trip.reject("p-2", "still too expensive")
    assert trip.status == "requested"


def test_an_operation_out_of_its_status_is_refused():
    trip = Trip(trip_id=42)
    with pytest.raises(Refused, match="is new, not requested"):
        trip.request_planning()
    with pytest.raises(Refused, match="is new, not proposed or awaiting clarification"):
        trip.approve("p-1", 1)


def test_a_proposal_is_recorded_and_passed_on():
    trip = proposed_trip()
    assert trip.status == "proposed"
    assert [p.proposal_id for p in trip.proposals] == ["p-1"]
    with pytest.raises(Refused, match="is for trip 7"):
        Trip(trip_id=42, status="planning").record_proposal(proposal(7))


def test_a_proposal_ready_event_carries_the_itineraries_as_proposed():
    trip = Trip(trip_id=42, status="planning")
    ready = trip.record_proposal(proposal(42))
    assert isinstance(ready, ProposalReady)
    assert [i.rank for i in ready.itineraries] == [1, 2, 3]


# --- the reply's operations


def test_approving_names_one_itinerary_of_one_of_the_trips_proposals():
    trip = proposed_trip()
    approved = trip.approve("p-1", 2)
    assert isinstance(approved, ItineraryApproved) and approved.rank == 2
    assert trip.status == "approved" and trip.approved.rank == 2


@pytest.mark.parametrize(
    "proposal_id, rank, refusal",
    [("p-9", 1, "not one of trip 42's: p-1"), ("p-1", 4, "no itinerary ranked 4")],
)
def test_approving_what_was_not_proposed_is_refused(proposal_id, rank, refusal):
    trip = proposed_trip()
    with pytest.raises(Refused, match=refusal):
        trip.approve(proposal_id, rank)
    assert trip.status == "proposed"


def test_rejecting_sends_the_trip_back_to_planning_with_the_reason():
    trip = proposed_trip()
    rejected = trip.reject("p-1", "all of them are too expensive")
    assert isinstance(rejected, ItineraryRejected)
    assert (trip.status, trip.reason) == ("requested", "all of them are too expensive")


def test_changing_the_dates_moves_the_stays_with_their_journeys():
    trip = proposed_trip()
    later = [j.departure_date + timedelta(days=1) for j in requirements().origin_destinations]
    changed = trip.change("a day later, the Tuesday fares are too high", departure_dates=later)

    assert isinstance(changed, TripChanged)
    assert [j.departure_date for j in trip.requirements.origin_destinations] == later
    madrid, lisbon = trip.requirements.stays
    assert (madrid.check_in, madrid.check_out) == (date(NEXT_YEAR, 5, 11), date(NEXT_YEAR, 5, 14))
    assert (lisbon.check_in, lisbon.check_out) == (date(NEXT_YEAR, 5, 14), date(NEXT_YEAR, 5, 18))
    assert trip.status == "requested"


def test_changing_only_the_first_date_shortens_the_first_stay():
    trip = proposed_trip()
    dates = [j.departure_date for j in requirements().origin_destinations]
    dates[0] += timedelta(days=1)
    trip.change("leaving a day later", departure_dates=dates)
    madrid = trip.requirements.stays[0]
    assert (madrid.check_in, madrid.check_out) == (date(NEXT_YEAR, 5, 11), date(NEXT_YEAR, 5, 13))


def test_a_change_passes_the_same_checks_as_a_request():
    trip = proposed_trip()
    with pytest.raises(Refused, match="one date for each"):
        trip.change("whatever", departure_dates=[date(NEXT_YEAR, 6, 1)])
    with pytest.raises(Refused, match="date order"):
        trip.change("whatever", departure_dates=[date(NEXT_YEAR, 6, 1), date(NEXT_YEAR, 5, 13), date(NEXT_YEAR, 5, 17)])  # fmt: skip
    assert trip.status == "proposed"  # nothing changed

    changed = trip.change("we can spend more", budget=usd(4000))
    assert changed.requirements.budget == usd(4000)


def test_a_question_is_asked_at_most_twice_per_proposal(monkeypatch):
    trip = proposed_trip()
    asked = trip.request_clarification("p-1", "Which itinerary?", ["1", "2", "3"])
    assert isinstance(asked, ClarificationRequested)
    assert trip.status == "awaiting clarification" and trip.pending_question.question == "Which itinerary?"  # fmt: skip
    trip.request_clarification("p-1", "The morning one or the evening one?")
    with pytest.raises(Refused, match="2 questions were already asked"):
        trip.request_clarification("p-1", "Still unsure?")

    approved = trip.approve("p-1", 1)  # the reply in the awaiting state settles it
    assert approved.rank == 1 and trip.pending_question is None


def test_the_cap_is_a_setting(monkeypatch):
    monkeypatch.setattr(trip_module, "CLARIFICATION_CAP", 0)
    with pytest.raises(Refused, match="0 questions were already asked"):
        proposed_trip().request_clarification("p-1", "Which?")


def test_the_state_survives_a_round_trip_through_its_document():
    trip = proposed_trip()
    trip.request_clarification("p-1", "Which itinerary?")
    document = trip.model_dump(mode="json")
    assert document["schema_version"] == 1 and document["status"] == "awaiting clarification"
    assert Trip.model_validate(document) == trip
