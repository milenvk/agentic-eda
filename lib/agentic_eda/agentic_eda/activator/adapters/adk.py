"""An ADK agent, taken as constructed, run through ADK's own Runner.

One Runner per agent object, on an in-memory session service of its own, since ADK's host
app exposes none of its own. The session is the activation's key, so one trip's activations
accumulate in one session as its trace; the typed request travels as the user message, and
an agent's answer is whatever it handed to ``eda.activation().answer(...)``, or else the
text of its final response, parsed against ``produces`` by the activator.
"""

from google.adk.agents.run_config import RunConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

USER = "activator"
# An activation is a few LLM calls at most. An LLM that keeps calling tools past its decision
# would otherwise run to ADK's default of 500; failing the activation redelivers the event.
MAX_LLM_CALLS = 10


class AdkAdapter:
    # An LLM may be on the path to the answer, so no answer is a failure unless declared.
    code_answers = False

    def __init__(self) -> None:
        self._runners: dict[int, Runner] = {}

    def check(self, agent, produced: tuple[type, ...]) -> None:
        pass  # an ADK agent declares no answer type the activator could compare

    async def invoke(self, agent, request, thread_id: str):
        runner = self._runner_for(agent)
        sessions = runner.session_service
        if await sessions.get_session(app_name=runner.app_name, user_id=USER, session_id=thread_id) is None:
            await sessions.create_session(app_name=runner.app_name, user_id=USER, session_id=thread_id)
        message = types.Content(
            role="user", parts=[types.Part(text=request.model_dump_json(exclude={"attributes_"}))]
        )
        final_text = None
        async for event in runner.run_async(
            user_id=USER,
            session_id=thread_id,
            new_message=message,
            run_config=RunConfig(max_llm_calls=MAX_LLM_CALLS),
        ):
            if event.is_final_response() and event.content and event.content.parts:
                final_text = event.content.parts[0].text or final_text
        return final_text

    def extract_answer(self, result, produced: tuple[type, ...]):
        return result

    def _runner_for(self, agent) -> Runner:
        if id(agent) not in self._runners:
            self._runners[id(agent)] = Runner(
                app_name=agent.name, agent=agent, session_service=InMemorySessionService()
            )
        return self._runners[id(agent)]


adapter = AdkAdapter()
