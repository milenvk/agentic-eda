"""The application's events: a review comes in, and its triage goes out.

Each class is a contract. `@event` binds it to its type on the wire and names the field
its order is kept within: events sharing a `review_id` are delivered one at a time, in
publish order, and nothing is promised across reviews.
"""

from typing import Literal

from pydantic import Field

from agentic_eda.contracts import EventContract, event

REVIEW_RECEIVED = "reviews.ReviewReceived"
REVIEW_TRIAGED = "reviews.ReviewTriaged"


@event(REVIEW_RECEIVED, order_per="review_id")
class ReviewReceived(EventContract):
    """A customer wrote a review of a product."""

    review_id: str = Field(description="Identifies the review across all of its events.")
    product: str = Field(description="The product's name as the shop lists it.")
    text: str = Field(description="The review in the customer's own words.")


@event(REVIEW_TRIAGED, order_per="review_id")
class ReviewTriaged(EventContract):
    """The support team's first reading of one review."""

    review_id: str = Field(description="Identifies the review across all of its events.")
    sentiment: Literal["positive", "neutral", "negative"]
    summary: str = Field(description="The review in one sentence.")
    needs_reply: bool = Field(description="True when a person should answer the customer.")
