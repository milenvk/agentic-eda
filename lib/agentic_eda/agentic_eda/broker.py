"""The EventBroker port — the only thing a component knows about the world outside itself."""

from collections.abc import Awaitable, Callable
from typing import Protocol

from .envelope import ContextAttributes


class WireEvent(ContextAttributes):
    """A business fact as it travels: its context attributes plus its data.

    This is the shape a CloudEvent takes on the wire, so the record here and the
    JSON out there are one thing. Its data is a dict: a contract (``events.py``)
    is applied where the event is consumed, never by the broker.
    """

    data: dict


EventHandler = Callable[[WireEvent], Awaitable[None]]

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
    ) -> WireEvent:
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
