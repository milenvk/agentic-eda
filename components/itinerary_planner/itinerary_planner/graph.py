"""The Itinerary Planner's graph: two searches that constrain each other, settled together.

A planner node briefs a flight search and a hotel search, which run side by side. A join
consolidates what they found into candidate itineraries, and a validator checks the hard
constraints in code, never with a model. The validator always hands back to the planner:
with problems, it briefs the searches again; without, it ranks what survived and proposes.

A journey may have a window of dates. A hotel's price depends on its nights, so the dates
are settled before either search starts: the planner reads the lowest fare on each date of
a window, and its brief names the date to search.

The model only ever judges among options that code has already fetched, and code carries
the facts, so an offer's price or a flight's time is never something a model retyped.
"""

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from agentic_eda.contracts import data_of
from agentic_eda.hydration import Hydration
from travel_agency.events.planning import (
    FlightItem,
    Itinerary,
    ItineraryProposed,
    ItineraryRequested,
    Money,
    Offer,
    OriginDestination,
    Stay,
    StayItem,
)

from .suppliers import Airline, FlightOffer, HotelOffer, Hotels

MAX_ATTEMPTS = 3
PICKS = 3

Ask = Callable[..., Awaitable[BaseModel]]
NOT_MOVED = timedelta(0)


class JourneyBrief(BaseModel):
    """The limits for the flight search of one journey."""

    departure_date: date | None = Field(
        description="One of the dates the journey may start on. Null keeps the requested date."
    )
    max_stops: int = Field(description="0 means nonstop flights only.")
    max_price: float | None = Field(
        description="Upper limit for one offer, all travellers together. Null means no limit."
    )


NO_LIMITS = JourneyBrief(departure_date=None, max_stops=1, max_price=None)


class StayBrief(BaseModel):
    """The limits for the hotel search of one stay."""

    max_total: float | None = Field(
        description="Upper limit for the whole stay, all travellers together. Null means no limit."
    )
    area_hint: str | None = Field(
        description="The kind of area to look in. Null when the preferences suggest none."
    )


class Brief(BaseModel):
    """What the planner asks of the two searches, one entry per journey and per stay."""

    journeys: list[JourneyBrief] = Field(description="One entry per journey, in travel order.")
    stays: list[StayBrief] = Field(description="One entry per hotel stay, in travel order.")
    note: str = Field(description="One sentence on what the searches should favour.")


class Picks(BaseModel):
    """A search's judgement: which offers to keep, best first, and why."""

    offer_ids: list[str] = Field(description="Copied exactly from the offers, best first.")
    reason: str = Field(description="One sentence on why the first offer is first.")


class Judgement(BaseModel):
    """The planner's verdict on one candidate itinerary."""

    label: str = Field(description="The judged itinerary's label, copied exactly.")
    rank: int = Field(description="1 is the itinerary to recommend first.")
    rationale: str = Field(
        description="One or two sentences for the customer on the trade against the others."
    )


class Ranking(BaseModel):
    """One judgement per candidate itinerary."""

    judgements: list[Judgement]


class PlannerState(BaseModel):
    request: ItineraryRequested
    handling: str = ""  # the request event this run is for
    context: str = ""
    fares: str = ""  # the lowest fare on each date of each window, as the planner reads it
    brief: Brief | None = None
    journeys: list[OriginDestination] = []  # each on the one date the brief settled
    stays: list[Stay] = []  # moved with the journeys around them
    flights: list[list[FlightOffer]] = []  # per journey, the search's picks, best first
    hotels: list[list[HotelOffer]] = []  # per stay
    candidates: list[Itinerary] = []
    problems: list[str] = []
    attempts: int = 0
    proposal: ItineraryProposed | None = None


