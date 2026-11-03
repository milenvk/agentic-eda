"""Prompts are configuration: versioned files, the version chosen by `PROMPT_VERSION`.

The files are in this package, beside this module, so they are installed with it. A line
whose variables all render empty is left out, so a sentence about something the reply may
not carry, such as the question being answered, is written in the file and not in code. How the Trip
is written for the LLM is here too, beside the prompt file: the journeys numbered in travel
order, and each itinerary by what a customer would describe it by.
"""

import os
from datetime import date
from importlib import resources
from string import Formatter

from travel_agency.events.booking import CustomerReplied, TripRequirements
from travel_agency.events.planning import Itinerary

from ..trip import Trip


def render(name: str, **variables: object) -> str:
    version = os.environ.get("PROMPT_VERSION", "v1")
    prompt = resources.files(__package__).joinpath(f"{name}.{version}.md")
    lines = []
    for line in prompt.read_text(encoding="utf-8").splitlines():
        fields = [field for _, field, _, _ in Formatter().parse(line) if field]
        if fields and all(variables[field] == "" for field in fields):
            continue
        lines.append(line.format(**variables))
    return "\n".join(lines) + "\n"


def reply_prompt(trip: Trip, reply: CustomerReplied) -> str:
    """The prompt for reading one reply: the trip and the proposal it is about."""
    proposal = next((p for p in trip.proposals if p.proposal_id == reply.proposal_id), None)
    return render(
        "reply",
        requirements=_requirements(trip.requirements),
        proposal_id=reply.proposal_id,
        itineraries="\n".join(_line(i) for i in proposal.itineraries) if proposal else "none",
        question=reply.answering or "",  # no question: the line is left out
        today=date.today().isoformat(),
    )


def _requirements(requirements: TripRequirements) -> str:
    """The requirements as the LLM reads them: the journeys numbered in travel order, each with its date."""
    journeys = "\n".join(
        f"{n}. {j.origin} to {j.destination}, leaving {j.departure_date}"
        for n, j in enumerate(requirements.origin_destinations, 1)
    )
    stays = "; ".join(f"{s.city} {s.check_in} to {s.check_out}" for s in requirements.stays) or "none"
    budget = f"{requirements.budget.amount:,.0f} {requirements.budget.currency}" if requirements.budget else "none"
    return (
        f"{requirements.adults} adults, {len(requirements.children)} children, budget {budget}, "
        f"preferences: {requirements.preferences or 'none'}\nJourneys, in travel order:\n{journeys}\nStays: {stays}"
    )


def _line(itinerary: Itinerary) -> str:
    """One itinerary as the LLM reads it: what the customer would describe it by."""
    parts = []
    for item in itinerary.items:
        if item.kind == "flight":
            first, last = item.segments[0], item.segments[-1]
            when = f"{_time_of_day(first.departs.hour)} flight, {first.departs:%a %d %b %H:%M}"
            parts.append(f"{when}, {first.origin} to {last.destination}")
        else:
            parts.append(f"{item.hotel} in {item.city} {item.check_in} to {item.check_out}")
    total = itinerary.total
    return f"{itinerary.rank}. {itinerary.label}, {total.amount:,.0f} {total.currency}: {'; '.join(parts)}. {itinerary.rationale}"  # fmt: skip


def _time_of_day(hour: int) -> str:
    """The word a customer uses for a departure time."""
    return "morning" if hour < 12 else "afternoon" if hour < 17 else "evening" if hour < 21 else "night"  # fmt: skip
