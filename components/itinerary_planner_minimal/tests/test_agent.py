"""Unit tests for the Planner: the LLM is mocked, the broker is a stub."""

from types import SimpleNamespace

import pytest

from itinerary_planner_minimal import agent
from travel_agency.broker import Event
from travel_agency.event_types import ITINERARY_PROPOSED, TRIP_REQUESTED

FAKE_ITINERARY = "Day 1: fly JFK-LIS. Days 2-6: Lisbon. Days 7-9: Madrid."


@pytest.fixture
def llm(monkeypatch):
    """Replace litellm.acompletion with a deterministic fake and record the call."""
    calls = []

    async def fake_acompletion(*, model, messages):
        calls.append({"model": model, "messages": messages})
        message = SimpleNamespace(content=FAKE_ITINERARY)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(agent.litellm, "acompletion", fake_acompletion)
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("PLANNING_SECONDS", "0")
    return calls


def trip_requested() -> Event:
    return Event(
        id="req-42",
        type=TRIP_REQUESTED,
        source="RequestTripScript",
        payload={"destination": "Lisbon", "travelers": 2},
    )


async def test_replies_with_a_proposal_carrying_the_request_id(broker, llm):
    await agent.plan(broker, trip_requested())

    (reply,) = broker.published
    assert reply.type == ITINERARY_PROPOSED
    assert reply.source == agent.SOURCE
    assert reply.payload == {"request_id": "req-42", "itinerary": FAKE_ITINERARY}


async def test_reasons_over_the_request_with_the_configured_model(broker, llm):
    await agent.plan(broker, trip_requested())

    (call,) = llm
    assert call["model"] == "test-model"
    assert "Lisbon" in call["messages"][0]["content"]


async def test_a_fast_model_is_held_to_the_45_second_mark(broker, llm, monkeypatch):
    monkeypatch.setenv("PLANNING_SECONDS", "45")
    naps = []

    async def fake_sleep(seconds):
        naps.append(seconds)

    monkeypatch.setattr(agent.asyncio, "sleep", fake_sleep)
    await agent.plan(broker, trip_requested())

    (nap,) = naps
    assert 40 < nap <= 45  # the instant fake inference leaves nearly the full hold
    assert broker.published  # the reply still goes out, after the hold


async def test_no_hold_when_planning_seconds_is_zero(broker, llm, monkeypatch):
    naps = []

    async def fake_sleep(seconds):
        naps.append(seconds)

    monkeypatch.setattr(agent.asyncio, "sleep", fake_sleep)
    await agent.plan(broker, trip_requested())

    assert naps == []
