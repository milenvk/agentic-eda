"""Everything an agent's module imports to join the event-driven architecture.

    from agentic_eda import eda

    consumes = eda.consumes(ItineraryRequested)
    produces = eda.produces(ItineraryProposed)
    eda.attach(app, agent, consumes=consumes, produces=produces)
"""

from .activator import attach, consumes, produces, publish
from .contracts import EventContract, Nothing, event

__all__ = [
    "EventContract",
    "Nothing",
    "attach",
    "consumes",
    "event",
    "produces",
    "publish",
]
