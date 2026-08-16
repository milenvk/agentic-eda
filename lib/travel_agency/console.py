"""Console rendering for demo scripts.

The demos exist to show events moving between components, so what gets printed
is the event: id, type, source, attributes, and payload, with long values
truncated. Harness tooling for every chapter's scripts — never a book listing.
"""

import json
import os
import sys

from .broker import Event

_VALUE_WIDTH = 120
_RULE = "─" * 72


def _use_color() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def _paint(text: str, code: str) -> str:
    if not _use_color():
        return text
    return f"\033[{code}m{text}\033[0m"


def _clip(value: object) -> str:
    text = value if isinstance(value, str) else json.dumps(value)
    if len(text) <= _VALUE_WIDTH:
        return text
    return f"{text[:_VALUE_WIDTH]}… [truncated: {len(text):,} chars total]"


def format_event(action: str, event: Event) -> str:
    """One event as a card. `action` is what just happened to it, e.g.
    'PUBLISHED' or 'RECEIVED'."""
    color = "32" if action == "PUBLISHED" else "36"  # green / cyan
    lines = [
        _RULE,
        f"{_paint(action, '1;' + color)}  {_paint(event.type, '1')}",
        f"  {_paint('id', '2')}      {event.id}",
        f"  {_paint('source', '2')}  {event.source}",
    ]
    for name, value in event.attributes.items():
        lines.append(f"  {_paint(name, '2')}  {_clip(value)}")
    lines.append(f"  {_paint('payload', '2')}")
    for name, value in event.payload.items():
        lines.append(f"    {_paint(name, '2')}  {_clip(value)}")
    lines.append(_RULE)
    return "\n".join(lines)


def show(action: str, event: Event) -> None:
    print(format_event(action, event), flush=True)
