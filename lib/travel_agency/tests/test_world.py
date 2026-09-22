"""Unit tests for the simulators' world: its reach, its routes, and its reproducibility."""

from itertools import combinations

from travel_agency.sims import world
from travel_agency.sims.world import CITIES


def test_the_world_reaches_every_inhabited_continent():
    continents = {city.continent for city in CITIES.values()}
    assert continents == {"Africa", "Asia", "Europe", "North America", "Oceania", "South America"}
    assert len(CITIES) >= 30
    assert all(city.airports and len(city.hotels) >= 3 for city in CITIES.values())


def test_every_pair_of_cities_is_connected_nonstop_or_through_one_hub():
    stranded = [
        (a.name, b.name)
        for a, b in combinations(CITIES.values(), 2)
        if not world.nonstop(a, b) and not world.connections(a, b)
    ]
    assert stranded == []


def test_distances_are_the_real_ones_near_enough():
    assert 5_300 < world.distance_km(CITIES["NYC"], CITIES["LIS"]) < 5_500
    assert 7_700 < world.distance_km(CITIES["TYO"], CITIES["SYD"]) < 7_900


def test_routes_follow_continents_and_hubs():
    assert world.nonstop(CITIES["LIS"], CITIES["OPO"])  # one continent
    assert world.nonstop(CITIES["NYC"], CITIES["LIS"])  # New York is a hub
    assert not world.nonstop(CITIES["YTO"], CITIES["RAK"])  # neither is, an ocean apart
    assert not world.nonstop(CITIES["LON"], CITIES["SYD"])  # a hub, and still out of range
    assert not world.nonstop(CITIES["LIS"], CITIES["LIS"])

    through = world.connections(CITIES["SAO"], CITIES["NBO"])
    assert through[0].name == "Johannesburg"  # the shortest detour comes first


def test_a_city_is_found_by_name_city_code_or_airport():
    assert [c.code for c in world.find_cities("lisbon")] == ["LIS"]
    assert [c.code for c in world.find_cities("NYC")] == ["NYC"]
    assert [c.code for c in world.find_cities("ewr")] == ["NYC"]  # a nearby airport
    assert world.find_cities("Atlantis") == []


def test_the_same_question_rolls_the_same_dice():
    first = world.dice("flights", "NYC", "LIS", "2026-10-01").random()
    assert first == world.dice("flights", "NYC", "LIS", "2026-10-01").random()
    assert first != world.dice("flights", "NYC", "LIS", "2026-10-02").random()
