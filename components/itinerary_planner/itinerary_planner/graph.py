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
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from agentic_eda.hydration import Hydration
from travel_agency.events.planning import (
    FlightItem,
    Itinerary,
    ItineraryProposed,
    ItineraryRequested,
    Money,
    Offer,
    StayItem,
)

from .suppliers import Airline, FlightOffer, HotelOffer, Hotels

MAX_ATTEMPTS = 3
PICKS = 3

Ask = Callable[..., Awaitable[BaseModel]]


class JourneyBrief(BaseModel):
    """The limits for the flight search of one journey."""

    max_stops: int = Field(description="0 means nonstop flights only.")
    max_price: float | None = Field(
        description="Upper limit for one offer, all travellers together. Null means no limit."
    )


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
    brief: Brief | None = None
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
            journeys=len(request.origin_destinations),
            stays=len(request.stays),
            problems="\n".join(state.problems) or "none yet",
        )
        return {**_fresh(state), "brief": brief, "attempts": state.attempts + 1, "problems": []}

    async def flight_search(state: PlannerState) -> dict:
        request, kept = state.request, []
        party = (request.adults, request.children)
        for number, journey in enumerate(request.origin_destinations):
            wanted = _at(state.brief.journeys, number) or JourneyBrief(max_stops=1, max_price=None)
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
        for number, stay in enumerate(request.stays):
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
