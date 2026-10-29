"""The ADK face of the library: a state's operations as an ADK agent's tools.

An agent that owns business state lets the LLM act on it only through the state's own
operations. ``StateOperations`` binds the operations named at construction to the state
under activation, afresh for every LLM call, and each tool does what any caller of an
operation does: the event the operation returns is the activation's answer, and a refusal
is the LLM's observation. Only a component that runs ADK imports this module, so the
library does not depend on ADK; ``agentic-eda[adk]`` installs it for the library's own
tests.
"""

import logging
from collections.abc import Callable
from typing import Any

from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools import BaseTool, FunctionTool, ToolContext
from google.adk.tools.base_toolset import BaseToolset
from pydantic import ValidationError, validate_call

from .activator import activation
from .contracts import EventContract
from .state import Refused

log = logging.getLogger("agentic_eda.adk")


class StateOperations(BaseToolset):
    """The named operations of the state under activation, as the LLM's tools."""

    def __init__(self, *operations: Callable[..., Any]) -> None:
        super().__init__()
        self._names = [operation.__name__ for operation in operations]

    async def get_tools(self, readonly_context: ReadonlyContext | None = None) -> list[BaseTool]:
        state = activation().state
        # ADK hands over the LLM's arguments as JSON types; Pydantic makes them the operation's.
        return [OperationTool(validate_call(getattr(state, name))) for name in self._names]


class OperationTool(FunctionTool):
    """One operation as a tool: its event answers the activation, its refusal is the LLM's observation."""

    async def run_async(self, *, args: dict[str, Any], tool_context: ToolContext) -> Any:
        try:
            result = await super().run_async(args=args, tool_context=tool_context)
        except (Refused, ValidationError) as error:
            log.info("the LLM's call of %s was refused: %s", self.name, error)
            return {"error": str(error)}
        if not isinstance(result, EventContract):
            return result  # ADK's own answer to a malformed call stays as it is
        activation().answer(result)
        tool_context.actions.skip_summarization = True  # the decision is made; no more LLM calls
        log.info("the LLM decided: %s", type(result).__name__)
        return {"result": "done"}
