"""The Booking Agent through the activator: the workflow on the in-memory broker.

Two agents share the broker: the Booking Agent on ADK, with a scripted LLM for the reply,
and a stand-in for the Planner, a plain function answering every planning request with the
same proposal. The store is the in-memory one.
"""

from contextlib import asynccontextmanager

import pytest
from conftest import FakeLlm, calls, proposal, says, trip_request

from agentic_eda import connect, eda
from agentic_eda.activator import Activator
from agentic_eda.memory_broker import InMemoryBroker
from agentic_eda.memory_state_store import InMemoryStateStore
from agentic_eda.publishing import publish_fact
from booking_agent.agent import build_agent
from booking_agent.trip import Trip
from travel_agency import event_types as types
from travel_agency.events.booking import (
    ClarificationRequested,
    CustomerReplied,
    ItineraryApproved,
    ItineraryRejected,
    ProposalReady,
    TripChanged,
    TripCreated,
    TripRequested,
    TripRequestRejected,
)
from travel_agency.events.planning import ItineraryProposed, ItineraryRequested

CHANNEL = "CustomerChannel"


@pytest.fixture
def system(monkeypatch) -> tuple[InMemoryBroker, InMemoryStateStore]:
    broker, store = InMemoryBroker(), InMemoryStateStore()

    @asynccontextmanager
    async def fake_event_broker(client_name, start="now"):
        yield broker

    @asynccontextmanager
    async def fake_state_store(client_name):
        yield store

    monkeypatch.setattr(connect, "event_broker", fake_event_broker)
    monkeypatch.setattr(connect, "state_store", fake_state_store)
    return broker, store


def booking_agent(llm: FakeLlm) -> Activator:
    return Activator(
        build_agent(llm),
        consumes=eda.consumes(
            TripRequested, TripCreated, ItineraryProposed, CustomerReplied, ItineraryRejected, TripChanged
        ),
        produces=eda.produces(
            TripCreated, TripRequestRejected, ItineraryRequested, ProposalReady,
            ItineraryApproved, ItineraryRejected, TripChanged, ClarificationRequested,
        ),
        state=eda.state(Trip, key="trip_id", created_by=[TripRequested]),
        source="BookingAgent",
    )  # fmt: skip


def planner() -> Activator:
    proposals = iter(range(1, 100))

    async def plan(request: ItineraryRequested) -> ItineraryProposed:
        return proposal(request.trip_id, f"p-{next(proposals)}")

    return Activator(
        plan,
        consumes=eda.consumes(ItineraryRequested),
        produces=eda.produces(ItineraryProposed),
        source="ItineraryPlannerAgent",
    )


async def request(broker: InMemoryBroker, **changes):
    event = await publish_fact(
        broker, CHANNEL, trip_request(**changes), attributes={"correlationid": "wf-1"}
    )
    await broker.settled()
    return event


async def reply(broker: InMemoryBroker, words: str, proposal_id: str = "p-1", trip_id: int = 1):
    await publish_fact(
        broker,
        CHANNEL,
        CustomerReplied(trip_id=trip_id, proposal_id=proposal_id, words=words),
        attributes={"correlationid": "wf-1"},
    )
    await broker.settled()


def types_published(broker: InMemoryBroker) -> list[str]:
    return [event.type for event in broker.published]


# --- the activations with no LLM call


async def test_a_request_becomes_a_trip_a_planning_request_and_a_proposal_for_the_customer(system, llm):  # fmt: skip
    broker, store = system
    async with booking_agent(llm).running(), planner().running():
        requested = await request(broker)

    assert types_published(broker) == [
        types.TRIP_REQUESTED,
        types.TRIP_CREATED,
        types.ITINERARY_REQUESTED,
        types.ITINERARY_PROPOSED,
        types.PROPOSAL_READY,
    ]
    created, planning, _, ready = broker.published[1:]
    assert created.causationid == requested.id and created.partitionkey == "1"
    assert planning.causationid == created.id  # the trip's own event caused the request
    assert all(event.correlationid == "wf-1" for event in broker.published)
    assert ready.data["proposal_id"] == "p-1"
    assert llm.requests == []  # no LLM was called for any of this
    document, version = await store.load(1)
    assert (document["status"], version) == ("proposed", 3)


async def test_a_request_that_fails_the_checks_is_rejected_under_the_conversations_key(system, llm):  # fmt: skip
    broker, store = system
    async with booking_agent(llm).running():
        await request(broker, budget={"amount": 0, "currency": "USD"})

    (rejected,) = broker.of_type(types.TRIP_REQUEST_REJECTED)
    assert rejected.partitionkey == "conv-1" and "more than nothing" in rejected.data["reason"]
    assert broker.of_type(types.TRIP_CREATED) == []
    assert (await store.load(1))[0]["status"] == "new"  # the row exists; no trip does


async def test_a_redelivered_request_creates_nothing_twice(system, llm):
    broker, _ = system
    async with booking_agent(llm).running():
        requested = await request(broker)
        await broker.publish(requested.type, requested.source, requested.data, id=requested.id, attributes={"correlationid": "wf-1", "partitionkey": "conv-1"})  # fmt: skip
        await broker.settled()

    assert len(broker.of_type(types.TRIP_CREATED)) == 1


