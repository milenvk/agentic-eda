"""Prompts are configuration: versioned files, the version chosen by `PROMPT_VERSION`.

The files are in this package, beside this module, so they are installed with it.
"""

import os
from importlib import resources


def render(name: str, **variables: object) -> str:
    version = os.environ.get("PROMPT_VERSION", "v1")
    prompt = resources.files(__package__).joinpath(f"{name}.{version}.md")
    return prompt.read_text(encoding="utf-8").format(**variables)
