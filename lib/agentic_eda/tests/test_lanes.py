"""Unit tests for the lanes: per-key order, cross-key concurrency, the cap, the watermark."""

import asyncio

import pytest

from travel_agency.lanes import Lanes, Watermark


class Gate:
    """Work that blocks until released, recording when it starts and ends."""

    def __init__(self, log: list[str], name: str) -> None:
        self.log = log
        self.name = name
        self.release = asyncio.Event()

    async def __call__(self) -> None:
        self.log.append(f"start {self.name}")
        await self.release.wait()
        self.log.append(f"end {self.name}")


async def settle() -> None:
    """Let every task that is ready run to its next wait."""
    for _ in range(5):
        await asyncio.sleep(0)


async def test_work_sharing_a_key_runs_one_at_a_time_in_order():
    lanes, log = Lanes(), []
    first, second = Gate(log, "1"), Gate(log, "2")
    lanes.submit("trip-1", first)
    lanes.submit("trip-1", second)
    await settle()
    assert log == ["start 1"]

    first.release.set()
    await settle()
    assert log == ["start 1", "end 1", "start 2"]

    second.release.set()
    await settle()
    assert log == ["start 1", "end 1", "start 2", "end 2"]
    assert lanes.in_flight == 0


async def test_work_of_different_keys_runs_concurrently():
    lanes, log = Lanes(), []
    gates = [Gate(log, name) for name in "abc"]
    for gate in gates:
        lanes.submit(gate.name, gate)
    await settle()
    assert log == ["start a", "start b", "start c"]
    assert lanes.in_flight == 3

    for gate in gates:
        gate.release.set()
    await settle()
    assert lanes.in_flight == 0


async def test_the_cap_counts_work_across_every_key():
    lanes, log = Lanes(max_in_flight=2), []
    first, second = Gate(log, "a"), Gate(log, "b")
    lanes.submit("a", first)
    assert not lanes.full
    lanes.submit("b", second)
    assert lanes.full

    first.release.set()
    await settle()
    assert not lanes.full
    assert lanes.in_flight == 1
    second.release.set()


async def test_a_failure_stops_its_lane_and_surfaces_on_check():
    lanes, log = Lanes(), []

    async def failing() -> None:
        raise RuntimeError("killed mid-inference")

    behind = Gate(log, "behind")
    other = Gate(log, "other")
    lanes.submit("trip-1", failing)
    lanes.submit("trip-1", behind)
    lanes.submit("trip-2", other)
    await settle()

    # The failed lane drops what was queued behind it; the other lane is untouched.
    assert log == ["start other"]
    assert lanes.in_flight == 1
    with pytest.raises(RuntimeError, match="mid-inference"):
        lanes.check()
    other.release.set()


async def test_close_cancels_unfinished_work():
    lanes, log = Lanes(), []
    lanes.submit("trip-1", Gate(log, "a"))
    lanes.submit("trip-1", Gate(log, "queued behind a"))
    lanes.submit("trip-2", Gate(log, "b"))
    await settle()
    await lanes.close()
    assert log == ["start a", "start b"]
    assert lanes.in_flight == 0  # the running and the queued alike


def test_nothing_to_commit_before_anything_finishes():
    watermark = Watermark()
    watermark.fetched("p0", 5)
    watermark.fetched("p0", 6)
    assert watermark.advanced() == {}


def test_the_position_advances_past_the_finished_prefix_only():
    watermark = Watermark()
    for offset in (5, 6, 7):
        watermark.fetched("p0", offset)

    watermark.finished("p0", 5)
    assert watermark.advanced() == {"p0": 6}
    watermark.finished("p0", 7)
    assert watermark.advanced() == {}  # 6 is still in flight
    watermark.finished("p0", 6)
    assert watermark.advanced() == {"p0": 8}


def test_a_move_is_reported_once():
    watermark = Watermark()
    watermark.fetched("p0", 0)
    watermark.finished("p0", 0)
    assert watermark.advanced() == {"p0": 1}
    assert watermark.advanced() == {}


def test_partitions_are_tracked_independently():
    watermark = Watermark()
    watermark.fetched("p0", 0)
    watermark.fetched("p1", 40)
    watermark.finished("p1", 40)
    assert watermark.advanced() == {"p1": 41}


def test_a_forgotten_partition_ignores_late_finishes():
    watermark = Watermark()
    watermark.fetched("p0", 0)
    watermark.forget(["p0"])
    watermark.finished("p0", 0)
    assert watermark.advanced() == {}
