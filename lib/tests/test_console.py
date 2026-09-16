"""Unit tests for the demo console renderer."""

from travel_agency import console
from travel_agency.broker import Event
from travel_agency.console import format_event


def make_event(**overrides) -> Event:
    fields = dict(
        id="event-1",
        type="booking.TripRequested",
        source="RequestTripScript",
        data={"destination": "Lisbon", "travelers": 2},
        time="2026-08-16T00:00:00+00:00",
    )
    fields.update(overrides)
    return Event(**fields)


def test_the_card_shows_the_event_not_the_data_prose():
    card = format_event("PUBLISHED", make_event())
    assert "PUBLISHED" in card
    assert "booking.TripRequested" in card
    assert "event-1" in card
    assert "RequestTripScript" in card
    assert "2026-08-16T00:00:00" in card
    assert "Lisbon" in card


def test_long_data_values_are_truncated_with_their_size():
    essay = "Day 1: fly JFK-LIS. " * 200
    card = format_event("RECEIVED", make_event(data={"itinerary": essay}))
    assert f"[truncated: {len(essay):,} chars total]" in card
    assert essay not in card


def test_short_values_are_printed_whole():
    card = format_event("RECEIVED", make_event(data={"request_id": "req-1"}))
    assert "req-1" in card
    assert "truncated" not in card


def test_multiline_values_stay_on_one_card_row():
    card = format_event("RECEIVED", make_event(data={"note": "Day 1\n\nDay 2"}))
    assert "Day 1 Day 2" in card
    assert "Day 1\n" not in card


def test_no_color_codes_when_output_is_not_a_terminal():
    # Under pytest, stdout is captured and is not a tty.
    assert "\033" not in format_event("PUBLISHED", make_event())


def test_color_codes_when_the_terminal_supports_them(monkeypatch):
    monkeypatch.setattr(console, "_use_color", lambda: True)
    assert "\033[1;32m" in format_event("PUBLISHED", make_event())


def test_force_color_overrides_the_missing_terminal(monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert "\033[1;32m" in format_event("PUBLISHED", make_event())


def test_no_color_wins_over_force_color(monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("NO_COLOR", "1")
    assert "\033" not in format_event("PUBLISHED", make_event())


def test_success_prints_a_check_and_the_message(capsys):
    console.success("SUCCESS: the itinerary arrived.")
    out = capsys.readouterr().out
    assert "✔" in out
    assert "SUCCESS: the itinerary arrived." in out


def test_success_check_is_green_when_color_is_forced(monkeypatch, capsys):
    monkeypatch.setenv("FORCE_COLOR", "1")
    console.success("SUCCESS")
    assert "\033[1;32m✔\033[0m" in capsys.readouterr().out


def test_client_errors_stay_visible(caplog):
    import logging

    console.quiet_client_logs()
    with caplog.at_level(logging.ERROR):
        logging.getLogger("aiokafka.cluster").error(
            "Topic X not found in cluster metadata"
        )
        logging.getLogger("aiokafka.conn").info("routine chatter")

    # Errors — including Kafka's routine fresh-start reports, which the demos
    # explain rather than hide — pass; INFO chatter does not.
    assert "not found in cluster metadata" in caplog.text
    assert "routine chatter" not in caplog.text
