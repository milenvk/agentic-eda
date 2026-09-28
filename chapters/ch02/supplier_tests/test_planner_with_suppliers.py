"""The Planner's clients against the two running simulators, over the network.

Each component's own suite tests its side of the conversation against a stand-in. This
suite is where the two sides meet: it runs in the Planner's image, with both simulators
up, and needs no Kafka and no model.
"""

from datetime import date

from conftest import FakeModel, brief, request

from agentic_eda.hydration import NoHydration
from itinerary_planner import suppliers_clients
from itinerary_planner.graph import build_graph
from travel_agency.events.planning import Child, OriginDestination, Stay

ARRIVE, DEPART = date(2027, 5, 10), date(2027, 5, 13)
TO_MADRID = OriginDestination(origin="NYC", destination="MAD", departure_date=ARRIVE)
IN_MADRID = Stay(city="MAD", check_in=ARRIVE, check_out=DEPART, rooms=1)
A_BABY_AND_A_CHILD = [Child(age=1, own_seat=False), Child(age=7, own_seat=True)]


async def test_the_airline_answers_the_planners_search():
    offers = await suppliers_clients.airline().search(TO_MADRID, 2, [], max_stops=1)

    assert {offer.stops for offer in offers} == {0, 1}
    assert all(offer.segments[0].origin in ("JFK", "EWR") for offer in offers)
    assert all(offer.segments[-1].destination == "MAD" for offer in offers)
    assert all(offer.arrives > offer.departs and offer.price.amount > 0 for offer in offers)


async def test_a_family_pays_the_airline_by_passenger_type():
    couple = await suppliers_clients.airline().search(TO_MADRID, 2, [], max_stops=0)
    family = await suppliers_clients.airline().search(TO_MADRID, 2, A_BABY_AND_A_CHILD, 0)

    assert family[0].offer_id.endswith("2ADT1CHD1INF")
    assert couple[0].price.amount < family[0].price.amount < 2 * couple[0].price.amount


async def test_the_hotels_answer_the_planners_search():
    offers = await suppliers_clients.hotels().availability(IN_MADRID, 2, A_BABY_AND_A_CHILD)

    assert offers
    assert all(offer.city == "MAD" and offer.rooms_left >= 1 for offer in offers)
    assert all(offer.room == "family" for offer in offers)  # three guests, the baby in a cot
    assert all((offer.check_in, offer.check_out) == (ARRIVE, DEPART) for offer in offers)


async def test_the_graph_plans_a_trip_across_the_world_on_the_suppliers_offers():
    model = FakeModel()
    model.briefs = [brief(max_stops=1)]
    graph = build_graph(
        ask=model,
        airline=suppliers_clients.airline(),
        hotels=suppliers_clients.hotels(),
        hydration=NoHydration(),
    )
    asked = request(
        origin_destinations=[
            {"origin": "SAO", "destination": "NBO", "departure_date": "2027-07-02"},
            {"origin": "NBO", "destination": "SAO", "departure_date": "2027-07-09"},
        ],
        stays=[{"city": "NBO", "check_in": "2027-07-02", "check_out": "2027-07-09", "rooms": 1}],
        budget=None,
    )

    state = await graph.ainvoke({"request": asked}, config={"configurable": {"thread_id": "t-1"}})

    proposal = state["proposal"]
    assert proposal.itineraries
    cheapest = next(i for i in proposal.itineraries if i.label == "cheapest")
    assert [item.kind for item in cheapest.items] == ["flight", "stay", "flight"]
    assert cheapest.items[1].city == "NBO"
    assert cheapest.items[0].offer.supplier == "Airline Reservation System"
