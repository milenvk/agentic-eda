"""PostgreSQL adapter for the StateStore port.

Two tables, created on first use if they are missing. The state table, named by the
component's configuration (``trips`` for the Booking Agent), holds one row per state: a
serial ``id``, the ``request_event_id`` that created it under a unique index, the
``version``, and the ``state`` document as JSONB, with the document's ``status`` copied
into a column for anyone reading the table. ``handled_events`` holds one row per event that
changed a state, which is how a redelivered event is recognised.
"""

from psycopg import sql
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from .state import StaleVersion

_SCHEMA = """
CREATE TABLE IF NOT EXISTS {table} (
    id SERIAL PRIMARY KEY,
    request_event_id TEXT NOT NULL UNIQUE,
    version INTEGER NOT NULL DEFAULT 0,
    state JSONB NOT NULL DEFAULT '{{}}',
    status TEXT GENERATED ALWAYS AS (state->>'status') STORED
);
CREATE TABLE IF NOT EXISTS handled_events (
    state_id INTEGER NOT NULL REFERENCES {table}(id),
    event_id TEXT NOT NULL,
    PRIMARY KEY (state_id, event_id)
);
"""


class PostgresStateStore:
    def __init__(self, conninfo: str, table: str, client_name: str = "agentic_eda") -> None:
        self._table = sql.Identifier(table)
        self._pool = AsyncConnectionPool(
            conninfo, open=False, kwargs={"application_name": client_name}
        )

    async def __aenter__(self) -> "PostgresStateStore":
        await self._pool.open()
        async with self._pool.connection() as connection:
            await connection.execute(sql.SQL(_SCHEMA).format(table=self._table))
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._pool.close()

    async def create(self, request_event_id: str) -> int:
        async with self._pool.connection() as connection:
            inserted = await connection.execute(
                sql.SQL(
                    "INSERT INTO {table} (request_event_id) VALUES (%s) "
                    "ON CONFLICT (request_event_id) DO NOTHING RETURNING id"
                ).format(table=self._table),
                (request_event_id,),
            )
            row = await inserted.fetchone()
            if row is None:  # the request already created its state
                found = await connection.execute(
                    sql.SQL("SELECT id FROM {table} WHERE request_event_id = %s").format(
                        table=self._table
                    ),
                    (request_event_id,),
                )
                row = await found.fetchone()
            return row[0]

    async def load(self, id: int) -> tuple[dict, int] | None:
        async with self._pool.connection() as connection:
            selected = await connection.execute(
                sql.SQL("SELECT state, version FROM {table} WHERE id = %s").format(
                    table=self._table
                ),
                (id,),
            )
            row = await selected.fetchone()
            return None if row is None else (row[0], row[1])

    async def handled(self, id: int, event_id: str) -> bool:
        async with self._pool.connection() as connection:
            selected = await connection.execute(
                "SELECT 1 FROM handled_events WHERE state_id = %s AND event_id = %s",
                (id, event_id),
            )
            return await selected.fetchone() is not None

    async def commit(self, id: int, state: dict, expected_version: int, event_id: str) -> None:
        async with self._pool.connection() as connection, connection.transaction():
            updated = await connection.execute(
                sql.SQL(
                    "UPDATE {table} SET state = %s, version = version + 1 "
                    "WHERE id = %s AND version = %s"
                ).format(table=self._table),
                (Jsonb(state), id, expected_version),
            )
            if updated.rowcount != 1:
                raise StaleVersion(f"state {id} is no longer at version {expected_version}")
            await connection.execute(
                "INSERT INTO handled_events (state_id, event_id) VALUES (%s, %s)",
                (id, event_id),
            )
