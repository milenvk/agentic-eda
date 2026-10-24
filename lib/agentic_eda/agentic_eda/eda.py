"""Everything an agent's module imports to join the event-driven architecture.

    from agentic_eda import eda

    consumes = eda.consumes(ItineraryRequested)
    produces = eda.produces(ItineraryProposed)
    eda.attach(app, agent, consumes=consumes, produces=produces)

An agent that owns business state declares it beside its events, and reads it from the
running activation:

    eda.attach(app, agent, consumes=..., produces=..., state=eda.state(Trip, key="trip_id"))

    trip = eda.activation().state
"""

from .activator import activation, attach, consumes, produces, publish, state
from .contracts import EventContract, Nothing, event

__all__ = [
    "EventContract",
    "Nothing",
    "activation",
    "attach",
    "consumes",
    "event",
    "produces",
    "publish",
    "state",
]
