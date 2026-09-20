"""The Itinerary Planner's graph: two searches that constrain each other, settled together.

A planner node briefs a flight search and a hotel search, which run side by side. A join
consolidates what they found into candidate itineraries, and a validator checks the hard
constraints in code, never with a model. The validator always hands back to the planner:
with problems, it briefs the searches again; without, it ranks what survived and proposes.

The model only ever judges among options that code has already fetched, and code carries
the facts, so an offer's price or a flight's time is never something a model retyped.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from travel_agency.events.planning import (
    FlightItem,
    Itinerary,
    ItineraryProposed,
    ItineraryRequested,
    Money,
    Offer,
    StayItem,
)
from travel_agency.hydration import Hydration

from .suppliers import Airline, FlightOffer, HotelOffer, Hotels

MAX_ATTEMPTS = 3
PICKS = 3

Ask = Callable[..., Awaitable[BaseModel]]


class Leg(BaseModel):
    origin: str
    destination: str
    on: date


class LegBrief(BaseModel):
    max_stops: int
    max_price: float | None


class StayBrief(BaseModel):
    max_total: float | None
    area_hint: str | None


class Brief(BaseModel):
    """What the planner asks of the two searches, one entry per leg and per stop."""

    legs: list[LegBrief]
    stays: list[StayBrief]
    note: str


class Picks(BaseModel):
    """A search's judgement: which offers to keep, best first, and why."""

    offer_ids: list[str]
    reason: str


class Judgement(BaseModel):
    label: str
    rank: int
    rationale: str


class Ranking(BaseModel):
    judgements: list[Judgement]


class PlannerState(BaseModel):
    request: ItineraryRequested
    handling: str = ""  # the request event this run is for
    context: str = ""
    brief: Brief | None = None
    flights: list[list[FlightOffer]] = []  # per leg, the search's picks, best first
    hotels: list[list[HotelOffer]] = []  # per stop
    candidates: list[Itinerary] = []
    problems: list[str] = []
    attempts: int = 0
    proposal: ItineraryProposed | None = None


def legs_of(request: ItineraryRequested) -> list[Leg]:
    """Out to the first stop, on between stops, and home from the last."""
    places = [request.origin, *(stop.city for stop in request.stops), request.origin]
    days = [request.stops[0].arrive, *(stop.depart for stop in request.stops)]
    return [
        Leg(origin=a, destination=b, on=day)
        for a, b, day in zip(places[:-1], places[1:], days, strict=True)
    ]


def build_graph(*, ask: Ask, airline: Airline, hotels: Hotels, hydration: Hydration):
    async def planner(state: PlannerState) -> dict:
        request = state.request
        event_id = request.attributes_.id if request.attributes_ else request.trip_id
        if state.handling != event_id:
            # A thread is kept per trip, so a new request starts from a clean slate.
            state = PlannerState(request=request, handling=event_id)
            state.context = await hydration.context_for(request.trip_id)

        if state.candidates and not state.problems:
            ranking = await ask(
                "rank", Ranking, request=_described(request), candidates=_listed(state.candidates)
            )
            return {**_fresh(state), "proposal": _proposal(request, state.candidates, ranking)}

        brief = await ask(
            "brief",
            Brief,
            request=_described(request),
            context=state.context,
            legs=len(legs_of(request)),
            stops=len(request.stops),
            problems="\n".join(state.problems) or "none yet",
        )
        return {**_fresh(state), "brief": brief, "attempts": state.attempts + 1, "problems": []}

    async def flight_search(state: PlannerState) -> dict:
        kept = []
        for number, leg in enumerate(legs_of(state.request)):
            wanted = _at(state.brief.legs, number) or LegBrief(max_stops=1, max_price=None)
            asked = (leg.origin, leg.destination, leg.on, state.request.travellers)
            offers = await airline.search(*asked, wanted.max_stops)
            if not offers and wanted.max_stops == 0:
                # The brief wanted a nonstop on a route nobody flies nonstop.
                offers = await airline.search(*asked, 1)
            if wanted.max_price is not None:
                offers = [o for o in offers if o.price.amount <= wanted.max_price] or offers
            kept.append(await _picked(ask, "flights", state.request, leg, offers))
        return {"flights": kept}

    async def hotel_search(state: PlannerState) -> dict:
        kept = []
        for number, stop in enumerate(state.request.stops):
            wanted = _at(state.brief.stays, number) or StayBrief(max_total=None, area_hint=None)
            offers = await hotels.availability(
                stop.city, stop.arrive, stop.depart, state.request.travellers
            )
            if wanted.max_total is not None:
                offers = [o for o in offers if o.total.amount <= wanted.max_total] or offers
            kept.append(await _picked(ask, "hotels", state.request, stop, offers))
        return {"hotels": kept}

    def join(state: PlannerState) -> dict:
        return {"candidates": _candidates(state.request, state.flights, state.hotels)}

    def validator(state: PlannerState) -> dict:
        valid, problems = [], []
        for candidate in state.candidates:
            found = _broken_constraints(state.request, candidate)
            (problems.extend if found else valid.append)(found or candidate)
        if valid or state.attempts >= MAX_ATTEMPTS:
            # Out of attempts, the planner proposes the nearest it found and says so.
            return {"candidates": valid or state.candidates, "problems": []}
        return {"candidates": [], "problems": problems}

    def after_planning(state: PlannerState):
        return END if state.proposal else ["flight_search", "hotel_search"]

    return (
        StateGraph(PlannerState)
        .add_node("planner", planner)
        .add_node("flight_search", flight_search)
        .add_node("hotel_search", hotel_search)
        .add_node("join", join)
        .add_node("validator", validator)
        .add_edge(START, "planner")
        .add_conditional_edges("planner", after_planning, ["flight_search", "hotel_search", END])
        .add_edge(["flight_search", "hotel_search"], "join")
        .add_edge("join", "validator")
        .add_edge("validator", "planner")
        .compile(checkpointer=InMemorySaver())
    )


