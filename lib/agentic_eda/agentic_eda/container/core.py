"""The agent container: it carries facts across the boundary, and the agent never learns how.

One activation is one inbound event handed to the agent. The container validates the
event's data into the class the agent declared, invokes the agent through its
framework's adapter, reduces what comes back to the classes the agent may answer with,
and publishes each with its envelope. Every outbound event passes through ``_publish``,
so the outbound boundary is one function.
"""

import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass, field

from pydantic import ValidationError

from .. import connect
from ..broker import PARTITION_KEY, Event, EventAttributes, EventBroker
from ..events import OWN_ID, EventModel, Nothing, binding_of, data_of
from .adapters import adapter_for
from .declarations import Consumes, produced_classes

log = logging.getLogger("Container")


class NoAnswer(RuntimeError):
    """An activation that had to answer published nothing. Raising redelivers the event."""


class RejectedAnswer(ValueError):
    """What the agent answered with is not one of the classes it declared."""


@dataclass
class Activation:
    event: Event
    container: "Container"
    published: list[Event] = field(default_factory=list)


# Set before the agent is invoked. asyncio carries it into every task a framework spawns
# and into a worker thread, so anything publishing from inside finds its activation.
_ACTIVATION: ContextVar[Activation | None] = ContextVar("activation", default=None)


async def publish(fact: EventModel) -> Event:
    """State a fact from inside an activation: the code twin of a publish tool.

    For an agent that must commit one fact before it goes on to the next. It is the
    same path a returned answer takes, so the class is one the agent declared.
    """
    activation = _ACTIVATION.get()
    if activation is None:
        raise RuntimeError("publish is only available inside an activation")
    return await activation.container._publish(fact, activation)


class Container:
    def __init__(self, agent, *, consumes: Consumes, produces, source: str | None, adapter=None):
        if not isinstance(consumes, Consumes):
            raise TypeError("pass what eda.consumes(...) returned as `consumes`")
        self.source = source or os.environ.get("COMPONENT_NAME")
        if not self.source:
            raise RuntimeError("name the component: pass `source` or set COMPONENT_NAME")
        self._agent = agent
        self._consumes = consumes
        self._consumed = consumes.by_type()
        self._answer_schema = produces
        self._produced = produced_classes(produces)
        self._adapter = adapter or adapter_for(agent)
        self._adapter.check(agent, self._produced)
        self._broker: EventBroker | None = None

    @asynccontextmanager
    async def running(self):
        """Open the broker, subscribe to what the agent consumes, and deliver until closed."""
        async with connect.event_broker(self.source) as broker:
            self._broker = broker
            for event_type in self._consumed:
                await broker.subscribe(event_type, self.activate)
            delivering = asyncio.create_task(broker.run())
            delivering.add_done_callback(_report_a_dead_loop)
            try:
                yield self
            finally:
                delivering.cancel()
                with suppress(asyncio.CancelledError):
                    await delivering

    async def activate(self, event: Event) -> None:
        """One activation: returning acknowledges the event, raising redelivers it."""
        request = self._validated(event)
        if request is None:
            return  # acknowledged: a malformed event never validates, however often it returns
        activation = Activation(event=event, container=self)
        token = _ACTIVATION.set(activation)
        try:
            result = await self._adapter.invoke(self._agent, request, _thread_id(event))
            if not self._produced:
                return  # a pure consumer: whatever it returned is its own business
            answer = self._adapter.extract_answer(result, self._produced)
            said_nothing = False
            for fact in self._reduce(answer):
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

    def _validated(self, event: Event) -> EventModel | None:
        cls = self._consumed[event.type]
        attributes = EventAttributes(**event.model_dump(exclude={"data", "identitytoken"}))
        try:
            return cls.model_validate({**event.data, "attributes_": attributes})
        except ValidationError as error:
            log.warning("%s rejected %s %s:\n%s", self.source, event.type, event.id, error)
            return None

    def _reduce(self, answer) -> list[EventModel]:
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

    def _parsed(self, answer: dict) -> EventModel:
        candidates = (self._answer_schema, *self._produced)
        errors = []
        for cls in candidates:
            try:
                return cls.model_validate(answer)
            except ValidationError as error:
                errors.append(f"{cls.__name__}: {error}")
        raise RejectedAnswer("the answer fits none of the declared classes:\n" + "\n".join(errors))

    async def _publish(self, fact: EventModel, activation: Activation) -> Event:
        if not isinstance(fact, self._produced) or isinstance(fact, Nothing):
            raise RejectedAnswer(
                f"{type(fact).__name__} is not among what {self.source} declared it produces"
            )
        # Validated again on the way out: a provider enforces a schema's shape and not its
        # constraints, and an instance may have been built without validation.
        fact = type(fact).model_validate(fact.model_dump(exclude={"attributes_"}))
        binding = binding_of(fact)
        inbound = activation.event
        attributes = {
            "correlationid": str(getattr(inbound, "correlationid", inbound.id)),
            "causationid": inbound.id,
        }
        event_id = None
        if binding.order_per is OWN_ID:
            event_id = str(uuid.uuid4())
            attributes[PARTITION_KEY] = event_id
        elif binding.order_per is not None:
            attributes[PARTITION_KEY] = str(getattr(fact, binding.order_per))
        published = await self._broker.publish(
            binding.type,
            self.source,
            data_of(fact),
            id=event_id,
            attributes=attributes,
        )
        activation.published.append(published)
        return published


def attach(app, agent, *, consumes: Consumes, produces, source: str | None = None, adapter=None):
    """Attach the container to the app that hosts the agent: the developer's one line.

    The container starts and stops with the app's lifespan, so attach to the app that is
    run. A sub-application mounted inside another has no lifespan of its own.
    """
    container = Container(
        agent, consumes=consumes, produces=produces, source=source, adapter=adapter
    )
    hosting = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(scope_app):
        async with hosting(scope_app) as state:
            async with container.running():
                yield state

    app.router.lifespan_context = lifespan
    return container


def _thread_id(event: Event) -> str:
    # The key where there is one, so everything about one trip shares a thread.
    return str(getattr(event, PARTITION_KEY, None) or event.id)


def _report_a_dead_loop(delivering: asyncio.Task) -> None:
    if not delivering.cancelled() and delivering.exception() is not None:
        log.error("the delivery loop stopped", exc_info=delivering.exception())
