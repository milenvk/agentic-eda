"""The StateStore port: where an agent's business state is kept between activations.

A state is one document per subject, such as a trip, written by one component. The port is
four calls and nothing else: no update, because ``commit`` is the only write after creation
and it insists on the version and the cause; no delete, because nothing in the business
deletes a trip; no query, because finding states by anything but their id is a read model's
job. The state is opaque here: a dict the activator serialises and rebuilds, which neither
the port nor an adapter reads.

The activator is the port's one caller, on behalf of the agent that declared its state with
``eda.state(...)``; an agent never meets the store, any more than it meets the broker.
"""

from typing import Protocol


class StaleVersion(RuntimeError):
    """A commit named a version that is no longer the current one: somebody else wrote first."""


class StateStore(Protocol):
    async def create(self, request_event_id: str) -> int:
        """Insert an empty state under the event that requested it, and return its id.

        The event's id is unique on the table, so a redelivered request finds the state it
        already created instead of creating a second one.
        """
        ...

    async def load(self, id: int) -> tuple[dict, int] | None:
        """The state's document and its version, or None where no such state exists."""
        ...

    async def handled(self, id: int, event_id: str) -> bool:
        """Whether this event already changed this state."""
        ...

    async def commit(self, id: int, state: dict, expected_version: int, event_id: str) -> None:
        """Write the state, bump its version, and record the event as handled, in one transaction.

        Refused with ``StaleVersion`` when the state's version is no longer ``expected_version``.
        """
        ...
