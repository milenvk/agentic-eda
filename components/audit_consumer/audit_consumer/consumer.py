"""The Audit Consumer — deterministic code, and it stays that way for the whole book.

Appends every event it sees to a durable, append-only record. Auditing involves
no reasoning, so it never needs an LLM. The publishers never know it exists.
"""

import json
import logging

from travel_agency.broker import Event

SOURCE = "AuditConsumer"

log = logging.getLogger(SOURCE)


def audit_line(event: Event) -> str:
    """One JSON line per event — the full fact, exactly as received."""
    return json.dumps(
        {
            "id": event.id,
            "type": event.type,
            "source": event.source,
            "attributes": event.attributes,
            "payload": event.payload,
        }
    )


async def record(log_path: str, event: Event) -> None:
    with open(log_path, "a") as record_file:
        record_file.write(audit_line(event) + "\n")
    log.info("recorded %s %s", event.type, event.id)
