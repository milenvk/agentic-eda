"""Per-key lanes: order within a key, concurrency across keys, a cap on the whole.

The EventBroker contract promises that events sharing a ``partitionkey`` are
handled one at a time and in order. It says nothing about events of different
keys waiting for each other, and an agent's activation can run for a minute, so
an adapter that handled records one after another would keep every other key
waiting for that minute. Lanes are how an adapter runs many keys at once without
breaking the promise: one queue per key, drained by one task, and a cap on the
work in flight across all of them.

Nothing here belongs to Kafka. The Kafka adapter is the first user, and any
adapter over a broker that hands out records in per-key order can use the same
two classes. ``Watermark`` is for the log-shaped brokers, which take one
committed position per partition rather than an acknowledgement per record.
"""

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable, Hashable, Iterable

Work = Callable[[], Awaitable[None]]


class Lanes:
    """Runs work one at a time within a key and concurrently across keys.

    ``submit`` never waits: the work joins its key's queue, and one task per key
    drains that queue in submission order. ``max_in_flight`` caps the work
    submitted and not yet finished across all keys; the caller checks ``full``
    before fetching more.

    No locks: every method runs on the event loop's thread and none of them
    awaits, so no two calls interleave. A caller on another thread must go
    through ``loop.call_soon_threadsafe``.
    """

    def __init__(self, max_in_flight: int = 64) -> None:
        self._max_in_flight = max_in_flight
        self._queues: dict[Hashable, deque[Work]] = {}
        self._tasks: dict[Hashable, asyncio.Task] = {}
        self._in_flight = 0
        self._failure: Exception | None = None

    @property
    def in_flight(self) -> int:
        return self._in_flight

    @property
    def full(self) -> bool:
        return self._in_flight >= self._max_in_flight

    def submit(self, key: Hashable, work: Work) -> None:
        self._in_flight += 1
        if key in self._tasks:
            self._queues[key].append(work)
        else:
            self._queues[key] = deque([work])
            self._tasks[key] = asyncio.create_task(self._drain(key))

    async def _drain(self, key: Hashable) -> None:
        queue = self._queues[key]
        try:
            while queue:
                work = queue.popleft()
                try:
                    await work()
                finally:
                    self._in_flight -= 1
        except Exception as error:
            self._failure = self._failure or error  # the lane stops at its first failure
        finally:
            # Whatever is still queued, behind a failure or a cancellation, was never
            # acknowledged, so the broker delivers it again.
            self._in_flight -= len(queue)
            del self._tasks[key]
            del self._queues[key]

    def check(self) -> None:
        """Raise the first failure a lane has met, if any."""
        if self._failure is not None:
            raise self._failure

    async def close(self) -> None:
        """Cancel every lane. Unfinished work was never acknowledged, so it comes back."""
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class Watermark:
    """Per partition, the position below which every fetched record has finished.

    A log-backed broker takes one committed position per partition, so with
    records finishing in any order the position to commit is the first offset
    still in flight, or one past the last fetched when nothing is. After a
    crash everything from that position on comes back, finished or not, which
    is what at-least-once means.
    """

    def __init__(self) -> None:
        self._pending: dict[Hashable, dict[int, bool]] = {}  # offset -> finished, in fetch order
        self._position: dict[Hashable, int] = {}
        self._committed: dict[Hashable, int] = {}

    def fetched(self, partition: Hashable, offset: int) -> None:
        if partition not in self._position:
            self._position[partition] = self._committed[partition] = offset
        self._pending.setdefault(partition, {})[offset] = False

    def finished(self, partition: Hashable, offset: int) -> None:
        pending = self._pending.get(partition, {})
        if offset not in pending:
            return  # the partition was revoked meanwhile; its new owner has the record
        pending[offset] = True
        while pending:
            first = next(iter(pending))
            if not pending[first]:
                break
            del pending[first]
            self._position[partition] = first + 1

    def advanced(self) -> dict[Hashable, int]:
        """The positions moved since the last call: what to commit now."""
        moved = {
            partition: position
            for partition, position in self._position.items()
            if position != self._committed[partition]
        }
        self._committed.update(moved)
        return moved

    def forget(self, partitions: Iterable[Hashable]) -> None:
        for partition in partitions:
            self._pending.pop(partition, None)
            self._position.pop(partition, None)
            self._committed.pop(partition, None)
