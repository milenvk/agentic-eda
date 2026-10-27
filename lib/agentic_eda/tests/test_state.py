"""The activator around an agent that declared its state: find or create, load, commit.

The broker and the store are the in-memory adapters, so no Kafka and no PostgreSQL.
"""

from contextlib import asynccontextmanager

import pytest
from pydantic import BaseModel, Field

from agentic_eda import connect, eda
from agentic_eda.activator import Activator
from agentic_eda.memory_broker import InMemoryBroker
from agentic_eda.memory_state_store import InMemoryStateStore

# A small copy of the book's trip: a request with no trip yet, the trip it creates, and
# the request the trip then makes.

TRIP_REQUESTED = "booking.TripRequested"
TRIP_CREATED = "booking.TripCreated"
ITINERARY_REQUESTED = "planning.ItineraryRequested"


@eda.event(TRIP_REQUESTED, order_per="conversation_id")
class TripRequested(eda.EventContract):
    conversation_id: str
    origin: str


@eda.event(TRIP_CREATED, order_per="trip_id")
class TripCreated(eda.EventContract):
    trip_id: int
    origin: str


@eda.event(ITINERARY_REQUESTED, order_per="trip_id")
class ItineraryRequested(eda.EventContract):
    trip_id: int
    origin: str


class Trip(BaseModel):
    trip_id: int
    status: str = "new"
    origin: str | None = None
    planned: int = 0

    def create(self, request: TripRequested) -> TripCreated:
        self.status, self.origin = "requested", request.origin
        return TripCreated(trip_id=self.trip_id, origin=self.origin)

    def request_planning(self) -> ItineraryRequested:
        self.status, self.planned = "planning", self.planned + 1
        return ItineraryRequested(trip_id=self.trip_id, origin=self.origin)


async def booking_agent(request):
    trip = eda.activation().state
    if isinstance(request, TripRequested):
        return trip.create(request)
    return trip.request_planning()


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


def activator(agent=booking_agent, **options) -> Activator:
    return Activator(
        agent,
        consumes=eda.consumes(TripRequested, TripCreated),
        produces=eda.produces(TripCreated, ItineraryRequested),
        state=eda.state(Trip, key="trip_id", created_by=[TripRequested]),
        source="BookingAgent",
        **options,
    )


async def request(broker, conversation="conv-1", id=None):
    """A request as a script publishes it: keyed by the conversation, labelled with it too."""
    return await broker.publish(
        TRIP_REQUESTED,
        "Script",
        {"conversation_id": conversation, "origin": "NYC"},
        id=id,
        attributes={"partitionkey": conversation, "correlationid": conversation},
    )


# --- the declaration


def test_a_state_is_built_from_its_key_alone():
    class Loose(BaseModel):
        trip_id: int
        origin: str  # no default: the activator could not create one for a request

    with pytest.raises(TypeError, match="every other field needs a default"):
        eda.state(Loose, key="trip_id")
    with pytest.raises(TypeError, match="no field 'id'"):
        eda.state(Trip, key="id")


def test_a_creating_event_is_an_event_about_no_state_yet():
    with pytest.raises(TypeError, match="not an @event class"):
        eda.state(Trip, key="trip_id", created_by=[Trip])
    with pytest.raises(TypeError, match="carries 'trip_id'"):
        eda.state(Trip, key="trip_id", created_by=[TripCreated])


def test_an_agent_with_state_consumes_only_events_about_it():
    @eda.event("system.SweepDue")
    class SweepDue(eda.EventContract):
        pass

    with pytest.raises(TypeError, match=r"\['SweepDue'\] carry no 'trip_id'"):
        Activator(
            booking_agent,
            consumes=eda.consumes(TripRequested, SweepDue),
            produces=eda.produces(TripCreated),
            state=eda.state(Trip, key="trip_id", created_by=[TripRequested]),
            source="BookingAgent",
        )


# --- one activation with state


async def test_a_request_creates_the_state_and_the_agent_reaches_its_next_step_through_its_own_event(system):  # fmt: skip
    broker, store = system
    async with activator().running():
        await request(broker)
        await broker.settled()

    created, planning = broker.of_type(TRIP_CREATED) + broker.of_type(ITINERARY_REQUESTED)
    assert created.data == {"trip_id": 1, "origin": "NYC"}  # the store assigned the id
    assert created.partitionkey == "1" and created.correlationid == "conv-1"
    assert planning.causationid == created.id  # the planning request, caused by the trip's own event
    document, version = await store.load(1)
    assert document["status"] == "planning" and document["trip_id"] == 1
    assert version == 2  # one commit per activation
    assert broker.failed == []


