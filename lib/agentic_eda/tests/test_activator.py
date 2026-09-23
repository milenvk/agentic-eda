"""Unit tests for the agent activator: declarations, one activation, and the attachment.

The broker is a stub, so no Kafka and no network are involved.
"""

import asyncio
import json
from contextlib import asynccontextmanager

import pytest
from examples import (
    ITINERARY_PROPOSED,
    ITINERARY_REQUESTED,
    PROPOSAL,
    REQUEST,
    ItineraryProposed,
    ItineraryRequested,
)
from pydantic import BaseModel, ValidationError
from starlette.applications import Starlette

from agentic_eda import connect, eda
from agentic_eda.broker import Event
from agentic_eda.activator import Activator, NoAnswer, RejectedAnswer
from agentic_eda.activator.adapters import adapter_for
from agentic_eda.activator.declarations import PureConsumer, produced_classes


class StubBroker:
    def __init__(self) -> None:
        self.published: list[Event] = []
        self.handlers: dict[str, object] = {}

    async def publish(self, event_type, source, data, id=None, attributes=None) -> Event:
        event = Event(
            id=id or f"stub-{len(self.published)}",
            type=event_type,
            source=source,
            data=data,
            **(attributes or {}),
        )
        self.published.append(event)
        return event

    async def subscribe(self, event_type, handler, mode="broadcast") -> None:
        self.handlers[event_type] = handler

    async def run(self) -> None:
        await asyncio.Event().wait()


@pytest.fixture
def broker(monkeypatch) -> StubBroker:
    stub = StubBroker()

    @asynccontextmanager
    async def fake_event_broker(client_name, start="now"):
        yield stub

    monkeypatch.setattr(connect, "event_broker", fake_event_broker)
    return stub


def requested(**attributes) -> Event:
    return Event(
        id="req-1", type=ITINERARY_REQUESTED, source="RequestTripScript", data=REQUEST,
        **attributes,
    )  # fmt: skip


async def activate(agent, broker, event=None, produces=None) -> list[Event]:
    activator = Activator(
        agent,
        consumes=eda.consumes(ItineraryRequested),
        produces=eda.produces(ItineraryProposed) if produces is None else produces,
        source="ItineraryPlannerAgent",
    )
    async with activator.running():
        await broker.handlers[ITINERARY_REQUESTED](event or requested())
    return broker.published


# --- declarations


def test_consumes_refuses_a_class_that_is_not_an_event():
    class Plain(BaseModel):
        trip_id: str

    with pytest.raises(TypeError, match="not an @event class"):
        eda.consumes(Plain)


def test_an_option_about_particular_classes_names_declared_ones():
    eda.consumes(ItineraryRequested, interrupting=[ItineraryRequested])
    with pytest.raises(TypeError, match="not among the consumed ones"):
        eda.consumes(ItineraryRequested, interrupting=[ItineraryProposed])


def test_produces_with_one_class_is_that_class():
    assert eda.produces(ItineraryProposed) is ItineraryProposed


def test_produces_with_a_choice_wraps_the_union_under_an_object_root():
    answer = eda.produces(ItineraryProposed, eda.Nothing)
    schema = answer.model_json_schema()

    assert schema["type"] == "object" and "anyOf" not in schema  # what a strict schema wants
    assert list(schema["properties"]) == ["fact"]
    assert produced_classes(answer) == (ItineraryProposed, eda.Nothing)


def test_produces_with_no_classes_declares_a_pure_consumer():
    assert eda.produces() is PureConsumer
    assert produced_classes(PureConsumer) == ()


def test_produces_refuses_a_default_a_strict_schema_cannot_express():
    @eda.event("planning.Loose", order_per=None)
    class Loose(eda.EventModel):
        currency: str = "USD"

    with pytest.raises(TypeError, match="Loose.currency has a default"):
        eda.produces(Loose)


