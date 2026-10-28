"""The Trip: the business state of one trip, its rules, and the operations that change it.

One class whose fields are the state and whose methods are the operations, one per business
action. Each operation checks the rules, changes the Trip in memory, and returns the one event
that says what happened; a check that fails raises `Refused`, which says why. The Trip decides,
the store writes (the activator loads the Trip before an activation and commits it after), and
the activator publishes. The class depends on the event classes and on nothing else: no store,
no broker, no framework, no LLM.
"""

import os
from datetime import date, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from travel_agency.events.booking import (
    ClarificationRequested,
    ItineraryApproved,
    ItineraryRejected,
    ProposalReady,
    TripChanged,
    TripCreated,
    TripRequested,
    TripRequestRejected,
    TripRequirements,
)
from travel_agency.events.planning import Itinerary, ItineraryProposed, ItineraryRequested, Money

# How many questions the Trip asks the customer about one proposal before it insists on a
# decision: each one costs a round trip of hours or days.
CLARIFICATION_CAP = int(os.environ.get("CLARIFICATION_CAP", "3"))

Status = Literal["new", "requested", "planning", "proposed", "awaiting clarification", "approved"]
REPLYING = ("proposed", "awaiting clarification")  # the statuses a customer's reply is read in

# The reply's operations are the LLM's tools, so their parameters say what a name cannot.
ProposalId = Annotated[str, Field(description="the id of the proposal the customer replied to")]


class Refused(Exception):
    """An operation's checks failed. The message says which, for whoever asked."""


class Proposal(BaseModel):
    """A proposal as planning published it, kept on the Trip so a reply can be read against it."""

    proposal_id: str
    itineraries: list[Itinerary]
    questions_asked: int = 0


class Question(BaseModel):
    proposal_id: str
    question: str
    options: list[str] | None


class Choice(BaseModel):
    proposal_id: str
    rank: int


