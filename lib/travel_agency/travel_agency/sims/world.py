"""The world every simulator draws from: cities, their airports and hotels, and the routes.

The facts are in `world.json`. Every simulator prices in US dollars and keeps time in UTC,
so nothing in the application converts a currency or a time zone.
"""

import json
import math
import random
from importlib import resources

from pydantic import BaseModel

CURRENCY = "USD"
LONGEST_NONSTOP_KM = 14_000
EARTH_RADIUS_KM = 6_371


class Hotel(BaseModel):
    name: str
    area: str  # the neighbourhood, and what staying there is like
    stars: int
    nightly: float  # a room's usual rate for one night


class City(BaseModel):
    name: str
    country: str
    continent: str
    code: str  # the IATA city code, covering every airport of the city
    airports: list[str]
    hub: bool = False
    latitude: float
    longitude: float
    hotels: list[Hotel]


def _load() -> dict[str, City]:
    text = resources.files(__package__).joinpath("world.json").read_text(encoding="utf-8")
    return {entry["code"]: City(**entry) for entry in json.loads(text)["cities"]}


CITIES = _load()


def find_cities(keyword: str) -> list[City]:
    """The city with this code, or else the cities matching a name or an airport code."""
    wanted = keyword.strip().casefold()
    coded = CITIES.get(wanted.upper())
    if coded is not None:
        return [coded]  # LON is London, although Barcelona's name contains it
    return [
        city
        for city in CITIES.values()
        if wanted in city.name.casefold()
        or wanted in (airport.casefold() for airport in city.airports)
    ]


def distance_km(a: City, b: City) -> float:
    """The great-circle distance between two cities, by the haversine formula."""
    lat_a, lat_b = math.radians(a.latitude), math.radians(b.latitude)
    half_lat = (lat_b - lat_a) / 2
    half_lon = math.radians(b.longitude - a.longitude) / 2
    h = math.sin(half_lat) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(half_lon) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def nonstop(a: City, b: City) -> bool:
    """Airlines fly nonstop within a continent, and between a hub and any city in range."""
    if a.code == b.code or distance_km(a, b) > LONGEST_NONSTOP_KM:
        return False
    return a.continent == b.continent or a.hub or b.hub


def connections(a: City, b: City) -> list[City]:
    """The hubs a one-stop journey can connect through, the shortest detour first."""
    hubs = [hub for hub in CITIES.values() if hub.hub and nonstop(a, hub) and nonstop(hub, b)]
    return sorted(hubs, key=lambda hub: distance_km(a, hub) + distance_km(hub, b))


def dice(*question) -> random.Random:
    """A generator seeded by the question asked, so the same question gets the same answer."""
    return random.Random("|".join(str(part) for part in question))
