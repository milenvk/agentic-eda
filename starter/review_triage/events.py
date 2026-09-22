"""The application's events: a review comes in, and its triage goes out.

Each class is a contract. `@event` binds it to its type on the wire and names the field
its order is kept within: events sharing a `review_id` are delivered one at a time, in
publish order, and nothing is promised across reviews.
"""

from typing import Literal

from agentic_eda.events import EventModel, event

REVIEW_RECEIVED = "reviews.ReviewReceived"
REVIEW_TRIAGED = "reviews.ReviewTriaged"


@event(REVIEW_RECEIVED, order_per="review_id")
class ReviewReceived(EventModel):
    review_id: str
    product: str
    text: str


@event(REVIEW_TRIAGED, order_per="review_id")
class ReviewTriaged(EventModel):
    review_id: str
    sentiment: Literal["positive", "neutral", "negative"]
    summary: str
    needs_reply: bool