class Trip(BaseModel):
    schema_version: int = 1
    trip_id: int
    status: Status = "new"
    requirements: TripRequirements | None = None
    proposals: list[Proposal] = []
    pending_question: Question | None = None
    approved: Choice | None = None

    # --- operations with no judgement in them, called by the agent's code

    def create(self, request: TripRequested) -> TripCreated | TripRequestRejected:
        """Record the request as this trip, or say what is wrong with it. No trip is created then."""
        self._allowed_in("new")
        requirements = TripRequirements.model_validate(
            request.model_dump(include=set(TripRequirements.model_fields))
        )
        problems = _problems(requirements)
        if problems:
            return TripRequestRejected(conversation_id=request.conversation_id, reason=problems)
        self.requirements, self.status = requirements, "requested"
        return TripCreated(
            trip_id=self.trip_id, conversation_id=request.conversation_id, requirements=requirements
        )

    def request_planning(self, reason: str | None = None) -> ItineraryRequested:
        """Ask planning for itineraries, with the requirements as they now stand.

        On a request made again, `reason` is why the customer sent the last proposal back,
        read off the event that sent the trip back here.
        """
        self._allowed_in("requested")
        self.status = "planning"
        return ItineraryRequested(
            trip_id=self.trip_id, reason=reason, **self.requirements.model_dump()
        )

    def record_proposal(self, proposal: ItineraryProposed) -> ProposalReady:
        """Keep planning's answer and pass the itineraries on to the customer."""
        self._allowed_in("planning")
        if proposal.trip_id != self.trip_id:
            raise Refused(f"proposal {proposal.proposal_id} is for trip {proposal.trip_id}")
        self.proposals.append(
            Proposal(proposal_id=proposal.proposal_id, itineraries=proposal.itineraries)
        )
        self.status = "proposed"
        return ProposalReady(
            trip_id=self.trip_id,
            proposal_id=proposal.proposal_id,
            itineraries=proposal.itineraries,
        )

    # --- the reply's operations, each the tool an LLM may call once it has read the reply
    # Their docstrings stay on one line each: a small LLM read a wrapped one differently.

    def approve(
        self,
        proposal_id: ProposalId,
        rank: Annotated[int, Field(description="the chosen itinerary's number in the proposal's list; 1 is the first listed")],  # fmt: skip
    ) -> ItineraryApproved:
        """The customer chose one itinerary of this proposal, named by its number or described by what sets it apart: its flight's time of day, its hotel, or its price."""
        self._allowed_in(*REPLYING)
        proposal = self._proposal(proposal_id)
        if rank not in [itinerary.rank for itinerary in proposal.itineraries]:
            raise Refused(f"proposal {proposal_id} has no itinerary ranked {rank}")
        self.approved, self.pending_question, self.status = Choice(proposal_id=proposal_id, rank=rank), None, "approved"  # fmt: skip
        return ItineraryApproved(trip_id=self.trip_id, proposal_id=proposal_id, rank=rank)

    def reject(
        self,
        proposal_id: ProposalId,
        reason: Annotated[str, Field(description="why the customer wants none of them, in the customer's words")],  # fmt: skip
    ) -> ItineraryRejected:
        """The customer wants none of this proposal's itineraries and asks for nothing different about the trip; planning will be asked again from the same requirements."""
        self._allowed_in(*REPLYING)
        self._proposal(proposal_id)
        self.pending_question, self.status = None, "requested"
        return ItineraryRejected(trip_id=self.trip_id, proposal_id=proposal_id, reason=reason)

    def change(
        self,
        reason: Annotated[str, Field(description="what the customer changed and why, in the customer's words")],  # fmt: skip
        departure_dates: Annotated[
            list[date] | None,
            Field(description="the new departure date of every journey in the requirements, one per journey in travel order, each replacing that journey's current date; a trip leaving later or earlier moves every journey by the same number of days; null leaves the dates as they are"),  # fmt: skip
        ] = None,
        budget: Annotated[Money | None, Field(description="the new budget, amount and currency; null leaves it as it is")] = None,  # fmt: skip
    ) -> TripChanged:
        """The customer keeps the trip but on other departure dates or with another budget; planning will be asked again from the changed requirements.

        Leaving later or earlier moves the whole trip, every journey by the same number of days, and the
        stays move with the journeys around them.
        """
        self._allowed_in(*REPLYING)
        requirements = self.requirements
        if departure_dates is not None:
            requirements = _moved(requirements, departure_dates)
        if budget is not None:
            requirements = requirements.model_copy(update={"budget": budget})
        problems = _problems(requirements)
        if problems:
            raise Refused(problems)
        self.requirements, self.pending_question, self.status = requirements, None, "requested"
        return TripChanged(trip_id=self.trip_id, requirements=requirements, reason=reason)

    def request_clarification(
        self,
        proposal_id: ProposalId,
        question: Annotated[str, Field(description="one short question whose answer settles it")],
        options: Annotated[
            list[str] | None,
            Field(description="the few answers that would settle it, when there are a few; null for an open question"),  # fmt: skip
        ] = None,
    ) -> ClarificationRequested:
        """The reply does not settle the decision; ask the customer, within the cap."""
        self._allowed_in(*REPLYING)
        proposal = self._proposal(proposal_id)
        if proposal.questions_asked >= CLARIFICATION_CAP:
            raise Refused(
                f"{CLARIFICATION_CAP} questions were already asked about proposal {proposal_id}: "
                f"decide on the words you have, by approving, rejecting, or changing the trip"
            )
        proposal.questions_asked += 1
        self.pending_question = Question(proposal_id=proposal_id, question=question, options=options)  # fmt: skip
        self.status = "awaiting clarification"
        return ClarificationRequested(
            trip_id=self.trip_id, proposal_id=proposal_id, question=question, options=options
        )

    # --- the checks

    def _allowed_in(self, *statuses: Status) -> None:
        if self.status not in statuses:
            raise Refused(f"trip {self.trip_id} is {self.status}, not {' or '.join(statuses)}")

    def _proposal(self, proposal_id: str) -> Proposal:
        for proposal in self.proposals:
            if proposal.proposal_id == proposal_id:
                return proposal
        known = ", ".join(p.proposal_id for p in self.proposals) or "none"
        raise Refused(f"proposal {proposal_id} is not one of trip {self.trip_id}'s: {known}")


def _problems(requirements: TripRequirements) -> str:
    """What makes the requirements no business request, as one message; empty when nothing does."""
    today = date.today()
    journeys = requirements.origin_destinations
    found = []
    if any(journey.departure_date <= today for journey in journeys):
        found.append("every journey must depart after today")
    dates = [journey.departure_date for journey in journeys]
    if dates != sorted(dates):
        found.append("the journeys must be in date order")
    if any(stay.check_in >= stay.check_out for stay in requirements.stays):
        found.append("every stay must check out after it checks in")
    if requirements.budget is not None and requirements.budget.amount <= 0:
        found.append("a budget must be more than nothing, or null for no limit")
    return "; ".join(found)


def _moved(requirements: TripRequirements, departure_dates: list[date]) -> TripRequirements:
    """The journeys on new dates, and the stays moved with the journeys around them."""
    journeys = requirements.origin_destinations
    if len(departure_dates) != len(journeys):
        raise Refused(f"the trip has {len(journeys)} journeys; give one date for each, in travel order")  # fmt: skip
    moved = [
        journey.model_copy(update={"departure_date": day})
        for journey, day in zip(journeys, departure_dates, strict=True)
    ]
    shifts = [(asked.departure_date, day - asked.departure_date) for asked, day in zip(journeys, departure_dates, strict=True)]  # fmt: skip
    stays = []
    for stay in requirements.stays:
        arriving = [by for day, by in shifts if day <= stay.check_in]
        leaving = [by for day, by in shifts if day >= stay.check_out]
        stays.append(
            stay.model_copy(
                update={
                    "check_in": stay.check_in + (arriving[-1] if arriving else timedelta(0)),
                    "check_out": stay.check_out + (leaving[0] if leaving else timedelta(0)),
                }
            )
        )
    return requirements.model_copy(update={"origin_destinations": moved, "stays": stays})
