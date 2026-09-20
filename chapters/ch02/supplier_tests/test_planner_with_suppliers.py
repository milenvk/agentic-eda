"""The Planner's clients against the two running simulators, over the network.

Each component's own suite tests its side of the conversation against a stand-in. This
suite is where the two sides meet: it runs in the Planner's image, with both simulators
up, and needs no Kafka and no model.
"""

from datetime import date

from conftest import FakeModel, brief, request

from itinerary_planner import suppliers_clients
from itinerary_planner.graph import build_graph
from travel_agency.hydration import NoHydration

ARRIVE, DEPART = date(2027, 5, 10), date(2027, 5, 13)


async def test_the_airline_answers_the_planners_search():
    offers = await suppliers_clients.airline().search("New York", "Madrid", ARRIVE, 2, max_stops=1)

    assert {offer.stops for offer in offers} == {0, 1}
    assert all(offer.origin in ("JFK", "EWR") and offer.destination == "MAD" for offer in offers)
    assert all(offer.arrives > offer.departs and offer.price.amount > 0 for offer in offers)


async def test_the_hotels_answer_the_planners_search():
    offers = await suppliers_clients.hotels().availability("Madrid", ARRIVE, DEPART, travellers=2)

    assert offers
    assert all(offer.city == "Madrid" and offer.rooms_left >= 1 for offer in offers)
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
        origin="São Paulo",
        stops=[{"city": "Nairobi", "arrive": "2027-07-02", "depart": "2027-07-09"}],
        budget=None,
    )

    state = await graph.ainvoke({"request": asked}, config={"configurable": {"thread_id": "t-1"}})

    proposal = state["proposal"]
    assert proposal.itineraries
    cheapest = next(i for i in proposal.itineraries if i.label == "cheapest")
    assert [item.kind for item in cheapest.items] == ["flight", "stay", "flight"]
    assert cheapest.items[1].city == "Nairobi"
    assert cheapest.items[0].offer.supplier == "Airline Reservation System"
