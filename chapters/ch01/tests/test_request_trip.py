"""Chapter-level tests: the demo script's reply matching."""

from request_trip import TRIP, is_reply_to

from agentic_eda.broker import WireEvent
from travel_agency.event_types import ITINERARY_PROPOSED


def proposal(request_id: str) -> WireEvent:
    return WireEvent(
        id="reply-1",
        type=ITINERARY_PROPOSED,
        source="ItineraryPlannerAgent",
        data={"request_id": request_id, "itineraries": [{"label": "best value", "items": []}]},
    )


def test_recognizes_the_reply_to_its_own_request():
    assert is_reply_to("req-1", proposal("req-1"))


def test_ignores_replies_to_other_requests():
    assert not is_reply_to("req-1", proposal("req-2"))


def test_ignores_events_that_reference_no_request():
    stray = WireEvent(id="x", type=ITINERARY_PROPOSED, source="s", data={})
    assert not is_reply_to("req-1", stray)


def test_the_running_example_is_the_trip_chapter_1_opens_with():
    assert TRIP["origin"] == "New York (JFK)"
    assert TRIP["destination"] == "Lisbon"
    assert TRIP["travelers"] == 2
    assert TRIP["duration"] == "one week"
    assert "Madrid" in TRIP["notes"]
