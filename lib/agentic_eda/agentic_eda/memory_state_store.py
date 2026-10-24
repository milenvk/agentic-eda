"""In-memory adapter for the StateStore port, for tests and nothing else."""

from .state import StaleVersion


class InMemoryStateStore:
    def __init__(self) -> None:
        self.rows: dict[int, dict] = {}  # id -> {"request_event_id", "state", "version"}
        self.handled_events: set[tuple[int, str]] = set()

    async def create(self, request_event_id: str) -> int:
        for id, row in self.rows.items():
            if row["request_event_id"] == request_event_id:
                return id
        id = len(self.rows) + 1
        self.rows[id] = {"request_event_id": request_event_id, "state": {}, "version": 0}
        return id

    async def load(self, id: int) -> tuple[dict, int] | None:
        row = self.rows.get(id)
        return None if row is None else (dict(row["state"]), row["version"])

    async def handled(self, id: int, event_id: str) -> bool:
        return (id, event_id) in self.handled_events

    async def commit(self, id: int, state: dict, expected_version: int, event_id: str) -> None:
        row = self.rows[id]
        if row["version"] != expected_version:
            raise StaleVersion(f"state {id} is at version {row['version']}, not {expected_version}")
        row["state"] = dict(state)
        row["version"] += 1
        self.handled_events.add((id, event_id))
