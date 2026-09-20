"""The hydration port: the context an agent loads when it wakes up.

An agent asks for what is already known about the subject of its work and gets text to
reason with. The adapter is chosen by configuration, and the default loads nothing.
"""

import os
from typing import Protocol


class Hydration(Protocol):
    async def context_for(self, key: str) -> str:
        """What is known about the subject with this key, as text for a prompt."""
        ...


class NoHydration:
    """Loads nothing: an agent's prompt gets an empty context."""

    async def context_for(self, key: str) -> str:
        return ""


def hydration() -> Hydration:
    """The adapter `HYDRATION_ADAPTER` selects; `none`, the default, loads nothing."""
    adapter = os.environ.get("HYDRATION_ADAPTER", "none")
    if adapter == "none":
        return NoHydration()
    raise RuntimeError(f"HYDRATION_ADAPTER={adapter!r} names an adapter this build does not have")
