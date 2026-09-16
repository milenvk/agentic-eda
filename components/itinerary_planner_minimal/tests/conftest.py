"""A stub of the EventBroker port for unit tests.

A deliberate few-line test double — not chapter 2's InMemoryBroker adapter.
"""

import pytest

from travel_agency.broker import Event


class StubBroker:
    def __init__(self) -> None:
        self.published: list[Event] = []

    async def publish(
        self,
        event_type: str,
        source: str,
        data: dict,
        id: str | None = None,
        attributes: dict[str, str] | None = None,
    ) -> Event:
        event = Event(
            id=id or f"stub-{len(self.published)}",
            type=event_type,
            source=source,
            data=data,
            **(attributes or {}),
        )
        self.published.append(event)
        return event

    async def subscribe(self, event_type, handler, mode="broadcast") -> None:
        pass


@pytest.fixture
def broker() -> StubBroker:
    return StubBroker()
