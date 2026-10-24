"""In-memory adapter for the EventBroker port, for tests in one process.

Events are delivered in publish order, one at a time, to every handler subscribed to their
type, which keeps the port's ordering promise and more. A handler that raises is recorded
in ``failed`` rather than redelivered, so a test asserts the failure instead of looping.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from .broker import EventHandler, WireEvent

log = logging.getLogger("EventBroker")


class InMemoryBroker:
    def __init__(self) -> None:
        self.published: list[WireEvent] = []
        self.failed: list[tuple[WireEvent, Exception]] = []
        self._handlers: dict[str, list[EventHandler]] = {}
        self._queue: asyncio.Queue[WireEvent] = asyncio.Queue()

    async def publish(
        self,
        event_type: str,
        source: str,
        data: dict,
        id: str | None = None,
        attributes: dict[str, str] | None = None,
    ) -> WireEvent:
        attributes = dict(attributes or {})
        attributes.setdefault("time", datetime.now(timezone.utc).isoformat())
        attributes.setdefault("datacontenttype", "application/json")
        event = WireEvent(
            id=id or str(uuid.uuid4()), type=event_type, source=source, data=data, **attributes
        )
        self.published.append(event)
        self._queue.put_nowait(event)
        return event

    async def subscribe(
        self, event_type: str, handler: EventHandler, mode: str = "broadcast"
    ) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    async def run(self) -> None:
        """Deliver until cancelled."""
        while True:
            event = await self._queue.get()
            try:
                for handler in self._handlers.get(event.type, []):
                    try:
                        await handler(event)
                    except Exception as error:
                        log.warning("a handler of %s %s failed: %r", event.type, event.id, error)
                        self.failed.append((event, error))
            finally:
                self._queue.task_done()

    async def settled(self) -> None:
        """Return once every published event, and everything it caused, is delivered."""
        await self._queue.join()

    def of_type(self, event_type: str) -> list[WireEvent]:
        return [event for event in self.published if event.type == event_type]
