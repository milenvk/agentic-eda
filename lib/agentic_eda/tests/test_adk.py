"""A state's operations as an ADK agent's tools, run through ADK's own runner with a scripted LLM."""

from collections.abc import AsyncGenerator
from typing import Annotated

import pytest
from examples import ItineraryProposed
from google.adk.agents import LlmAgent
from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import BaseModel, Field

from agentic_eda.activator import Activation, core
from agentic_eda.adk import StateOperations
from agentic_eda.state import Refused


class Order(BaseModel):
    """A state of one operation, which accepts once and refuses after."""

    trip_id: str = "trip-1"
    approved: bool = False

    def approve(self, rank: Annotated[int, Field(ge=1, description="the chosen itinerary's number")]) -> ItineraryProposed:
        """Approve one itinerary by its number."""
        if self.approved:
            raise Refused("the order is already approved")
        self.approved = True
        return ItineraryProposed(trip_id=self.trip_id, itineraries=[f"itinerary {rank}"])


class FakeLlm(BaseLlm):
    """A scripted LLM: one answer per call, in order, the last one repeating."""

    script: list[list[types.Part]] = []
    requests: list[LlmRequest] = []
    model: str = "fake"

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        self.requests.append(llm_request)
        parts = self.script[min(len(self.requests), len(self.script)) - 1]
        yield LlmResponse(content=types.Content(role="model", parts=parts))


def calls(name: str, **args) -> list[types.Part]:
    return [types.Part(function_call=types.FunctionCall(name=name, args=args))]


def says(text: str) -> list[types.Part]:
    return [types.Part(text=text)]


async def run(llm: FakeLlm, state: Order) -> Activation:
    """One activation of an agent whose only tools are the state's operations."""
    agent = LlmAgent(name="agent", model=llm, instruction="Approve.", tools=[StateOperations(Order.approve)])
    runner = InMemoryRunner(agent=agent, app_name="test")
    await runner.session_service.create_session(app_name="test", user_id="u", session_id="s")
    activation = Activation(event=None, request=None, activator=None, state=state)
    token = core._ACTIVATION.set(activation)  # what the activator does before invoking an agent
    try:
        message = types.Content(role="user", parts=[types.Part(text="go")])
        async for _ in runner.run_async(user_id="u", session_id="s", new_message=message):
            pass
    finally:
        core._ACTIVATION.reset(token)
    return activation


def tool_result(request: LlmRequest) -> dict:
    """What the LLM was told its tool call came to."""
    parts = [part for content in request.contents for part in content.parts if part.function_response]
    return parts[-1].function_response.response


async def test_an_operation_is_the_llms_tool_under_its_own_name_and_docstring():
    llm = FakeLlm(script=[calls("approve", rank=2)], requests=[])
    await run(llm, Order())
    (declaration,) = llm.requests[0].config.tools[0].function_declarations
    assert declaration.name == "approve"
    assert declaration.description == "Approve one itinerary by its number."
    assert declaration.parameters_json_schema["properties"]["rank"]["description"] == "the chosen itinerary's number"


async def test_an_accepted_operation_answers_the_activation_and_ends_the_turn():
    llm = FakeLlm(script=[calls("approve", rank=2)], requests=[])
    activation = await run(llm, Order())
    assert activation.answered == ItineraryProposed(trip_id="trip-1", itineraries=["itinerary 2"])
    assert len(llm.requests) == 1  # nothing the LLM could say after the decision is read


async def test_a_refusal_is_the_llms_observation_and_the_activation_stays_unanswered():
    llm = FakeLlm(script=[calls("approve", rank=1), says("I see.")], requests=[])
    activation = await run(llm, Order(approved=True))
    assert activation.answered is None
    assert tool_result(llm.requests[1]) == {"error": "the order is already approved"}


async def test_a_malformed_call_is_refused_the_same_way():
    llm = FakeLlm(script=[calls("approve", rank=0), says("I see.")], requests=[])
    activation = await run(llm, Order())
    assert activation.answered is None
    assert "greater than or equal to 1" in tool_result(llm.requests[1])["error"]
