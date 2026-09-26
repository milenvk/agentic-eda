"""Console rendering and log hygiene for demo scripts and components.

The demos exist to show events moving between components, so what gets printed
is the event: its attributes and its data, with long values
truncated. Harness tooling for every chapter's scripts — never a book listing.
"""

import json
import logging
import os
import sys

from .broker import WireEvent

_VALUE_WIDTH = 120
_RULE = "─" * 72


def _use_color() -> bool:
    # Containers logging through `docker compose logs` have no TTY, but their
    # bytes reach a terminal — FORCE_COLOR (set in the compose files) says so.
    if "NO_COLOR" in os.environ:
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty()


def _paint(text: str, code: str) -> str:
    if not _use_color():
        return text
    return f"\033[{code}m{text}\033[0m"


def _clip(value: object) -> str:
    text = value if isinstance(value, str) else json.dumps(value)
    original_length = len(text)
    # A card row stays one line: newlines and runs of whitespace collapse.
    text = " ".join(text.split())
    if original_length <= _VALUE_WIDTH:
        return text
    return f"{text[:_VALUE_WIDTH]}… [truncated: {original_length:,} chars total]"


def format_event(action: str, event: WireEvent) -> str:
    """One event as a card. `action` is what just happened to it, e.g.
    'PUBLISHED' or 'RECEIVED'."""
    color = "32" if action == "PUBLISHED" else "36"  # green / cyan
    lines = [
        _RULE,
        f"{_paint(action, '1;' + color)}  {_paint(event.type, '1')}",
        f"  {_paint('id', '2')}      {event.id}",
        f"  {_paint('source', '2')}  {event.source}",
    ]
    # Every other attribute the event carries, in the order it declares them:
    # the optional standard ones first, then the extensions (chapter 2 onward).
    attributes = event.model_dump(mode="json", exclude={"data"}, exclude_none=True)
    for name, value in attributes.items():
        if name not in ("id", "source", "type", "specversion"):
            lines.append(f"  {_paint(name, '2')}  {_clip(value)}")
    lines.append(f"  {_paint('data', '2')}")
    for name, value in event.data.items():
        lines.append(f"    {_paint(name, '2')}  {_clip(value)}")
    lines.append(_RULE)
    return "\n".join(lines)


def show(action: str, event: WireEvent) -> None:
    print(format_event(action, event), flush=True)


def success(text: str) -> None:
    """A green check for a demo milestone."""
    print(f"{_paint('✔', '1;32')} {text}", flush=True)


def quiet_client_logs() -> None:
    """Reduce client-library logging to errors and real problems.

    The Kafka client, LiteLLM, and its HTTP client all log routine chatter.
    What stays visible at ERROR includes Kafka's routine fresh-start reports
    (an unknown topic before the first event is published to it, coordinator
    election on first contact): the demos explain those rather than hide them.
    """
    logging.getLogger("aiokafka").setLevel(logging.ERROR)
    logging.getLogger("LiteLLM").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def configure_logging() -> None:
    """Standard component logging: the component's own lines and the event
    cards at INFO, client libraries reduced to real problems."""
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    quiet_client_logs()
