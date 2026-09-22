"""Unit tests for the Planner: the LLM is mocked, the broker is a stub."""

import json
from types import SimpleNamespace

import pytest

from agentic_eda.broker import Event
from itinerary_planner_minimal import agent
from travel_agency.event_types import ITINERARY_PROPOSED, ITINERARY_REQUESTED

FAKE_ITINERARIES = [
    {
        "label": "best value",
        "rationale": "Direct flights, three nights in Madrid on the way out.",
        "items": [
            {"kind": "flight", "from": "JFK", "to": "MAD", "date": "day 1", "notes": ""},
            {
                "kind": "stay",
                "city": "Madrid",
                "hotel": "Hotel Example",
                "check_in": "day 1",
                "check_out": "day 4",
            },
            {"kind": "flight", "from": "MAD", "to": "LIS", "date": "day 4", "notes": ""},
        ],
    }
]
FAKE_REPLY = json.dumps({"itineraries": FAKE_ITINERARIES})


@pytest.fixture
def llm(monkeypatch):
    """Replace litellm.acompletion with a deterministic fake and record the call."""
    calls = []

    async def fake_acompletion(*, model, messages, response_format=None):
        calls.append({"model": model, "messages": messages, "response_format": response_format})
        message = SimpleNamespace(content=FAKE_REPLY)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(agent.litellm, "acompletion", fake_acompletion)
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("PLANNING_SECONDS", "0")
    return calls


def itinerary_requested() -> Event:
    return Event(
        id="req-42",
        type=ITINERARY_REQUESTED,
        source="RequestTripScript",
        data={"destination": "Lisbon", "travelers": 2},
    )


async def test_replies_with_a_proposal_carrying_the_request_id(broker, llm):
    await agent.plan(broker, itinerary_requested())

    (reply,) = broker.published
    assert reply.type == ITINERARY_PROPOSED
    assert reply.source == agent.SOURCE
    assert reply.data == {"request_id": "req-42", "itineraries": FAKE_ITINERARIES}


async def test_reasons_over_the_request_with_the_configured_model(broker, llm):
    await agent.plan(broker, itinerary_requested())

    (call,) = llm
    assert call["model"] == "test-model"
    assert "Lisbon" in call["messages"][0]["content"]
    assert call["response_format"] == {"type": "json_object"}


async def test_a_fast_model_is_held_to_the_45_second_mark(broker, llm, monkeypatch, caplog):
    import logging

    monkeypatch.setenv("PLANNING_SECONDS", "45")
    naps = []

    async def fake_sleep(seconds):
        naps.append(seconds)

    monkeypatch.setattr(agent.asyncio, "sleep", fake_sleep)
    with caplog.at_level(logging.INFO, logger=agent.SOURCE):
        await agent.plan(broker, itinerary_requested())

    (nap,) = naps
    assert 40 < nap <= 45  # the instant fake inference leaves nearly the full hold
    assert broker.published  # the reply still goes out, after the hold
    assert "reasoning finished in" in caplog.text  # the real inference time is reported


async def test_no_hold_when_planning_seconds_is_zero(broker, llm, monkeypatch):
    naps = []

    async def fake_sleep(seconds):
        naps.append(seconds)

    monkeypatch.setattr(agent.asyncio, "sleep", fake_sleep)
    await agent.plan(broker, itinerary_requested())

    assert naps == []
