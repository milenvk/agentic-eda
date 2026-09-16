"""Unit tests for the Audit Consumer."""

import json

from audit_consumer.consumer import audit_line, record
from travel_agency.broker import Event


def make_event(event_id: str) -> Event:
    return Event(
        id=event_id,
        type="booking.TripRequested",
        source="RequestTripScript",
        data={"destination": "Lisbon"},
        time="2026-08-16T00:00:00+00:00",
    )


def test_audit_line_is_the_full_fact_as_json():
    line = json.loads(audit_line(make_event("event-1")))
    assert line == {
        "specversion": "1.0",
        "id": "event-1",
        "type": "booking.TripRequested",
        "source": "RequestTripScript",
        "time": "2026-08-16T00:00:00Z",
        "data": {"destination": "Lisbon"},
    }


async def test_record_appends_one_line_per_event(tmp_path):
    log_path = str(tmp_path / "audit.log")

    await record(log_path, make_event("event-1"))
    await record(log_path, make_event("event-2"))

    lines = open(log_path).read().splitlines()
    assert [json.loads(line)["id"] for line in lines] == ["event-1", "event-2"]
