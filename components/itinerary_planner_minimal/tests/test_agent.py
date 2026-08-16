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