def build_graph(*, ask: Ask, airline: Airline, hotels: Hotels, hydration: Hydration):
    async def planner(state: PlannerState) -> dict:
        request = state.request
        event_id = request.attributes_.id if request.attributes_ else str(request.trip_id)
        if state.handling != event_id:
            # A thread is kept per trip, so a new request starts from a clean slate.
            state = PlannerState(request=request, handling=event_id)
            state.context = await hydration.context_for(str(request.trip_id))
            state.fares = await _fare_calendar(airline, request)

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
            fares=state.fares or "no journey has a window",
            journeys=len(request.origin_destinations),
            stays=len(request.stays),
            problems="\n".join(state.problems) or "none yet",
        )
        journeys, stays = _settled(request, brief)
        return {
            **_fresh(state),
            "brief": brief,
            "journeys": journeys,
            "stays": stays,
            "attempts": state.attempts + 1,
            "problems": [],
        }

    async def flight_search(state: PlannerState) -> dict:
        request, kept = state.request, []
        party = (request.adults, request.children)
        for number, journey in enumerate(state.journeys):
            wanted = _at(state.brief.journeys, number) or NO_LIMITS
            offers = await airline.search(journey, *party, wanted.max_stops)
            if not offers and wanted.max_stops == 0:
                # The brief wanted a nonstop on a route nobody flies nonstop.
                offers = await airline.search(journey, *party, 1)
            if wanted.max_price is not None:
                offers = [o for o in offers if o.price.amount <= wanted.max_price] or offers
            kept.append(
                await _picked(ask, "flights", request, journey, offers, note=state.brief.note)
            )
        return {"flights": kept}

    async def hotel_search(state: PlannerState) -> dict:
        request, kept = state.request, []
        for number, stay in enumerate(state.stays):
            wanted = _at(state.brief.stays, number) or StayBrief(max_total=None, area_hint=None)
            offers = await hotels.availability(stay, request.adults, request.children)
            if wanted.max_total is not None:
                offers = [o for o in offers if o.total.amount <= wanted.max_total] or offers
            kept.append(
                await _picked(
                    ask,
                    "hotels",
                    request,
                    stay,
                    offers,
                    note=state.brief.note,
                    area_hint=wanted.area_hint or "no particular area",
                )
            )
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


async def _fare_calendar(airline: Airline, request: ItineraryRequested) -> str:
    """The lowest fare on each date of every window, which the industry calls calendar shopping."""
    lines = []
    for journey in request.origin_destinations:
        for day in _window(journey):
            offers = await airline.search(_on(journey, day), request.adults, request.children, 1)
            if offers:
                lowest = min(offers, key=_price).price
                route = f"{journey.origin} to {journey.destination}"
                lines.append(f"{route} on {day}: from {lowest.amount:,.0f} {lowest.currency}")
    return "\n".join(lines)


def _window(journey: OriginDestination) -> list[date]:
    """Every date the journey may start on, or none where it has no window."""
    before, after = journey.days_before or 0, journey.days_after or 0
    if not (before or after):
        return []
    first = journey.departure_date - timedelta(days=before)
    return [first + timedelta(days=n) for n in range(before + after + 1)]


def _on(journey: OriginDestination, day: date) -> OriginDestination:
    exactly = {"departure_date": day, "days_before": None, "days_after": None}
    return journey.model_copy(update=exactly)


def _settled(
    request: ItineraryRequested, brief: Brief
) -> tuple[list[OriginDestination], list[Stay]]:
    """The journeys on the dates the brief chose, and the stays moved with them."""
    requested = request.origin_destinations
    journeys = []
    for number, journey in enumerate(requested):
        day = (_at(brief.journeys, number) or NO_LIMITS).departure_date
        if day not in _window(journey):
            day = journey.departure_date  # a date outside the window is never searched
        journeys.append(_on(journey, day))
    stays = [_following(stay, requested, journeys) for stay in request.stays]

    days = [journey.departure_date for journey in journeys]
    if days == sorted(days) and all(stay.check_in < stay.check_out for stay in stays):
        return journeys, stays
    # The chosen dates leave a stay without a night: the requested dates need no judgement.
    return [_on(journey, journey.departure_date) for journey in requested], request.stays