async def test_a_redelivered_request_finds_its_trip_and_causes_nothing_twice(system):
    broker, store = system
    async with activator().running():
        await request(broker, id="req-1")
        await request(broker, id="req-1")  # the same event, delivered again
        await broker.settled()

    assert len(broker.of_type(TRIP_CREATED)) == 1
    assert len(store.rows) == 1


async def test_an_event_about_a_state_the_store_never_had_is_acknowledged_with_a_warning(system, caplog):  # fmt: skip
    broker, _ = system
    async with activator().running():
        await broker.publish(TRIP_CREATED, "Elsewhere", {"trip_id": 99, "origin": "NYC"})
        await broker.settled()

    assert broker.of_type(ITINERARY_REQUESTED) == []
    assert broker.failed == []
    assert "has no Trip 99" in caplog.text


async def test_the_state_is_not_committed_when_the_answer_is_rejected(system):
    broker, store = system

    async def drifting(request):
        eda.activation().state.status = "changed"
        return "not an event"

    async with activator(drifting).running():
        await request(broker)
        await broker.settled()

    document, version = await store.load(1)
    assert (document, version) == ({}, 0)  # the row stays as created
    assert len(broker.failed) == 1


async def test_code_that_cannot_return_hands_its_answer_to_the_activation(system):
    broker, store = system

    async def through_a_tool(request):
        eda.activation().answer(await booking_agent(request))  # as an LLM's tool would

    async with activator(through_a_tool).running():
        await request(broker)
        await broker.settled()

    (created,) = broker.of_type(TRIP_CREATED)
    assert created.data["trip_id"] == 1
    assert (await store.load(1))[0]["status"] == "planning"  # and its own event was consumed


async def test_an_activation_answers_once(system):
    broker, _ = system

    async def twice(request):
        trip = eda.activation().state
        eda.activation().answer(trip.create(request))
        eda.activation().answer(trip.request_planning())

    async with activator(twice).running():
        await request(broker)
        await broker.settled()

    ((_, error),) = broker.failed
    assert "already answered with TripCreated" in str(error)


async def test_an_agent_whose_state_no_event_creates_reads_it_and_never_commits(system):
    broker, store = system
    seen = []

    async def observe(request):
        seen.append(eda.activation().state.status)
        return "ignored"

    reader = Activator(
        observe,
        consumes=eda.consumes(TripCreated),
        produces=eda.produces(),
        state=eda.state(Trip, key="trip_id"),
        source="Observer",
    )
    async with activator().running(), reader.running():
        await request(broker)
        await broker.settled()

    assert seen == ["planning"]  # the Trip as the writer last committed it
    assert (await store.load(1))[1] == 2  # two commits, both the writer's
    assert len(store.handled_events) == 2  # the reader recorded nothing


async def test_the_activation_is_only_readable_from_inside():
    with pytest.raises(RuntimeError, match="no activation running"):
        eda.activation()


async def test_an_agent_with_state_opens_the_store_with_the_broker(system, monkeypatch):
    opened = []
    broker, store = system

    @asynccontextmanager
    async def fake_state_store(client_name):
        opened.append(client_name)
        yield store

    monkeypatch.setattr(connect, "state_store", fake_state_store)
    async with activator().running():
        pass
    assert opened == ["BookingAgent"]


class FakeGraph:
    """A graph keyed by thread: the state's id is the thread once there is a state."""

    class Input(BaseModel):
        request: TripRequested | TripCreated

    def __init__(self) -> None:
        self.threads = []

    def get_input_schema(self):
        return self.Input

    async def ainvoke(self, state, config=None):
        self.threads.append(config["configurable"]["thread_id"])
        return {"answer": await booking_agent(state["request"])}


FakeGraph.__module__ = "langgraph.graph.state"


async def test_the_state_id_is_the_activation_thread(system):
    broker, _ = system
    graph = FakeGraph()
    async with activator(graph).running():
        await request(broker)
        await broker.settled()
    assert graph.threads == ["1", "1"]  # the request's activation and the trip's own
