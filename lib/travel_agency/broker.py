"""The EventBroker port — the only thing a component knows about the world outside itself."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Event:
    """A business fact: something that happened.

    The first three fields and ``payload`` map to the CloudEvents core attributes
    (``id``, ``type``, ``source``, ``data``). ``attributes`` holds every other
    CloudEvents attribute — optional standard ones such as ``time``, and extension
    ones such as ``correlationid`` (introduced in chapter 2).
    """

    id: str
    type: str
    source: str
    payload: dict
    attributes: dict[str, str] = field(default_factory=dict)


EventHandler = Callable[[Event], Awaitable[None]]


class EventBroker(Protocol):
    """What a component may do: state a fact, and react to a kind of fact."""

    async def publish(
        self,
        event_type: str,
        source: str,
        payload: dict,
        id: str | None = None,
        attributes: dict[str, str] | None = None,
    ) -> str:
        """Record that something happened. Returns the event's unique id."""
        ...

    async def subscribe(
        self,
        event_type: str,
        handler: EventHandler,
        mode: str = "broadcast",
    ) -> None:
        """Call ``handler`` for every event of the given type."""
        ...
