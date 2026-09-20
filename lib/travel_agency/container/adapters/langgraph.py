"""A compiled LangGraph graph, taken as its developer built it, checkpointer and all."""

from typing import get_args


class LangGraphAdapter:
    # A graph's final state is assembled by its nodes, which are code.
    code_answers = True

    def check(self, agent, produced: tuple[type, ...]) -> None:
        pass  # a graph's output schema is its state, which says nothing about the answer

    async def invoke(self, agent, request, thread_id: str):
        field = _field_holding(agent.get_input_schema(), type(request))
        return await agent.ainvoke(
            {field: request}, config={"configurable": {"thread_id": thread_id}}
        )

    def extract_answer(self, result, produced: tuple[type, ...]):
        answers = [value for value in result.values() if isinstance(value, produced)]
        if len(answers) > 1:
            raise ValueError("the graph's final state holds more than one answer")
        return answers[0] if answers else None


def _field_holding(schema, request_class: type) -> str:
    """The input field whose type is the request's: bound by type, never by name."""
    for name, field in schema.model_fields.items():
        candidates = get_args(field.annotation) or (field.annotation,)
        if any(isinstance(c, type) and issubclass(request_class, c) for c in candidates):
            return name
    raise TypeError(f"the graph's input has no field of type {request_class.__name__}")


adapter = LangGraphAdapter()