def _following(stay: Stay, requested: list, settled: list) -> Stay:
    """A stay begins with the journey before it and ends with the journey after it."""
    moved = [
        (asked.departure_date, chosen.departure_date - asked.departure_date)
        for asked, chosen in zip(requested, settled, strict=True)
    ]
    arriving = [by for day, by in moved if day <= stay.check_in]
    leaving = [by for day, by in moved if day >= stay.check_out]
    return stay.model_copy(
        update={
            "check_in": stay.check_in + (arriving[-1] if arriving else NOT_MOVED),
            "check_out": stay.check_out + (leaving[0] if leaving else NOT_MOVED),
        }
    )


async def _picked(ask: Ask, prompt: str, request, subject, offers: list, **brief: str) -> list:
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
        **brief,  # the planner's words for this search
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

    # Per label, how a flight is chosen for each journey and a hotel for each stay.
    choices = {
        "cheapest": (cheapest, cheapest),
        "fastest": (fastest, cheapest),
        "best value": (first_pick, first_pick),
    }
    candidates, seen = [], set()
    for label, (choose_flight, choose_hotel) in choices.items():
        flown = [choose_flight(offers) for offers in flights]
        stays = [choose_hotel(offers) for offers in hotels]
        chosen = tuple(o.offer_id for o in (*flown, *stays))
        if chosen in seen:
            continue
        seen.add(chosen)
        candidates.append(_itinerary(label, request, flown, stays))
    return candidates


def _itinerary(
    label: str, request, flown: list[FlightOffer], stays: list[HotelOffer]
) -> Itinerary:
    items = [
        FlightItem(
            kind="flight",
            segments=flight.segments,
            fare_conditions=flight.fare_conditions,
            offer=_offer(flight, flight.price),
        )
        for flight in flown
    ] + [
        StayItem(
            kind="stay",
            city=stay.city,
            hotel=stay.hotel,
            rooms=stay.rooms,
            room=stay.room,
            check_in=stay.check_in,
            check_out=stay.check_out,
            rate_plan=stay.rate_plan,
            cancellation=stay.cancellation,
            offer=_offer(stay, stay.total),
            backup=None,
        )
        for stay in stays
    ]
    currency = (request.budget or flown[0].price).currency
    total = sum(o.price.amount for o in flown) + sum(o.total.amount for o in stays)
    return Itinerary(
        rank=1,
        label=label,
        rationale="",
        items=sorted(items, key=_start),
        total=Money(amount=total, currency=currency),
    )


def _start(item: FlightItem | StayItem) -> tuple[date, int]:
    """Travel order: by day, and a flight before the stay beginning on its day."""
    if item.kind == "flight":
        return item.segments[0].departs.date(), 0
    return item.check_in, 1


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
        leaving = later.segments[0]
        if leaving.departs <= earlier.segments[-1].arrives:
            problems.append(f"{candidate.label}: leaves {leaving.origin} before arriving there")
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
        proposal_id=str(uuid4()),
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
    kept = {"handling": state.handling, "context": state.context, "fares": state.fares}
    return {**kept, "proposal": None}


def _offer(supplied, price: Money) -> Offer:
    return Offer(
        supplier=supplied.supplier,
        offer_id=supplied.offer_id,
        price=price,
        valid_until=supplied.valid_until,
    )


def _described(request: ItineraryRequested) -> str:
    return json.dumps(data_of(request))  # as it was published


def _listed(candidates: list[Itinerary]) -> str:
    return "\n".join(c.model_dump_json(exclude={"rank", "rationale"}) for c in candidates)


def _price(offer) -> float:
    return (offer.price if hasattr(offer, "price") else offer.total).amount


def _duration(offer: FlightOffer) -> float:
    return (offer.arrives - offer.departs).total_seconds()


def _at(items: list, number: int):
    return items[number] if number < len(items) else None
