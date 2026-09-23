"""An agent with no framework: a coroutine function from a request to its answer."""

import inspect
from typing import get_type_hints


class FunctionAdapter:
    code_answers = True

    def check(self, agent, produced: tuple[type, ...]) -> None:
        answer = get_type_hints(agent).get("return", inspect.Signature.empty)
        if answer in (inspect.Signature.empty, None, type(None)) or not produced:
            return
        declared = getattr(answer, "__produces__", (answer,))
        strangers = [cls.__name__ for cls in declared if cls not in produced]
        if strangers:
            raise TypeError(
                f"{agent.__name__} returns {strangers}, which its `produces` does not declare"
            )

    async def invoke(self, agent, request, thread_id: str):
        return await agent(request)

    def extract_answer(self, result, produced: tuple[type, ...]):
        return result


adapter = FunctionAdapter()
