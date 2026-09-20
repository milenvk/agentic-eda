"""Unit tests for the hotel simulator, called through an MCP client as the Planner calls it."""

from mcp import Client

from hotel_reservation_system_sim.server import mcp

THREE_NIGHTS = {"city": "Lisbon", "check_in": "2026-10-01", "check_out": "2026-10-04", "guests": 2}


async def search(**changes):
    async with Client(mcp) as client:
        return await client.call_tool("search_availability", {**THREE_NIGHTS, **changes})


async def offers(**changes) -> list[dict]:
    result = await search(**changes)
    assert not result.is_error, result.content
    return result.structured_content["offers"]


async def test_the_tool_describes_itself_to_a_client():
    async with Client(mcp) as client:
        (tool,) = (await client.list_tools()).tools
    assert tool.name == "search_availability"
    assert set(tool.input_schema["required"]) == {"city", "check_in", "check_out", "guests"}


async def test_the_same_question_finds_the_same_rooms_at_the_same_rates():
    def facts(found):
        return [(o["offer_id"], o["rooms_left"], o["total"]) for o in found]

    assert facts(await offers()) == facts(await offers())
    assert facts(await offers()) != facts(await offers(check_in="2026-10-02"))


async def test_each_hotel_is_offered_under_each_rate_plan_with_its_cancellation_policy():
    found = await offers()
    flexible = {o["hotel"]: o for o in found if o["rate_plan"] == "FLEXIBLE"}
    advance = {o["hotel"]: o for o in found if o["rate_plan"] == "ADVANCE"}

    assert flexible and flexible.keys() == advance.keys()
    for hotel, offer in flexible.items():
        assert "free cancellation" in offer["cancellation"]
        assert advance[hotel]["cancellation"] == "no refund once booked"
        assert advance[hotel]["total"] < offer["total"]  # the price of flexibility
        assert offer["currency"] == "USD"
        assert offer["area"]  # what a preference is judged against


async def test_a_hotel_without_rooms_enough_for_the_party_is_left_out():
    couple = await offers(guests=2)
    big_party = await offers(guests=12)  # six rooms, the most any hotel ever has left

    assert all(o["rooms_left"] >= 1 for o in couple)
    assert all(o["rooms_left"] == 6 for o in big_party)
    assert len(big_party) < len(couple)


async def test_a_longer_stay_costs_more():
    def cheapest(found):
        return min(o["total"] for o in found)

    assert cheapest(await offers(check_out="2026-10-08")) > cheapest(await offers())


async def test_every_city_in_the_world_has_hotels_to_offer():
    assert await offers(city="Nairobi")
    assert await offers(city="Auckland")


async def test_a_question_that_cannot_be_answered_is_an_error_saying_why():
    unknown = await search(city="Atlantis")
    backwards = await search(check_out="2026-09-30")

    assert unknown.is_error and "Atlantis" in unknown.content[0].text
    assert backwards.is_error and "check_out" in backwards.content[0].text
