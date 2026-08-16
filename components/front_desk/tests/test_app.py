"""Unit tests for the Front Desk. The ASGI transport never runs the lifespan,
so no Kafka is involved."""

import asyncio

import httpx

from front_desk.app import app, relay, watchers
from travel_agency.broker import Event


def make_event() -> Event:
    return Event(
        id="event-1",
        type="com.travelagency.booking.TripRequested",
        source="RequestTripScript",
        payload={"destination": "Lisbon"},
    )


async def test_the_page_watches_the_event_stream():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert 'EventSource("/events")' in response.text


async def test_relay_fans_an_event_out_to_every_watcher():
    first, second = asyncio.Queue(), asyncio.Queue()
    watchers.update({first, second})
    try:
        await relay(make_event())
        assert first.get_nowait().id == "event-1"
        assert second.get_nowait().id == "event-1"
    finally:
        watchers.clear()
