"""The airline's schedule and fares, generated from the world for any date.

Nothing is stored: a search rolls dice seeded by its route and date, so the same search
finds the same flights at the same prices on every run.
"""

from datetime import UTC, date, datetime, timedelta
from random import Random

from travel_agency.sims import world
from travel_agency.sims.world import City

from .wire import Endpoint, FareRule, FlightOffer, Itinerary, Price, Segment

CARRIER = "WW"  # the simulator's one invented airline
CRUISE_KMH = 800
BASE_FARE, FARE_PER_KM = 50, 0.09
ONE_STOP_DISCOUNT = 0.7  # a stop is the cheaper way to fly
CONNECTIONS_OFFERED = 2
OFFER_MINUTES = 30

# Each nonstop route is flown twice a day, and connecting journeys leave at midday.
MORNING, MIDDAY, EVENING = 8, 11, 17

# Per branded fare: its markup, then what a change and a refund are charged.
BRANDED_FARES = {
    "BASIC": (
        1.0,
        [
            FareRule(category="EXCHANGE", max_penalty_amount=150),
            FareRule(category="REFUND", not_applicable=True),
        ],
    ),
    "FLEX": (
        1.35,
        [
            FareRule(category="EXCHANGE", max_penalty_amount=0),
            FareRule(category="REFUND", max_penalty_amount=100),
        ],
    ),
}


def search(
    origin: City, destination: City, on: date, adults: int, non_stop: bool
) -> list[FlightOffer]:
    """The day's offers: every way to fly, under each branded fare."""
    roll = world.dice("flights", origin.code, destination.code, on)
    demand = roll.uniform(0.85, 1.25)  # how full the day is
    fare = (BASE_FARE + FARE_PER_KM * world.distance_km(origin, destination)) * demand * adults
    expires_at = datetime.now(UTC) + timedelta(minutes=OFFER_MINUTES)

    offers = []
    for segments in _journeys(roll, origin, destination, on, non_stop):
        discount = ONE_STOP_DISCOUNT if len(segments) > 1 else 1.0
        flown = "+".join(segment.carrier_code + segment.number for segment in segments)
        for brand, (markup, rules) in BRANDED_FARES.items():
            offers.append(
                FlightOffer(
                    id=f"{flown}-{on:%Y%m%d}-{brand}-{adults}",
                    itineraries=[Itinerary(segments=segments)],
                    price=Price(currency=world.CURRENCY, total=round(fare * discount * markup, 2)),
                    branded_fare=brand,
                    fare_rules=rules,
                    expires_at=expires_at,
                )
            )
    return offers


def _journeys(
    roll: Random, origin: City, destination: City, on: date, non_stop: bool
) -> list[list[Segment]]:
    journeys = []
    if world.nonstop(origin, destination):
        for slot, hour in ((1, MORNING), (2, EVENING)):
            start, end = roll.choice(origin.airports), roll.choice(destination.airports)
            journeys.append([_flight(origin, start, destination, end, _time(roll, on, hour), slot)])
    if not non_stop:
        for hub in world.connections(origin, destination)[:CONNECTIONS_OFFERED]:
            start, end = roll.choice(origin.airports), roll.choice(destination.airports)
            transfer = hub.airports[0]  # a connection never changes airports
            first = _flight(origin, start, hub, transfer, _time(roll, on, MIDDAY), slot=3)
            layover = timedelta(minutes=roll.choice((90, 120, 180)))
            onward = _flight(hub, transfer, destination, end, first.arrival.at + layover, slot=3)
            journeys.append([first, onward])
    return journeys


def _flight(
    a: City, a_airport: str, b: City, b_airport: str, departs: datetime, slot: int
) -> Segment:
    minutes = 30 + world.distance_km(a, b) / CRUISE_KMH * 60
    # A route keeps its flight number from day to day, as a real one does.
    route = world.dice("route", a.code, b.code).randint(10, 99)
    return Segment(
        departure=Endpoint(iata_code=a_airport, at=departs),
        arrival=Endpoint(iata_code=b_airport, at=departs + timedelta(minutes=round(minutes))),
        carrier_code=CARRIER,
        number=f"{route}{slot}",
    )


def _time(roll: Random, on: date, hour: int) -> datetime:
    return datetime(on.year, on.month, on.day, hour, roll.choice((0, 15, 30, 45)), tzinfo=UTC)
