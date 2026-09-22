"""Everything an agent's module imports to join the event-driven architecture.

    from travel_agency import eda

    consumes = eda.consumes(ItineraryRequested)
    produces = eda.produces(ItineraryProposed)
    eda.attach(app, agent, consumes=consumes, produces=produces)
"""

from .container import attach, consumes, produces, publish
from .events import OWN_ID, EventModel, Nothing, event

__all__ = [
    "OWN_ID",
    "EventModel",
    "Nothing",
    "attach",
    "consumes",
    "event",
    "produces",
    "publish",
]
