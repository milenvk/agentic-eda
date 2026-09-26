"""The CloudEvents context attributes: what an event says about itself, apart from its data.

Shared by the port, whose wire event is these attributes plus data, and by the event
contracts, which carry a copy of them beside their data. Neither module imports the other.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ContextAttributes(BaseModel, extra="allow", frozen=True):
    """What a CloudEvent says about itself: everything but the fact.

    The declared fields are the spec's context attributes. Anything else on the
    wire is an extension attribute, kept by ``extra="allow"`` and read by its own
    name (``event.correlationid`` from chapter 2). Extensions may be strings,
    integers or booleans by the spec; this system's own are strings.
    """

    specversion: Literal["1.0"] = "1.0"
    id: str
    type: str
    source: str
    time: datetime | None = None
    datacontenttype: str | None = None
    dataschema: str | None = None
    subject: str | None = None
    __pydantic_extra__: dict[str, str | int | bool] = Field(init=False)
