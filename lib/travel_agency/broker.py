"""The EventBroker port — the only thing a component knows about the world outside itself."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field


class EventAttributes(BaseModel, extra="allow", frozen=True):
    """What a CloudEvent says about itself: everything but the fact.

    The declared fields are the spec's context attributes. Anything else on the
    wire is an extension attribute, kept by ``extra="allow"`` and read by its own
    name (``event.correlationid`` from chapter 2). Extensions may be strings,
    integers or booleans by the spec; this system's own are strings.
    """

    specversion: Literal["1.0"] = "1.0"
    id: str
    type: str
    source: str
    time: datetime | None = None
    datacontenttype: str | None = None
    dataschema: str | None = None
    subject: str | None = None
    __pydantic_extra__: dict[str, str | int | bool] = Field(init=False)


class Event(EventAttributes):
    """A business fact: something that happened, and what it says about itself.

    An event is its attributes plus its data, which is the shape a CloudEvent
    takes on the wire, so the record here and the JSON out there are one thing.
    """

    data: dict


EventHandler = Callable[[Event], Awaitable[None]]

# The CloudEvents partitioning extension: the attribute an adapter orders by. Events
# sharing its value are delivered in publish order, one at a time, to one consumer.
# Producers set it, adapters read it, and neither spells the name twice.
PARTITION_KEY = "partitionkey"


class EventBroker(Protocol):
    """What a component may do: state a fact, and react to a kind of fact."""

    async def publish(
        self,
        event_type: str,
        source: str,
        data: dict,
        id: str | None = None,
        attributes: dict[str, str] | None = None,
    ) -> Event:
        """Record that something happened.

        Returns the event as published, with whatever the caller left to the
        broker filled in: its id, the time, and the rest of the envelope.
        """
        ...

    async def subscribe(
        self,
        event_type: str,
        handler: EventHandler,
        mode: str = "broadcast",
    ) -> None:
        """Call ``handler`` for every event of the given type."""
        ...


class EventBrokerConnection(EventBroker, Protocol):
    """An open broker: everything above, plus the loop that delivers events.

    Agents and handlers depend on ``EventBroker``, because publishing and
    subscribing is all their business logic ever does. Only a component's entry
    point needs this wider surface, to hand control to the broker once its
    subscriptions are registered. ``connect.event_broker`` opens and closes it.
    """

    async def run(self) -> None:
        """Deliver subscribed events until cancelled."""
        ...
