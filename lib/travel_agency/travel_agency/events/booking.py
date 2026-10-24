"""The booking context's events: a trip from the customer's request to the approved itinerary.

Whoever asks writes `TripRequested` and `CustomerReplied` in booking's language; the Booking
Agent writes every other event here, as the one writer of the Trip.
"""

from pydantic import BaseModel, Field, model_validator

from agentic_eda.contracts import EventContract, event

from ..event_types import (
    CLARIFICATION_REQUESTED,
    CUSTOMER_REPLIED,
    ITINERARY_APPROVED,
    ITINERARY_REJECTED,
    PROPOSAL_READY,
    TRIP_CHANGED,
    TRIP_CREATED,
    TRIP_REQUEST_REJECTED,
    TRIP_REQUESTED,
)
from .planning import Child, Itinerary, Money, OriginDestination, Stay

TRIP_ID = Field(description="Identifies the trip across all of its events. Assigned by the store.")
PROPOSAL_ID = Field(description="The proposal's id, as planning published it.")


class TripRequirements(BaseModel):
    """What a trip request states, in the same terms planning is asked in."""

    origin_destinations: list[OriginDestination] = Field(
        min_length=1, description="The journeys wanted, in travel order."
    )
    stays: list[Stay] = Field(description="The hotel stays wanted. Empty when none is wanted.")
    adults: int = Field(ge=1, description="Travellers of 18 or older.")
    children: list[Child] = Field(description="Every traveller under 18. Empty when there is none.")
    budget: Money | None = Field(
        description="Upper limit for the whole trip and all travellers. Null means no limit."
    )
    preferences: str = Field(description="Free text in the customer's own words.")
    car_class: str | None = Field(
        description="The class of rental car wanted. Null means no car is wanted."
    )

    @model_validator(mode="after")
    def _every_held_infant_has_an_adult(self):
        held = sum(1 for child in self.children if not child.own_seat)
        if held > self.adults:
            raise ValueError("an adult holds one infant at most")
        return self


@event(TRIP_REQUESTED, order_per="conversation_id")
class TripRequested(TripRequirements, EventContract):
    """A customer's request for a trip, written by whoever heard it. No trip exists yet."""

    conversation_id: str = Field(
        description="The customer channel's id for the exchange; the key, since there is no trip."
    )


@event(TRIP_REQUEST_REJECTED, order_per="conversation_id")
class TripRequestRejected(EventContract):
    """The request failed booking's checks; no trip was created."""

    conversation_id: str
    reason: str = Field(description="What is missing or wrong, for the customer to read.")


@event(TRIP_CREATED, order_per="trip_id")
class TripCreated(EventContract):
    """The request passed booking's checks and is now a trip, under the store's id."""

    trip_id: int = TRIP_ID
    conversation_id: str
    requirements: TripRequirements = Field(description="The accepted request.")


@event(PROPOSAL_READY, order_per="trip_id")
class ProposalReady(EventContract):
    """Itineraries for the customer to choose from."""

    trip_id: int = TRIP_ID
    proposal_id: str = PROPOSAL_ID
    itineraries: list[Itinerary] = Field(min_length=1, description="Best first.")


@event(CUSTOMER_REPLIED, order_per="trip_id")
class CustomerReplied(EventContract):
    """What the customer said about a proposal, in their own words. Booking reads it."""

    trip_id: int = TRIP_ID
    proposal_id: str = Field(description="The proposal the customer is replying to.")
    words: str = Field(description="The reply as the customer wrote it.")


@event(ITINERARY_APPROVED, order_per="trip_id")
class ItineraryApproved(EventContract):
    """The customer chose one itinerary."""

    trip_id: int = TRIP_ID
    proposal_id: str = PROPOSAL_ID
    rank: int = Field(ge=1, description="The chosen itinerary's rank in the proposal.")


@event(ITINERARY_REJECTED, order_per="trip_id")
class ItineraryRejected(EventContract):
    """The customer wants none of the proposal's itineraries; planning is asked again."""

    trip_id: int = TRIP_ID
    proposal_id: str = PROPOSAL_ID
    reason: str = Field(description="Why, in the customer's words.")


@event(TRIP_CHANGED, order_per="trip_id")
class TripChanged(EventContract):
    """The customer changed what they want; planning is asked again."""

    trip_id: int = TRIP_ID
    requirements: TripRequirements = Field(description="The requirements as they now stand.")
    reason: str = Field(description="What changed and why, in the customer's words.")


@event(CLARIFICATION_REQUESTED, order_per="trip_id")
class ClarificationRequested(EventContract):
    """The reply did not settle the decision; a question goes back to the customer."""

    trip_id: int = TRIP_ID
    proposal_id: str = PROPOSAL_ID
    question: str = Field(description="What booking needs to know, for the customer to read.")
    options: list[str] | None = Field(
        description="The answers that would settle it, when there are a few. Null otherwise."
    )
