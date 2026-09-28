"""Unit tests for the Itinerary Planner's graph, and for the agent as the activator hosts it."""

import asyncio
from contextlib import asynccontextmanager

from datetime import date

from conftest import brief, journey, request

from agentic_eda import connect, eda
from agentic_eda.broker import WireEvent
from agentic_eda.activator import Activator
from agentic_eda.hydration import NoHydration
from itinerary_planner.graph import MAX_ATTEMPTS, build_graph
from itinerary_planner.prompts import render
from travel_agency.event_types import ITINERARY_PROPOSED, ITINERARY_REQUESTED
from travel_agency.events.planning import ItineraryProposed, ItineraryRequested


def graph(model, airline, hotels):
    return build_graph(ask=model, airline=airline, hotels=hotels, hydration=NoHydration())


async def planned(compiled, asked: ItineraryRequested, thread: str = "trip-1") -> ItineraryProposed:
    state = await compiled.ainvoke(
        {"request": asked}, config={"configurable": {"thread_id": thread}}
    )
    return state["proposal"]


def stay(city: str, check_in: str, check_out: str) -> dict:
    return {"city": city, "check_in": check_in, "check_out": check_out, "rooms": 1}


async def test_the_items_are_in_travel_order_whatever_the_trip(model, airline, hotels):
    model.briefs = [brief(max_stops=1)]
    multi_city = request(
        budget=None,
        origin_destinations=[
            journey("NYC", "LIS", "2026-10-01"),
            journey("LIS", "OPO", "2026-10-04"),
            journey("OPO", "NYC", "2026-10-06"),
        ],
        stays=[stay("LIS", "2026-10-01", "2026-10-04"), stay("OPO", "2026-10-04", "2026-10-06")],
    )
    one_way_with_no_hotel = request(
        budget=None, origin_destinations=[journey("NYC", "LIS", "2026-10-01")], stays=[]
    )

    there_and_back = await planned(graph(model, airline, hotels), multi_city, "trip-2")
    one_way = await planned(graph(model, airline, hotels), one_way_with_no_hotel, "trip-3")

    kinds = [item.kind for item in there_and_back.itineraries[0].items]
    assert kinds == ["flight", "stay", "flight", "stay", "flight"]
    stayed = [item.city for item in there_and_back.itineraries[0].items if item.kind == "stay"]
    assert stayed == ["LIS", "OPO"]
    assert [item.kind for item in one_way.itineraries[0].items] == ["flight"]


async def test_a_journey_with_a_window_is_flown_on_the_date_the_brief_settles(
    model, airline, hotels
):
    airline.savings = {date(2026, 9, 30): 200}  # a day earlier is the cheaper day
    flexible = [journey("NYC", "LIS", "2026-10-01", 1, 1), journey("LIS", "NYC", "2026-10-04")]
    model.briefs = [brief(max_stops=1, dates=("2026-09-30", None))]

    proposal = await planned(graph(model, airline, hotels), request(origin_destinations=flexible))

    told = next(variables for name, variables in model.asked if name == "brief")
    assert told["fares"].splitlines() == [
        "NYC to LIS on 2026-09-30: from 500 USD",
        "NYC to LIS on 2026-10-01: from 700 USD",
        "NYC to LIS on 2026-10-02: from 700 USD",
    ]
    out, stayed, back = proposal.itineraries[0].items
    assert out.segments[0].departs.date() == date(2026, 9, 30)
    assert (stayed.check_in, stayed.check_out) == (date(2026, 9, 30), date(2026, 10, 4))
    assert back.segments[0].departs.date() == date(2026, 10, 4)  # it has no window


async def test_a_date_outside_the_window_is_not_searched(model, airline, hotels):
    flexible = [journey("NYC", "LIS", "2026-10-01", 1, 1), journey("LIS", "NYC", "2026-10-04")]
    model.briefs = [brief(max_stops=1, dates=("2026-09-20", "2026-10-05"))]

    proposal = await planned(graph(model, airline, hotels), request(origin_destinations=flexible))

    out, stayed, back = proposal.itineraries[0].items
    assert out.segments[0].departs.date() == date(2026, 10, 1)
    assert (stayed.check_in, stayed.check_out) == (date(2026, 10, 1), date(2026, 10, 4))
    assert back.segments[0].departs.date() == date(2026, 10, 4)


