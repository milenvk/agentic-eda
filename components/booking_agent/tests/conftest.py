"""Fixtures for the Booking Agent's tests: the running example as a request, a proposal
answering it, and a scripted LLM. No model, no broker, and no database are involved."""

from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime, timedelta

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from travel_agency.events.booking import TripRequested, TripRequirements
from travel_agency.events.planning import (
    FlightItem,
    FlightSegment,
    Itinerary,
    ItineraryProposed,
    Money,
    OriginDestination,
    Stay,
    StayItem,
)

NEXT_YEAR = date.today().year + 1


def usd(amount: float) -> Money:
    return Money(amount=amount, currency="USD")


def requirements(**changes) -> TripRequirements:
    """New York to Lisbon for two, with three days in Madrid on the way."""
    fields = {
        "origin_destinations": [
            OriginDestination(origin="NYC", destination="MAD", departure_date=date(NEXT_YEAR, 5, 10)),
            OriginDestination(origin="MAD", destination="LIS", departure_date=date(NEXT_YEAR, 5, 13)),
            OriginDestination(origin="LIS", destination="NYC", departure_date=date(NEXT_YEAR, 5, 17)),
        ],
        "stays": [
            Stay(city="MAD", check_in=date(NEXT_YEAR, 5, 10), check_out=date(NEXT_YEAR, 5, 13), rooms=1),
            Stay(city="LIS", check_in=date(NEXT_YEAR, 5, 13), check_out=date(NEXT_YEAR, 5, 17), rooms=1),
        ],
        "adults": 2,
        "children": [],
        "budget": usd(3500),
        "preferences": "Quiet, walkable neighbourhoods.",
        "car_class": None,
    }  # fmt: skip
    return TripRequirements(**{**fields, **changes})


def trip_request(conversation_id: str = "conv-1", **changes) -> TripRequested:
    return TripRequested(conversation_id=conversation_id, **requirements(**changes).model_dump())


def itinerary(rank: int, label: str, departs_at: int, total: float) -> Itinerary:
    """One itinerary with one flight and one stay, enough to describe it by."""
    departs = datetime(NEXT_YEAR, 5, 10, departs_at, tzinfo=UTC)
    flight = FlightSegment(
        carrier="WW", number="101", origin="JFK", destination="MAD", departs=departs, arrives=departs + timedelta(hours=7)
    )  # fmt: skip
    stay = StayItem(
        kind="stay", city="MAD", hotel="Casa Verde", rooms=1, room="double",
        check_in=date(NEXT_YEAR, 5, 10), check_out=date(NEXT_YEAR, 5, 13),
        rate_plan="FLEXIBLE", cancellation="free until 48 hours before arrival", offer=None, backup=None,
    )  # fmt: skip
    return Itinerary(
        rank=rank,
        label=label,
        rationale=f"{label} suits this trip",
        items=[FlightItem(kind="flight", segments=[flight], fare_conditions="no refund", offer=None), stay],  # fmt: skip
        total=usd(total),
    )


def proposal(trip_id: int, proposal_id: str = "p-1") -> ItineraryProposed:
    return ItineraryProposed(
        trip_id=trip_id,
        proposal_id=proposal_id,
        itineraries=[
            itinerary(1, "best value", departs_at=9, total=3100),  # the morning flight
            itinerary(2, "cheapest", departs_at=22, total=2650),
            itinerary(3, "fastest", departs_at=18, total=3400),
        ],
    )


class FakeLlm(BaseLlm):
    """A scripted LLM: one answer per call, in order, the last one repeating.

    Each answer is a list of parts: a tool call the LLM makes, or the text it ends with.
    """

    script: list[list[types.Part]] = []
    requests: list[LlmRequest] = []
    model: str = "fake"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.requests.append(llm_request)
        parts = self.script[min(len(self.requests), len(self.script)) - 1]
        yield LlmResponse(content=types.Content(role="model", parts=parts))


def calls(name: str, **args) -> list[types.Part]:
    return [types.Part(function_call=types.FunctionCall(name=name, args=args))]


def says(text: str) -> list[types.Part]:
    return [types.Part(text=text)]


@pytest.fixture
def llm() -> FakeLlm:
    return FakeLlm(script=[says("Done.")], requests=[])
