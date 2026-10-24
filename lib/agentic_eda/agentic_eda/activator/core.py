"""The agent activator: it carries events across the boundary, and the agent never learns how.

One activation is one inbound event handed to the agent. The activator validates the
event's data into the class the agent declared, invokes the agent through its
framework's adapter, reduces what comes back to the classes the agent may answer with,
and publishes each with its envelope. Every outbound event passes through ``_publish``,
so the outbound boundary is one function.

For an agent that declared its state, the activator also keeps that state: before the
activation it asks the store whether the event was already handled, loads the state the
event's key names (or creates one for an event that starts a new state), and hands it to
the agent through the activation; after the activation it commits the state with the
version it loaded and the event's id, then publishes, then acknowledges.
"""

import asyncio
import json
import logging
import os
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

from .. import connect
from ..broker import PARTITION_KEY, EventBroker, WireEvent
from ..contracts import EventContract, Nothing
from ..envelope import ContextAttributes
from ..publishing import publish_fact
from ..state import StateStore
from .adapters import adapter_for
from .declarations import Consumes, State, produced_classes

log = logging.getLogger("Activator")


class NoAnswer(RuntimeError):
    """An activation that had to answer published nothing. Raising redelivers the event."""


class RejectedAnswer(ValueError):
    """What the agent answered with is not one of the classes it declared."""


@dataclass
class Activation:
    """One inbound event under activation: what the agent's code may read and answer.

    ``request`` is the event as the class the agent declared, ``state`` the business state
    the activator loaded for an agent with a ``state`` declaration, and ``answer`` is how
    code that cannot return, such as an LLM's tool, hands the activator its one event.
    """

    event: WireEvent
    request: EventContract
    activator: "Activator"
    state: BaseModel | None = None
    published: list[WireEvent] = field(default_factory=list)
    answered: EventContract | None = None
    state_id: int | None = None
    version: int | None = None

    def answer(self, fact: EventContract) -> None:
        """Hand the activator the activation's one event, to publish once the state is committed."""
        if self.answered is not None:
            raise RuntimeError(
                f"the activation already answered with {type(self.answered).__name__}"
            )
        self.answered = fact


# Set before the agent is invoked. asyncio carries it into every task a framework spawns
# and into a worker thread, so anything running inside finds its activation.
_ACTIVATION: ContextVar[Activation | None] = ContextVar("activation", default=None)


def activation() -> Activation:
    """The running activation, from anywhere inside the agent: its code, a tool, a prompt."""
    running = _ACTIVATION.get()
    if running is None:
        raise RuntimeError("there is no activation running")
    return running


async def publish(fact: EventContract) -> WireEvent:
    """State a fact from inside an activation: the code twin of a publish tool.

    For an agent that must commit one fact before it goes on to the next. It is the
    same path a returned answer takes, so the class is one the agent declared.
    """
    running = _ACTIVATION.get()
    if running is None:
        raise RuntimeError("publish is only available inside an activation")
    return await running.activator._publish(fact, running)


