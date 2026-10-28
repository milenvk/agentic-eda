"""Prompts are configuration: versioned files, the version chosen by `PROMPT_VERSION`.

The files are in this package, beside this module, so they are installed with it. A line
whose variables all render empty is left out, so a sentence about something the trip may
not have, such as a pending question, is written in the file and not in code.
"""

import os
from importlib import resources
from string import Formatter


def render(name: str, **variables: object) -> str:
    version = os.environ.get("PROMPT_VERSION", "v1")
    prompt = resources.files(__package__).joinpath(f"{name}.{version}.md")
    lines = []
    for line in prompt.read_text(encoding="utf-8").splitlines():
        fields = [field for _, field, _, _ in Formatter().parse(line) if field]
        if fields and all(variables[field] == "" for field in fields):
            continue
        lines.append(line.format(**variables))
    return "\n".join(lines) + "\n"