def test_a_component_has_to_be_named(monkeypatch):
    monkeypatch.delenv("COMPONENT_NAME", raising=False)

    async def agent(request):
        return None

    with pytest.raises(RuntimeError, match="name the component"):
        Activator(agent, consumes=eda.consumes(ItineraryRequested), produces=eda.produces(), source=None)  # fmt: skip


# --- one activation


async def test_the_agent_receives_its_own_class_and_the_activator_publishes_its_answer(broker):
    seen = []

    async def plan(request: ItineraryRequested) -> ItineraryProposed:
        seen.append(request)
        return ItineraryProposed.model_validate(PROPOSAL)

    (published,) = await activate(plan, broker, requested(correlationid="conv-7", partitionkey="trip-1"))  # fmt: skip

    (request,) = seen
    assert isinstance(request, ItineraryRequested)
    assert request.attributes_.source == "RequestTripScript"  # the attributes beside the data
    assert published.type == ITINERARY_PROPOSED
    assert published.source == "ItineraryPlannerAgent"
    assert published.correlationid == "conv-7"  # the thread, carried on
    assert published.causationid == "req-1"  # the event it answers
    assert published.partitionkey == "trip-1"  # from order_per
    assert "event_type" not in published.data and "attributes_" not in published.data
    assert len(published.data["itineraries"]) == 2


async def test_a_thread_starts_at_the_event_that_carries_no_correlation(broker):
    async def plan(request):
        return ItineraryProposed.model_validate(PROPOSAL)

    (published,) = await activate(plan, broker)
    assert published.correlationid == "req-1"


async def test_a_credential_never_reaches_the_agent(broker):
    seen = []

    async def plan(request):
        seen.append(request.attributes_)
        return ItineraryProposed.model_validate(PROPOSAL)

    await activate(plan, broker, requested(identitytoken="signed.token"))
    assert not hasattr(seen[0], "identitytoken")


async def test_a_malformed_event_is_rejected_before_the_agent_and_acknowledged(broker):
    called = []

    async def plan(request):
        called.append(request)

    malformed = Event(id="req-2", type=ITINERARY_REQUESTED, source="s", data={"trip_id": "t"})
    assert await activate(plan, broker, malformed) == []
    assert called == []


async def test_an_agent_that_answers_nothing_is_a_failure(broker):
    async def plan(request):
        return None

    with pytest.raises(NoAnswer, match="published nothing"):
        await activate(plan, broker)


async def test_an_agent_may_say_it_has_nothing_to_say(broker, caplog):
    async def plan(request):
        return eda.Nothing(reason="no route fits the budget")

    caplog.set_level("INFO")
    published = await activate(plan, broker, produces=eda.produces(ItineraryProposed, eda.Nothing))
    assert published == []
    assert "no route fits the budget" in caplog.text


async def test_where_code_answers_no_answer_is_nothing_if_declared(broker):
    async def plan(request):
        return None

    assert await activate(plan, broker, produces=eda.produces(ItineraryProposed, eda.Nothing)) == []


async def test_a_pure_consumer_answers_with_nothing_and_that_is_fine(broker):
    async def record(request):
        return "ignored"

    assert await activate(record, broker, produces=eda.produces()) == []


@pytest.mark.parametrize(
    "answer",
    [PROPOSAL, json.dumps(PROPOSAL), {"fact": {**PROPOSAL, "event_type": ITINERARY_PROPOSED}}],
    ids=["a dict", "json text", "the wrapper's shape"],
)
async def test_an_answer_is_reduced_to_a_declared_class(broker, answer):
    async def plan(request):
        return answer

    (published,) = await activate(
        plan, broker, produces=eda.produces(ItineraryProposed, eda.Nothing)
    )
    assert published.type == ITINERARY_PROPOSED


async def test_an_answer_of_an_undeclared_class_is_rejected(broker):
    async def plan(request):
        return request  # a request is not what this agent produces

    with pytest.raises(RejectedAnswer, match="not among what"):
        await activate(plan, broker)


