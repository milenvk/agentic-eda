"""The agent is a plain function, so its test needs no broker, no activator, and no model."""

from types import SimpleNamespace

import litellm

from review_triage.agent import triage
from review_triage.events import ReviewReceived


async def test_the_model_judges_and_code_carries_the_facts(monkeypatch):
    asked = {}

    async def a_model(**request):
        asked.update(request)
        answer = '{"sentiment": "negative", "summary": "A shoe split.", "needs_reply": true}'
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=answer))])

    monkeypatch.setenv("LLM_MODEL", "a-model")
    monkeypatch.setattr(litellm, "acompletion", a_model)
    review = ReviewReceived(review_id="review-1", product="Trail Runner 2", text="It split.")

    triaged = await triage(review)

    assert "It split." in asked["messages"][0]["content"]
    assert (triaged.sentiment, triaged.needs_reply) == ("negative", True)
    assert triaged.review_id == "review-1"  # carried by code, never retyped by the model
