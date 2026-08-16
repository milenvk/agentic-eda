"""Unit tests for the demo console renderer."""

from travel_agency import console
from travel_agency.broker import Event
from travel_agency.console import format_event


def make_event(**overrides) -> Event:
    fields = dict(
        id="event-1",
        type="com.travelagency.booking.TripRequested",
        source="RequestTripScript",
        payload={"destination": "Lisbon", "travelers": 2},
        attributes={"time": "2026-08-16T00:00:00+00:00"},
    )
    fields.update(overrides)
    return Event(**fields)


def test_the_card_shows_the_event_not_the_payload_prose():
    card = format_event("PUBLISHED", make_event())
    assert "PUBLISHED" in card
    assert "com.travelagency.booking.TripRequested" in card
    assert "event-1" in card
    assert "RequestTripScript" in card
    assert "2026-08-16T00:00:00+00:00" in card
    assert "Lisbon" in card


def test_long_payload_values_are_truncated_with_their_size():
    essay = "Day 1: fly JFK-LIS. " * 200
    card = format_event("RECEIVED", make_event(payload={"itinerary": essay}))
    assert f"[truncated: {len(essay):,} chars total]" in card
    assert essay not in card


def test_short_values_are_printed_whole():
    card = format_event("RECEIVED", make_event(payload={"request_id": "req-1"}))
    assert "req-1" in card
    assert "truncated" not in card


def test_no_color_codes_when_output_is_not_a_terminal():
    # Under pytest, stdout is captured and is not a tty.
    assert "\033" not in format_event("PUBLISHED", make_event())


def test_color_codes_when_the_terminal_supports_them(monkeypatch):
    monkeypatch.setattr(console, "_use_color", lambda: True)
    assert "\033[1;32m" in format_event("PUBLISHED", make_event())
