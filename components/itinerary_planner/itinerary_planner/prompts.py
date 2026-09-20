"""Prompts are configuration: versioned files, the version chosen by `PROMPT_VERSION`."""

import os
from pathlib import Path
from typing import TypeVar

import litellm
from pydantic import BaseModel

Answer = TypeVar("Answer", bound=BaseModel)

_PROMPTS = Path(__file__).parent.parent / "prompts"


def render(name: str, **variables: object) -> str:
    version = os.environ.get("PROMPT_VERSION", "v1")
    return (_PROMPTS / f"{name}.{version}.md").read_text().format(**variables)


async def ask(name: str, answer: type[Answer], **variables: object) -> Answer:
    """One judgement from the model: a prompt in, a typed answer out."""
    response = await litellm.acompletion(
        model=os.environ["LLM_MODEL"],
        messages=[{"role": "user", "content": render(name, **variables)}],
        response_format=answer,
    )
    return answer.model_validate_json(response.choices[0].message.content)