# --- the reply, read by the LLM into one operation


async def test_the_llm_reads_the_reply_against_the_proposal_and_approves(system):
    broker, store = system
    llm = FakeLlm(script=[calls("approve", proposal_id="p-1", rank=1)], requests=[])
    async with booking_agent(llm).running(), planner().running():
        await request(broker)
        await reply(broker, "The one with the morning flights, please.")

    (approved,) = broker.of_type(types.ITINERARY_APPROVED)
    assert approved.data == {"trip_id": 1, "proposal_id": "p-1", "rank": 1}
    assert (await store.load(1))[0]["status"] == "approved"
    # The LLM saw the proposal and the words, once: an accepted operation ends its turn.
    assert len(llm.requests) == 1
    prompt = llm.requests[0].config.system_instruction
    assert "best value, 3,100 USD" in prompt
    reply_as_sent = llm.requests[0].contents[-1].parts[0].text
    assert "p-1" in reply_as_sent and "morning flights" in reply_as_sent  # the id is in the reply, not the prose
    assert len(llm.requests[0].contents) == 1  # no history re-sent


async def test_a_refused_operation_returns_to_the_llm_as_an_observation(system):
    broker, _ = system
    llm = FakeLlm(
        script=[calls("approve", proposal_id="p-1", rank=4), calls("approve", proposal_id="p-1", rank=3)],  # fmt: skip
        requests=[],
    )
    async with booking_agent(llm).running(), planner().running():
        await request(broker)
        await reply(broker, "The evening one.")

    (approved,) = broker.of_type(types.ITINERARY_APPROVED)
    assert approved.data["rank"] == 3
    observation = llm.requests[1].contents[-1].parts[0].function_response.response
    assert "no itinerary ranked 4" in str(observation)


async def test_an_ambiguous_reply_earns_a_question_and_the_next_reply_settles_it(system):
    broker, store = system
    llm = FakeLlm(
        script=[
            calls("request_clarification", proposal_id="p-1", question="Which of the three itineraries?", options=["1", "2", "3"]),  # fmt: skip
            calls("approve", proposal_id="p-1", rank=2),
        ],
        requests=[],
    )
    async with booking_agent(llm).running(), planner().running():
        await request(broker)
        await reply(broker, "Sounds good.")
        assert (await store.load(1))[0]["status"] == "awaiting clarification"
        await reply(broker, "The second one.")

    (asked,) = broker.of_type(types.CLARIFICATION_REQUESTED)
    assert asked.data["question"] == "Which of the three itineraries?"
    assert "You already asked" not in llm.requests[0].config.system_instruction  # the line is left out
    assert "You already asked: Which of the three" in llm.requests[1].config.system_instruction
    assert broker.of_type(types.ITINERARY_APPROVED)[0].data["rank"] == 2


async def test_a_change_and_a_rejection_each_send_the_trip_back_to_planning(system):
    broker, store = system
    later = [f"{trip_request().origin_destinations[0].departure_date.year}-05-{day}" for day in (11, 13, 17)]  # fmt: skip
    llm = FakeLlm(
        script=[
            # The arguments as an LLM sends them: dates as strings, the budget as a JSON object.
            calls("change", reason="leaving a day later, the Tuesday fares are too high", departure_dates=later, budget={"amount": 3000, "currency": "USD"}),  # fmt: skip
            calls("reject", proposal_id="p-2", reason="all of them are too expensive"),
        ],
        requests=[],
    )
    async with booking_agent(llm).running(), planner().running():
        await request(broker)
        await reply(broker, "Could we leave a day later? The Tuesday fares are too high.")
        await reply(broker, "No, all of them are too expensive.", proposal_id="p-2")

    (changed,) = broker.of_type(types.TRIP_CHANGED)
    assert changed.data["requirements"]["origin_destinations"][0]["departure_date"] == later[0]
    assert changed.data["requirements"]["budget"] == {"amount": 3000, "currency": "USD"}
    (rejected,) = broker.of_type(types.ITINERARY_REJECTED)
    planning = broker.of_type(types.ITINERARY_REQUESTED)
    assert [event.data.get("reason") for event in planning] == [
        None,
        "leaving a day later, the Tuesday fares are too high",
        "all of them are too expensive",
    ]
    assert planning[1].causationid == changed.id and planning[2].causationid == rejected.id
    assert [event.data["proposal_id"] for event in broker.of_type(types.PROPOSAL_READY)] == ["p-1", "p-2", "p-3"]  # fmt: skip
    assert (await store.load(1))[0]["status"] == "proposed"


async def test_an_llm_that_answers_in_prose_instead_of_a_tool_call_fails_the_activation(system):
    broker, store = system
    llm = FakeLlm(script=[says("I think they like it.")], requests=[])
    async with booking_agent(llm).running(), planner().running():
        await request(broker)
        await reply(broker, "Sounds good.")

    ((failed, error),) = broker.failed
    assert failed.type == types.CUSTOMER_REPLIED and "not JSON" in str(error)
    assert (await store.load(1))[0]["status"] == "proposed"  # nothing was committed
