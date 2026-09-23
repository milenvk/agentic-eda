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
}


def adapter_for(agent) -> Adapter:
    if inspect.iscoroutinefunction(agent):
        module = "agentic_eda.activator.adapters.function"
    else:
        origin = type(agent).__module__.split(".")[0]
        module = _BY_MODULE.get(origin)
        if module is None:
            raise TypeError(
                f"no adapter for {type(agent).__name__} from {origin!r}: "
                f"pass one to attach(..., adapter=...)"
            )
    return importlib.import_module(module).adapter