async def test_dates_leaving_a_stay_without_a_night_are_not_searched(model, airline, hotels):
    flexible = [
        journey("NYC", "LIS", "2026-10-01", days_after=3),
        journey("LIS", "NYC", "2026-10-04", days_before=3),
    ]
    model.briefs = [brief(max_stops=1, dates=("2026-10-04", "2026-10-02"))]  # home before out

    proposal = await planned(graph(model, airline, hotels), request(origin_destinations=flexible))

    out, stayed, back = proposal.itineraries[0].items
    assert (stayed.check_in, stayed.check_out) == (date(2026, 10, 1), date(2026, 10, 4))
    assert out.segments[0].departs.date() == date(2026, 10, 1)


async def test_both_suppliers_are_asked_for_the_whole_party(model, airline, hotels):
    family = request(children=[{"age": 1, "own_seat": False}, {"age": 7, "own_seat": True}])

    await planned(graph(model, airline, hotels), family)

    for adults, children in (airline.parties[0], hotels.parties[0]):
        assert adults == 2
        assert [(child.age, child.own_seat) for child in children] == [(1, False), (7, True)]


async def test_it_proposes_ranked_itineraries_carrying_the_suppliers_offers(model, airline, hotels):
    proposal = await planned(graph(model, airline, hotels), request())

    assert proposal.trip_id == 1
    assert proposal.proposal_id  # the Planner names what it publishes
    assert [i.rank for i in proposal.itineraries] == list(range(1, len(proposal.itineraries) + 1))
    assert all(i.rationale.endswith("suits this trip") for i in proposal.itineraries)  # the model's
    cheapest = next(i for i in proposal.itineraries if i.label == "cheapest")
    assert [item.kind for item in cheapest.items] == ["flight", "stay", "flight"]  # travel order
    assert cheapest.items[0].offer.offer_id == "onestop-NYC-LIS"  # the supplier's offer, as made
    assert cheapest.items[0].segments[0].carrier == "WW"  # and the airline's own flight
    stayed = cheapest.items[1]
    assert (stayed.rooms, stayed.room, stayed.rate_plan) == (1, "double", "FLEXIBLE")
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


async def test_the_brief_is_handed_to_both_searches(model, airline, hotels):
    await planned(graph(model, airline, hotels), request())

    # Rendered from the installed package's prompt files, so a file left out of the package
    # and a variable missing from a file both fail here.
    prompts = {name: render(name, **variables) for name, variables in model.asked}
    assert "favour the saving" in prompts["flights"]
    assert "favour the saving" in prompts["hotels"]
    assert "by the river" in prompts["hotels"]


async def test_the_planner_is_told_the_meaning_of_the_requests_fields(model, airline, hotels):
    await planned(graph(model, airline, hotels), request())

    prompts = {name: render(name, **variables) for name, variables in model.asked}
    for prompt in (prompts["brief"], prompts["rank"]):
        assert "  budget: Upper limit for the whole trip and all travellers." in prompt
        assert "  own_seat: False only for an infant under 2 held by an adult." in prompt
        assert "Stay: One hotel stay the travellers want." in prompt


async def test_no_area_hint_is_stated_as_no_particular_area(model, airline, hotels):
    model.briefs = [brief(max_stops=1, area_hint=None)]

    await planned(graph(model, airline, hotels), request())

    asked_of_hotels = next(variables for name, variables in model.asked if name == "hotels")
    assert asked_of_hotels["area_hint"] == "no particular area"


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
    from_toronto = [journey("YTO", "LIS", "2026-10-01"), journey("LIS", "YTO", "2026-10-04")]
    second = await planned(compiled, request("req-2", origin_destinations=from_toronto))

    assert first.itineraries[0].items[0].segments[0].origin == "NYC"
    assert second.itineraries[0].items[0].segments[0].origin == "YTO"  # on the same thread


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

