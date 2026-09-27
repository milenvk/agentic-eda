"""The agent: one judgement per review. No broker, no envelope, and no agent framework.

A typed request comes in and a typed answer goes out. The model only judges; code carries
the facts, so the review's id is never something a model retyped.
"""

import os
from typing import Literal

import litellm
from pydantic import BaseModel, Field

from .events import ReviewReceived, ReviewTriaged

PROMPT = """You triage product reviews for a shop's support team.

Product: {product}
Review: {text}

Say whether the review is positive, neutral, or negative, summarise it in one sentence,
and say whether the customer needs a reply from a person."""


class Judgement(BaseModel):
    """The answer asked of the LLM: the triage without the review's id."""

    sentiment: Literal["positive", "neutral", "negative"]
    summary: str = Field(description="The review in one sentence.")
    needs_reply: bool = Field(description="True when a person should answer the customer.")


async def triage(review: ReviewReceived) -> ReviewTriaged:
    prompt = PROMPT.format(product=review.product, text=review.text)
    response = await litellm.acompletion(
        model=os.environ["LLM_MODEL"],
        messages=[{"role": "user", "content": prompt}],
        response_format=Judgement,
    )
    judgement = Judgement.model_validate_json(response.choices[0].message.content)
    return ReviewTriaged(review_id=review.review_id, **judgement.model_dump())