class Activator:
    def __init__(
        self,
        agent,
        *,
        consumes: Consumes,
        produces,
        source: str | None,
        state: State | None = None,
        adapter=None,
    ):
        if not isinstance(consumes, Consumes):
            raise TypeError("pass what eda.consumes(...) returned as `consumes`")
        if state is not None and not isinstance(state, State):
            raise TypeError("pass what eda.state(...) returned as `state`")
        self.source = source or os.environ.get("COMPONENT_NAME")
        if not self.source:
            raise RuntimeError("name the component: pass `source` or set COMPONENT_NAME")
        self._agent = agent
        self._consumes = consumes
        self._consumed = consumes.by_type()
        self._answer_schema = produces
        self._produced = produced_classes(produces)
        self._state = state
        self._adapter = adapter or adapter_for(agent)
        self._adapter.check(agent, self._produced)
        self._broker: EventBroker | None = None
        self._store: StateStore | None = None

    @asynccontextmanager
    async def running(self):
        """Open the broker and, for an agent with state, the store; deliver until closed."""
        async with AsyncExitStack() as opened:
            self._broker = await opened.enter_async_context(connect.event_broker(self.source))
            if self._state is not None:
                self._store = await opened.enter_async_context(connect.state_store(self.source))
            for event_type in self._consumed:
                await self._broker.subscribe(event_type, self.activate)
            delivering = asyncio.create_task(self._broker.run())
            delivering.add_done_callback(_report_a_dead_loop)
            try:
                yield self
            finally:
                delivering.cancel()
                with suppress(asyncio.CancelledError):
                    await delivering

    async def activate(self, event: WireEvent) -> None:
        """One activation: returning acknowledges the event, raising redelivers it."""
        request = self._validated(event)
        if request is None:
            return  # acknowledged: a malformed event never validates, however often it returns
        activation = Activation(event=event, request=request, activator=self)
        if self._state is not None and not await self._load(activation):
            return  # acknowledged: already handled, or about a state this store never had
        token = _ACTIVATION.set(activation)
        try:
            result = await self._adapter.invoke(self._agent, request, self._thread_id(activation))
            if not self._produced:
                await self._commit(activation)
                return  # a pure consumer: whatever it returned is its own business
            answer = activation.answered
            if answer is None:
                answer = self._adapter.extract_answer(result, self._produced)
            facts = self._reduce(answer)
            await self._commit(activation)
            said_nothing = False
            for fact in facts:
                if isinstance(fact, Nothing):
                    said_nothing = True
                    log.info("%s answered nothing to %s: %s", self.source, event.id, fact.reason)
                else:
                    await self._publish(fact, activation)
            if not activation.published and not said_nothing:
                raise NoAnswer(
                    f"{self.source} published nothing for {event.type} {event.id}; "
                    f"an agent that may have nothing to say declares Nothing and says so"
                )
        finally:
            _ACTIVATION.reset(token)

    def _validated(self, event: WireEvent) -> EventContract | None:
        cls = self._consumed[event.type]
        attributes = ContextAttributes(**event.model_dump(exclude={"data", "identitytoken"}))
        try:
            return cls.model_validate({**event.data, "attributes_": attributes})
        except ValidationError as error:
            log.warning("%s rejected %s %s:\n%s", self.source, event.type, event.id, error)
            return None

    async def _load(self, activation: Activation) -> bool:
        """Find or create the event's state and put it on the activation; False means skip."""
        declared, event = self._state, activation.event
        key = getattr(activation.request, declared.key, None)
        if key is None:
            # An event about no state yet, such as a request: it starts one, and a
            # redelivery of it finds the one it started.
            state_id = await self._store.create(event.id)
        else:
            state_id = int(key)
        if await self._store.handled(state_id, event.id):
            log.info("%s already handled %s for %s %s", self.source, event.id, declared.key, state_id)
            return False
        loaded = await self._store.load(state_id)
        if loaded is None:
            log.warning("%s has no %s %s for %s %s", self.source, declared.cls.__name__, state_id, event.type, event.id)  # fmt: skip
            return False
        document, activation.version = loaded
        # The row's id is the state's id, on a new state and a loaded one alike.
        activation.state = declared.cls.model_validate({**document, declared.key: state_id})
        activation.state_id = state_id
        return True

    async def _commit(self, activation: Activation) -> None:
        if self._state is None:
            return
        await self._store.commit(
            activation.state_id,
            activation.state.model_dump(mode="json"),
            activation.version,
            activation.event.id,
        )

    def _thread_id(self, activation: Activation) -> str:
        # The state's id where there is one, else the key, so everything about one trip
        # shares a thread; an event without either gets a thread of its own.
        if activation.state_id is not None:
            return str(activation.state_id)
        event = activation.event
        return str(getattr(event, PARTITION_KEY, None) or event.id)

    def _reduce(self, answer) -> list[EventContract]:
        """Turn what the agent answered into instances of the classes it declared."""
        if answer is None:
            # Code cannot drift the way a model can, so where code answers, no answer is
            # Nothing, if the agent declared that it may have nothing to say.
            if self._adapter.code_answers and Nothing in self._produced:
                return [Nothing(reason="the agent returned no answer")]
            return []
        if isinstance(answer, (list, tuple)):
            return [fact for item in answer for fact in self._reduce(item)]
        if isinstance(answer, str):
            try:
                answer = json.loads(answer)
            except json.JSONDecodeError as error:
                raise RejectedAnswer(f"the answer is not JSON: {answer[:200]!r}") from error
        if isinstance(answer, dict):
            answer = self._parsed(answer)
        if hasattr(type(answer), "__produces__"):
            answer = answer.fact  # the wrapper, unwrapped
        if not isinstance(answer, self._produced):
            raise RejectedAnswer(
                f"{type(answer).__name__} is not among what {self.source} declared it produces"
            )
        return [answer]

    def _parsed(self, answer: dict) -> EventContract:
        candidates = (self._answer_schema, *self._produced)
        errors = []
        for cls in candidates:
            try:
                return cls.model_validate(answer)
            except ValidationError as error:
                errors.append(f"{cls.__name__}: {error}")
        raise RejectedAnswer("the answer fits none of the declared classes:\n" + "\n".join(errors))

    async def _publish(self, fact: EventContract, activation: Activation) -> WireEvent:
        if not isinstance(fact, self._produced) or isinstance(fact, Nothing):
            raise RejectedAnswer(
                f"{type(fact).__name__} is not among what {self.source} declared it produces"
            )
        # Validated again on the way out: a provider enforces a schema's shape and not its
        # constraints, and an instance may have been built without validation.
        fact = type(fact).model_validate(fact.model_dump(exclude={"attributes_"}))
        inbound = activation.event
        attributes = {
            "correlationid": str(getattr(inbound, "correlationid", inbound.id)),
            "causationid": inbound.id,
        }
        published = await publish_fact(self._broker, self.source, fact, attributes)
        activation.published.append(published)
        return published


def attach(
    app,
    agent,
    *,
    consumes: Consumes,
    produces,
    state: State | None = None,
    source: str | None = None,
    adapter=None,
):
    """Attach the activator to the app that hosts the agent: the developer's one line.

    The activator starts and stops with the app's lifespan, so attach to the app that is
    run. A sub-application mounted inside another has no lifespan of its own.
    """
    activator = Activator(
        agent, consumes=consumes, produces=produces, source=source, state=state, adapter=adapter
    )
    hosting = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(scope_app):
        async with hosting(scope_app) as hosted:
            async with activator.running():
                yield hosted

    app.router.lifespan_context = lifespan
    return activator


def _report_a_dead_loop(delivering: asyncio.Task) -> None:
    if not delivering.cancelled() and delivering.exception() is not None:
        log.error("the delivery loop stopped", exc_info=delivering.exception())
