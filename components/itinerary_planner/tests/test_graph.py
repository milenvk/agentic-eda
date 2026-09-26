"""Unit tests for the Itinerary Planner's graph, and for the agent as the activator hosts it."""

import asyncio
from contextlib import asynccontextmanager

from conftest import brief, request

from agentic_eda import connect, eda
from agentic_eda.broker import WireEvent
from agentic_eda.activator import Activator
from agentic_eda.hydration import NoHydration
from itinerary_planner.graph import MAX_ATTEMPTS, build_graph, legs_of
from travel_agency.event_types import ITINERARY_PROPOSED, ITINERARY_REQUESTED
from travel_agency.events.planning import ItineraryProposed, ItineraryRequested


def graph(model, airline, hotels):
    return build_graph(ask=model, airline=airline, hotels=hotels, hydration=NoHydration())


async def planned(compiled, asked: ItineraryRequested, thread: str = "trip-1") -> ItineraryProposed:
    state = await compiled.ainvoke(
        {"request": asked}, config={"configurable": {"thread_id": thread}}
    )
    return state["proposal"]


def test_a_trip_flies_out_on_between_stops_and_home():
    one_stop = legs_of(request())
    assert [(leg.origin, leg.destination) for leg in one_stop] == [
        ("New York", "Lisbon"),
        ("Lisbon", "New York"),
    ]
    two_stops = legs_of(
        request(
            stops=[
                {"city": "Lisbon", "arrive": "2026-10-01", "depart": "2026-10-04"},
                {"city": "Porto", "arrive": "2026-10-04", "depart": "2026-10-06"},
            ]
        )
    )
    assert [leg.destination for leg in two_stops] == ["Lisbon", "Porto", "New York"]
    assert str(two_stops[1].on) == "2026-10-04"


async def test_it_proposes_ranked_itineraries_carrying_the_suppliers_offers(model, airline, hotels):
    proposal = await planned(graph(model, airline, hotels), request())

    assert proposal.trip_id == 1
    assert proposal.proposal_id  # the Planner names what it publishes
    assert [i.rank for i in proposal.itineraries] == list(range(1, len(proposal.itineraries) + 1))
    assert all(i.rationale.endswith("suits this trip") for i in proposal.itineraries)  # the model's
    cheapest = next(i for i in proposal.itineraries if i.label == "cheapest")
    assert [item.kind for item in cheapest.items] == ["flight", "stay", "flight"]  # travel order
    assert cheapest.items[0].offer.offer_id == "onestop-New-Lis"  # the supplier's offer, as made
    assert cheapest.total.amount == 700 + 600 + 700


async def test_the_validators_loop_is_what_settles_the_two_searches_together(model, airline, hotels):
    # Nonstop flights alone leave too little for any hotel, and only the validator can say so.
    model.briefs = [brief(max_stops=0), brief(max_stops=1)]

    proposal = await planned(graph(model, airline, hotels), request())

    assert airline.searches == [0, 0, 1, 1]  # two legs, searched again with a stop allowed
    second_brief = [variables for name, variables in model.asked if name == "brief"][1]
    assert "over the 2,900 budget" in second_brief["problems"]  # the planner was told why
    assert all(i.total.amount <= 2900 for i in proposal.itineraries)


async def test_out_of_attempts_it_proposes_the_nearest_it_found(model, airline, hotels):
    model.briefs = [brief(max_stops=0)]  # it never learns

    proposal = await planned(graph(model, airline, hotels), request(budget=1000))

    assert len([name for name, _ in model.asked if name == "brief"]) == MAX_ATTEMPTS
    assert proposal.itineraries  # over budget, and proposed all the same


async def test_with_no_budget_nothing_loops(model, airline, hotels):
    model.briefs = [brief(max_stops=0)]
    await planned(graph(model, airline, hotels), request(budget=None))
    assert [name for name, _ in model.asked].count("brief") == 1


async def test_a_nonstop_nobody_flies_is_searched_again_with_a_stop(model, airline, hotels):
    airline.flies_nonstop = False
    model.briefs = [brief(max_stops=0)]

    proposal = await planned(graph(model, airline, hotels), request(budget=None))

    assert airline.searches == [0, 1, 0, 1]  # each leg, asked twice
    assert proposal.itineraries


async def test_a_pick_nobody_offered_falls_back_to_price(model, airline, hotels):
    async def wayward(name, answer, **variables):
        reply = await model(name, answer, **variables)
        if name == "flights":
            reply.offer_ids = ["an-offer-nobody-made"]
        return reply

    proposal = await planned(graph(wayward, airline, hotels), request())
    flights = [item for i in proposal.itineraries for item in i.items if item.kind == "flight"]
    assert all(flight.offer.offer_id.startswith(("onestop", "nonstop", "flex")) for flight in flights)


async def test_a_new_request_for_the_same_trip_starts_from_a_clean_slate(model, airline, hotels):
    compiled = graph(model, airline, hotels)

    first = await planned(compiled, request("req-1"))
    second = await planned(compiled, request("req-2", origin="Toronto"))  # the same thread

    assert first.itineraries[0].items[0].origin == "New York"
    assert second.itineraries[0].items[0].origin == "Toronto"


def test_the_agent_module_knows_nothing_of_events():
    from itinerary_planner import agent

    assert hasattr(agent.agent, "ainvoke")  # a compiled graph, as its developer built it
    assert not hasattr(agent, "eda")  # what it consumes and produces is declared in app.py


async def test_hosted_by_the_activator_it_answers_an_event_with_an_event(
    model, airline, hotels, monkeypatch
):
    published: list[WireEvent] = []
    handlers = {}

    class StubBroker:
        async def publish(self, event_type, source, data, id=None, attributes=None) -> WireEvent:
            event = WireEvent(id=id or "p-1", type=event_type, source=source, data=data, **attributes)
            published.append(event)
            return event

        async def subscribe(self, event_type, handler, mode="broadcast") -> None:
            handlers[event_type] = handler

        async def run(self) -> None:
            await asyncio.Event().wait()

    @asynccontextmanager
    async def fake_event_broker(client_name, start="now"):
        yield StubBroker()

    monkeypatch.setattr(connect, "event_broker", fake_event_broker)
    activator = Activator(
        graph(model, airline, hotels),
        consumes=eda.consumes(ItineraryRequested),
        produces=eda.produces(ItineraryProposed),
        source="ItineraryPlannerAgent",
    )
    asked = WireEvent(
        id="req-1",
        type=ITINERARY_REQUESTED,
        source="RequestTripScript",
        data=request().model_dump(mode="json", exclude={"attributes_", "event_type"}),
        correlationid="req-1",
        partitionkey="1",
    )

    async with activator.running():
        await handlers[ITINERARY_REQUESTED](asked)

    (proposal,) = published
    assert proposal.type == ITINERARY_PROPOSED
    assert (proposal.causationid, proposal.correlationid) == ("req-1", "req-1")
    assert proposal.partitionkey == "1"
    assert ItineraryProposed.model_validate(proposal.data).itineraries  # a valid contract, on the wire

