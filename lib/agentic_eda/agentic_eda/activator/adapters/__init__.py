"""Framework adapters: the two things frameworks disagree on, and nothing else.

How an agent is invoked, and how its answer is read out of the result. An adapter is
those two functions, chosen by the module the agent's class comes from, so no framework
is imported until an agent of it is attached.
"""

import importlib
import inspect
from typing import Protocol


class Adapter(Protocol):
    # Whether code or a model assembles the answer. Code cannot drift into saying nothing.
    code_answers: bool

    def check(self, agent, produced: tuple[type, ...]) -> None:
        """Fail at startup where the agent's own declaration disagrees with `produces`."""

    async def invoke(self, agent, request, thread_id: str):
        """Run the agent once on one request."""

    def extract_answer(self, result, produced: tuple[type, ...]):
        """Read the agent's answer out of whatever its framework returned."""


_BY_MODULE = {
    "langgraph": "agentic_eda.activator.adapters.langgraph",
    "google.adk": "agentic_eda.activator.adapters.adk",
}


def adapter_for(agent) -> Adapter:
    if inspect.iscoroutinefunction(agent):
        module = "agentic_eda.activator.adapters.function"
    else:
        module = _by_framework(type(agent))
        if module is None:
            raise TypeError(
                f"no adapter for {type(agent).__name__} from {type(agent).__module__!r}: "
                f"pass one to attach(..., adapter=...)"
            )
    return importlib.import_module(module).adapter


def _by_framework(cls: type) -> str | None:
    # A developer's own subclass of a framework's agent class comes from the developer's
    # module, so the framework is found among the class's bases.
    for base in cls.__mro__:
        for prefix, module in _BY_MODULE.items():
            if base.__module__ == prefix or base.__module__.startswith(prefix + "."):
                return module
    return None
