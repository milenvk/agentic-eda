"""How often the live LLM reads a customer's reply into the right operation.

Each case is a reply the chapter 3 demo script sends, read against a proposal the Planner
produced in a real run (`proposals/`, captured from the audit log with the request it
answered), N times. The count of right readings per case is the measure of a prompt, a tool
description, or a model; the demo's happy path depends on every case being read right.

Run inside the component's image against the LLM named in `.env`, from the repository root:

    docker compose -f chapters/ch03/compose.tests.yaml build tests-booking-agent
    docker run --rm --env-file .env --add-host host.docker.internal:host-gateway \\
        ch03-tests-booking-agent python evals/reply_eval.py 20
"""

import asyncio
import collections
import json
import sys
from datetime import date, timedelta
from os import environ
from pathlib import Path

from google.adk.agents.run_config import RunConfig
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import InMemoryRunner
from google.genai import types

from agentic_eda.activator.core import _ACTIVATION, Activation
from booking_agent.agent import build_agent
from booking_agent.trip import Trip
from travel_agency.events.booking import CustomerReplied, TripRequested
from travel_agency.events.planning import ItineraryProposed

PROPOSALS = sorted(Path(__file__).with_name("proposals").glob("*.json"))
QUESTION = "Which itinerary did you choose?"


def trip_from(capture: dict, asked: bool) -> Trip:
    """A trip in status proposed, as the demo's was: the captured request and proposal, ids kept."""
    proposal = ItineraryProposed(**capture["proposal"])
    trip = Trip(trip_id=proposal.trip_id)
    trip.create(TripRequested(conversation_id="eval", **capture["request"]))
    trip.request_planning()
    trip.record_proposal(proposal)
    if asked:
        trip.request_clarification(proposal.proposal_id, QUESTION)
    return trip


def cases_for(capture: dict) -> list[tuple[str, bool, str]]:
    """The script's replies against one captured proposal: words, pending question, expected."""
    journeys = capture["request"]["origin_destinations"]
    a_day_later = [
        str(date.fromisoformat(j["departure_date"]) + timedelta(days=1)) for j in journeys
    ]
    itineraries = capture["proposal"]["itineraries"]
    cheapest = min(itineraries, key=lambda i: i["total"]["amount"])["rank"]
    return [
        ("Thanks, got it.", False, "ClarificationRequested"),
        (
            "Could we leave a day later? The fares on that day are too high.",
            True,
            f"TripChanged dates {a_day_later}",
        ),
        ("No, all of these are too expensive for what they offer.", False, "ItineraryRejected"),
        ("The cheapest one, please.", False, f"ItineraryApproved rank {cheapest}"),
    ]


async def read(runner: InMemoryRunner, trip: Trip, words: str) -> str:
    """One reading: the agent's reply step on this trip and these words, and what it decided."""
    proposal_id = trip.proposals[-1].proposal_id
    reply = CustomerReplied(trip_id=trip.trip_id, proposal_id=proposal_id, words=words)
    activation = Activation(event=None, request=reply, activator=None, state=trip)
    token = _ACTIVATION.set(activation)
    try:
        session = await runner.session_service.create_session(
            app_name=runner.app_name, user_id="eval"
        )
        as_sent = reply.model_dump_json(exclude={"attributes_"})
        message = types.Content(role="user", parts=[types.Part(text=as_sent)])
        async for _ in runner.run_async(
            user_id="eval",
            session_id=session.id,
            new_message=message,
            run_config=RunConfig(max_llm_calls=10),
        ):
            pass
    except Exception as error:  # noqa: BLE001  a failed reading is a result, not a reason to stop
        return f"error: {type(error).__name__}: {str(error)[:80]}"
    finally:
        _ACTIVATION.reset(token)
    answered = activation.answered
    if answered is None:
        return "no decision"
    name = type(answered).__name__
    if name == "ItineraryApproved":
        return f"{name} rank {answered.rank}"
    if name == "ClarificationRequested":
        return f"{name}: {answered.question!r}"
    if name == "TripChanged":
        dates = [str(j.departure_date) for j in answered.requirements.origin_destinations]
        return f"{name} dates {dates}"
    return name


async def main(n: int) -> None:
    agent = build_agent(LiteLlm(model=environ["LLM_MODEL"], temperature=0))
    runner = InMemoryRunner(agent=agent, app_name="eval")
    print(f"model {environ['LLM_MODEL']}, {n} readings per case", flush=True)
    right_total = total = 0
    for path in PROPOSALS:
        capture = json.loads(path.read_text())
        for words, asked, expected in cases_for(capture):
            counts: collections.Counter[str] = collections.Counter()
            for _ in range(n):
                counts[await read(runner, trip_from(capture, asked), words)] += 1
            right = sum(count for outcome, count in counts.items() if outcome.startswith(expected))
            right_total, total = right_total + right, total + n
            pending = ", a question pending" if asked else ""
            print(f"\n{right}/{n} [{path.stem}{pending}] {expected}  {words!r}", flush=True)
            for outcome, count in counts.most_common():
                print(f"    {count:2}  {outcome}", flush=True)
    print(f"\n{right_total}/{total} right", flush=True)


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 20))