async def _picked(ask: Ask, prompt: str, request, subject, offers: list) -> list:
    """The search's judgement over what the supplier offered, never beyond it."""
    if not offers:
        raise LookupError(f"no supplier offers anything for {subject}")
    picks = await ask(
        prompt,
        Picks,
        preferences=request.preferences,
        subject=subject.model_dump_json(),
        offers="\n".join(o.model_dump_json() for o in offers),
        keep=PICKS,
    )
    by_id = {offer.offer_id: offer for offer in offers}
    kept = [by_id[i] for i in dict.fromkeys(picks.offer_ids) if i in by_id][:PICKS]
    # A model may name an offer nobody made: fall back to price, which needs no judgement.
    return kept or sorted(offers, key=_price)[:PICKS]


def _candidates(request, flights, hotels) -> list[Itinerary]:
    def cheapest(offers):
        return min(offers, key=_price)

    def fastest(offers):
        return min(offers, key=_duration)

    def first_pick(offers):
        return offers[0]  # the searches put their best judgement first

    # Per label, how a flight is chosen for each leg and a hotel for each stop.
    choices = {
        "cheapest": (cheapest, cheapest),
        "fastest": (fastest, cheapest),
        "best value": (first_pick, first_pick),
    }
    candidates, seen = [], set()
    for label, (choose_flight, choose_hotel) in choices.items():
        legs = [choose_flight(offers) for offers in flights]
        stays = [choose_hotel(offers) for offers in hotels]
        chosen = tuple(o.offer_id for o in (*legs, *stays))
        if chosen in seen:
            continue
        seen.add(chosen)
        candidates.append(_itinerary(label, request, legs, stays))
    return candidates


def _itinerary(label: str, request, legs: list[FlightOffer], stays: list[HotelOffer]) -> Itinerary:
    items: list[FlightItem | StayItem] = []
    for number, flight in enumerate(legs):
        items.append(
            FlightItem(
                kind="flight",
                origin=flight.origin,
                destination=flight.destination,
                departs=flight.departs,
                arrives=flight.arrives,
                fare_conditions=flight.fare_conditions,
                offer=_offer(flight, flight.price),
            )
        )
        if number < len(stays):
            stay = stays[number]
            items.append(
                StayItem(
                    kind="stay",
                    city=stay.city,
                    hotel=stay.hotel,
                    check_in=stay.check_in,
                    check_out=stay.check_out,
                    cancellation=stay.cancellation,
                    offer=_offer(stay, stay.total),
                )
            )
    currency = (request.budget or legs[0].price).currency
    total = sum(o.price.amount for o in legs) + sum(o.total.amount for o in stays)
    return Itinerary(
        rank=1, label=label, rationale="", items=items, total=Money(amount=total, currency=currency)
    )


def _broken_constraints(request: ItineraryRequested, candidate: Itinerary) -> list[str]:
    problems = []
    budget = request.budget
    if budget and candidate.total.amount > budget.amount:
        over = candidate.total.amount - budget.amount
        problems.append(
            f"{candidate.label}: {candidate.total.amount:,.0f} {budget.currency} is "
            f"{over:,.0f} over the {budget.amount:,.0f} budget"
        )
    flights = [item for item in candidate.items if item.kind == "flight"]
    for earlier, later in zip(flights, flights[1:], strict=False):
        if later.departs <= earlier.arrives:
            problems.append(f"{candidate.label}: leaves {later.origin} before arriving there")
    now = datetime.now(UTC)
    for item in candidate.items:
        if item.offer and item.offer.valid_until <= now:
            problems.append(f"{candidate.label}: the offer {item.offer.offer_id} has expired")
    return problems


def _proposal(request, candidates: list[Itinerary], ranking: Ranking) -> ItineraryProposed:
    judged = {j.label: j for j in ranking.judgements}
    ordered = sorted(candidates, key=lambda c: judged[c.label].rank if c.label in judged else 99)
    return ItineraryProposed(
        trip_id=request.trip_id,
        itineraries=[
            candidate.model_copy(
                update={
                    "rank": rank,
                    "rationale": judged[candidate.label].rationale
                    if candidate.label in judged
                    else "the planner gave no reason for this one",
                }
            )
            for rank, candidate in enumerate(ordered, start=1)
        ],
    )


def _fresh(state: PlannerState) -> dict:
    return {"handling": state.handling, "context": state.context, "proposal": None}


def _offer(supplied, price: Money) -> Offer:
    return Offer(
        supplier=supplied.supplier,
        offer_id=supplied.offer_id,
        price=price,
        valid_until=supplied.valid_until,
    )


def _described(request: ItineraryRequested) -> str:
    return request.model_dump_json(exclude={"attributes_", "event_type"})


def _listed(candidates: list[Itinerary]) -> str:
    return "\n".join(c.model_dump_json(exclude={"rank", "rationale"}) for c in candidates)


def _price(offer) -> float:
    return (offer.price if hasattr(offer, "price") else offer.total).amount


def _duration(offer: FlightOffer) -> float:
    return (offer.arrives - offer.departs).total_seconds()


def _at(items: list, number: int):
    return items[number] if number < len(items) else None