async def test_an_answer_is_validated_on_the_way_out_whatever_built_it(broker):
    async def plan(request):
        return ItineraryProposed.model_construct(trip_id="trip-1", itineraries=[])

    with pytest.raises(ValidationError):
        await activate(plan, broker)
    assert broker.published == []


async def test_code_may_publish_mid_activation_and_that_counts_as_its_answer(broker):
    async def plan(request):
        first = await eda.publish(ItineraryProposed.model_validate(PROPOSAL))
        assert first.causationid == "req-1"

    (published,) = await activate(plan, broker)
    assert published.type == ITINERARY_PROPOSED


async def test_publish_is_only_available_inside_an_activation():
    with pytest.raises(RuntimeError, match="inside an activation"):
        await eda.publish(ItineraryProposed.model_validate(PROPOSAL))


async def test_the_event_that_starts_a_sequence_is_keyed_on_its_own_id(broker):
    @eda.event("booking.TripRequested", order_per=eda.OWN_ID)
    class TripRequested(eda.EventModel):
        origin: str

    async def ask(request):
        return TripRequested(origin="Nairobi")

    (published,) = await activate(ask, broker, produces=eda.produces(TripRequested))
    assert published.partitionkey == published.id


async def test_an_event_nothing_orders_carries_no_key(broker):
    @eda.event("system.SweepDue", order_per=None)
    class SweepDue(eda.EventModel):
        pass

    async def sweep(request):
        return SweepDue()

    (published,) = await activate(sweep, broker, produces=eda.produces(SweepDue))
    assert not hasattr(published, "partitionkey")


# --- adapters


class FakeGraph:
    """Stands in for a compiled graph: the adapter is chosen by the class's module."""

    class Input(BaseModel):
        request: ItineraryRequested
        flights: list[str] = []

    def __init__(self) -> None:
        self.calls = []

    def get_input_schema(self):
        return self.Input

    async def ainvoke(self, state, config=None):
        self.calls.append((state, config))
        return {**state, "proposal": ItineraryProposed.model_validate(PROPOSAL)}


FakeGraph.__module__ = "langgraph.graph.state"


async def test_a_graph_gets_the_request_by_type_and_its_answer_is_found_by_type(broker):
    graph = FakeGraph()

    (published,) = await activate(graph, broker, requested(partitionkey="trip-1"))

    ((state, config),) = graph.calls
    assert isinstance(state["request"], ItineraryRequested)
    assert config == {"configurable": {"thread_id": "trip-1"}}  # the key is the thread
    assert published.type == ITINERARY_PROPOSED


def test_an_agent_of_an_unknown_framework_names_its_adapter():
    with pytest.raises(TypeError, match="pass one to attach"):
        adapter_for(object())


def test_a_function_whose_return_type_disagrees_with_produces_fails_at_startup():
    async def plan(request: ItineraryRequested) -> ItineraryRequested:
        return request

    with pytest.raises(TypeError, match="does not declare"):
        Activator(
            plan,
            consumes=eda.consumes(ItineraryRequested),
            produces=eda.produces(ItineraryProposed),
            source="ItineraryPlannerAgent",
        )


# --- the attachment


async def test_the_activator_starts_and_stops_with_the_app_that_hosts_the_agent(broker):
    hosted = []

    @asynccontextmanager
    async def lifespan(app):
        hosted.append("started")
        yield
        hosted.append("stopped")

    async def plan(request):
        return ItineraryProposed.model_validate(PROPOSAL)

    app = Starlette(lifespan=lifespan)
    eda.attach(
        app,
        plan,
        consumes=eda.consumes(ItineraryRequested),
        produces=eda.produces(ItineraryProposed),
        source="ItineraryPlannerAgent",
    )

    async with app.router.lifespan_context(app):
        assert hosted == ["started"]  # the app's own lifespan still runs
        assert list(broker.handlers) == [ITINERARY_REQUESTED]  # subscribed, by the event's type
    assert hosted == ["started", "stopped"]
