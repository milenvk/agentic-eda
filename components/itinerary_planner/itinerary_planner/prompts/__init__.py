"""Prompts are configuration: versioned files, the version chosen by `PROMPT_VERSION`.

The files are in this package, beside this module, so they are installed with it.
"""

import os
from importlib import resources
from typing import TypeVar

import litellm
from pydantic import BaseModel

Answer = TypeVar("Answer", bound=BaseModel)


def render(name: str, **variables: object) -> str:
    version = os.environ.get("PROMPT_VERSION", "v1")
    prompt = resources.files(__package__).joinpath(f"{name}.{version}.md")
    return prompt.read_text(encoding="utf-8").format(**variables)


async def ask(name: str, answer: type[Answer], **variables: object) -> Answer:
    """One judgement from the model: a prompt in, a typed answer out."""
    response = await litellm.acompletion(
        model=os.environ["LLM_MODEL"],
        messages=[{"role": "user", "content": render(name, **variables)}],
        response_format=answer,
        temperature=0,  # a judgement, not a creative task: the same prompt gets the same answer
    )
    return answer.model_validate_json(response.choices[0].message.content)
