"""Fakes for the Planner's tests: a model that answers on cue, and two suppliers.

No model and no simulator are involved. The fake model gives the judgement a test asks
for, so what is tested is the graph: its routing, its validator, and what it carries.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from agentic_eda.broker import EventAttributes
from itinerary_planner.graph import Brief, Judgement, LegBrief, Picks, Ranking, StayBrief
from itinerary_planner.suppliers import FlightOffer, HotelOffer
from travel_agency.events.planning import ItineraryRequested, Money

SOON = datetime.now(UTC) + timedelta(hours=2)


def usd(amount: float) -> Money:
    return Money(amount=amount, currency="USD")


def request(event_id: str = "req-1", budget: float | None = 2900, **changes) -> ItineraryRequested:
    fields = {
        "trip_id": 1,
        "origin": "New York",
        "stops": [{"city": "Lisbon", "arrive": "2026-10-01", "depart": "2026-10-04"}],
        "travellers": 2,
        "budget": usd(budget) if budget else None,
        "preferences": "quiet, walkable, we'd take a stop to save real money",
        "car_class": None,
        "attributes_": EventAttributes(
            id=event_id, type="planning.ItineraryRequested", source="RequestTripScript"
        ),
    }
    return ItineraryRequested.model_validate({**fields, **changes})


class FakeAirline:
    """Nonstop flights are dear; allowing a stop brings a cheap one into view."""

    def __init__(self) -> None:
        self.searches: list[int] = []
        self.flies_nonstop = True

    async def search(self, origin, destination, on: date, travellers, max_stops):
        self.searches.append(max_stops)
        departs = datetime(on.year, on.month, on.day, 9, tzinfo=UTC)

        def offer(name: str, stops: int, hours: int, price: float) -> FlightOffer:
            return FlightOffer(
                offer_id=f"{name}-{origin[:3]}-{destination[:3]}",
                supplier="Airline Reservation System",
                origin=origin,
                destination=destination,
                departs=departs,
                arrives=departs + timedelta(hours=hours),
                stops=stops,
                fare_conditions="changes 150 USD, no refund",
                price=usd(price),
                valid_until=SOON,
            )

        offers = []
        if self.flies_nonstop:
            offers += [offer("nonstop", 0, 7, 1400), offer("flex", 0, 7, 1600)]
        if max_stops >= 1:
            offers.append(offer("onestop", 1, 11, 700))
        return offers


class FakeHotels:
    async def availability(self, city, check_in, check_out, travellers):
        def offer(name: str, area: str, total: float, rooms: int) -> HotelOffer:
            return HotelOffer(
                offer_id=f"{name}-{city[:3]}",
                supplier="Hotel Reservation System",
                city=city,
                hotel=name,
                area=area,
                check_in=check_in,
                check_out=check_out,
                rooms_left=rooms,
                cancellation="free until 48 hours before arrival",
                total=usd(total),
                valid_until=SOON,
            )

        return [offer("Casa do Bairro", "Alfama", 600, 4), offer("Grand Avenida", "Baixa", 900, 1)]


class FakeModel:
    """Answers each prompt as a test arranged, and remembers what it was asked."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, dict]] = []
        self.briefs: list[Brief] = []  # one per attempt; the last repeats
        self.pick_first: dict[str, str] = {}  # per prompt, a word its first pick contains

    async def __call__(self, name: str, answer: type, **variables):
        self.asked.append((name, variables))
        if name == "brief":
            attempt = sum(1 for asked, _ in self.asked if asked == "brief")
            return self.briefs[min(attempt, len(self.briefs)) - 1]
        if name in ("flights", "hotels"):
            ids = [line.split('"offer_id":"')[1].split('"')[0] for line in variables["offers"].splitlines()]
            wanted = self.pick_first.get(name, "")
            return Picks(offer_ids=sorted(ids, key=lambda i: wanted not in i), reason="fits them")
        if name == "rank":
            labels = [line.split('"label":"')[1].split('"')[0] for line in variables["candidates"].splitlines()]
            return Ranking(
                judgements=[
                    Judgement(label=label, rank=rank, rationale=f"{label} suits this trip")
                    for rank, label in enumerate(reversed(labels), start=1)
                ]
            )
        raise AssertionError(f"no prompt named {name}")


def brief(max_stops: int, max_price: float | None = None) -> Brief:
    return Brief(
        legs=[LegBrief(max_stops=max_stops, max_price=max_price)] * 2,
        stays=[StayBrief(max_total=None, area_hint="quiet")],
        note="favour the saving",
    )


@pytest.fixture
def model() -> FakeModel:
    fake = FakeModel()
    fake.briefs = [brief(max_stops=1)]
    return fake


@pytest.fixture
def airline() -> FakeAirline:
    return FakeAirline()


@pytest.fixture
def hotels() -> FakeHotels:
    return FakeHotels()
