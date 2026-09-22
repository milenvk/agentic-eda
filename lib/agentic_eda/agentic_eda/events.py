"""Event contracts: one Pydantic class per kind of event, bound with ``@event``.

An ``@event`` class is the contract for a kind of event: what its data holds, which
type names it on the wire, and which of its fields its order is kept within. The
``Event`` of the port is a different thing: one occurrence on the wire, the envelope
around that data.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, create_model
from pydantic.json_schema import SkipJsonSchema

from .broker import EventAttributes


class _OwnId:
    def __repr__(self) -> str:
        return "OWN_ID"


# For the event that starts a sequence: it is keyed on its own id, which the events
# that follow it then share.
OWN_ID = _OwnId()

_UNSET = object()


class EventModel(BaseModel):
    """The base of every event class: its data, with the event's attributes beside it.

    ``attributes_`` is filled by the container on the way in and overwritten on the
    way out. It is left out of the JSON schema, so a model reads it and is never asked
    to fill it.
    """

    attributes_: SkipJsonSchema[EventAttributes | None] = None


class Nothing(EventModel):
    """The answer of an agent that decided to publish nothing, and why.

    A positive answer rather than silence: the container logs the reason and publishes
    nothing, and an agent that simply failed to answer is still caught.
    """

    event_type: Literal["nothing"] = "nothing"
    reason: str


@dataclass(frozen=True)
class Binding:
    """What ``@event`` records about a class: its type on the wire and its ordering."""

    type: str
    order_per: str | _OwnId | None


def data_of(fact: EventModel) -> dict:
    """An event's data as it is published: its own fields, as JSON values."""
    return fact.model_dump(mode="json", exclude={"attributes_", "event_type"})


def binding_of(subject: object) -> Binding | None:
    """The binding of an event class or of an instance of one, if it has one."""
    cls = subject if isinstance(subject, type) else type(subject)
    return getattr(cls, "__event__", None)


def event(*args, order_per: str | _OwnId | None = _UNSET):
    """Bind a class to its event type and to the field its order is kept within.

    As a decorator, on a class of your own::

        @event(ITINERARY_PROPOSED, order_per="trip_id")
        class ItineraryProposed(EventModel): ...

    As a function, on a class you do not own, which comes back as a subclass an agent
    still receives as an instance of its own class::

        TripRequest = event(TripRequest, ITINERARY_REQUESTED, order_per="trip_id")

    ``order_per`` is never left unsaid. Events sharing that field's value are delivered
    in publish order, one at a time, and nothing is promised across values. ``OWN_ID``
    is for the event that starts a sequence, and ``None`` declares an event nothing
    orders.
    """
    if order_per is _UNSET:
        raise TypeError(
            "declare order_per: the field this event's order is kept within, OWN_ID "
            "for the event that starts a sequence, or None for an event nothing orders"
        )
    if args and isinstance(args[0], type):
        cls, event_type = args
        return _bind(cls, event_type, order_per)
    (event_type,) = args
    return lambda cls: _bind(cls, event_type, order_per)


def _bind(cls: type[BaseModel], event_type: str, order_per) -> type[EventModel]:
    bases = (cls,) if issubclass(cls, EventModel) else (cls, EventModel)
    bound = create_model(
        cls.__name__,
        __base__=bases,
        __module__=cls.__module__,
        __doc__=cls.__doc__,
        # What makes a union of event classes discriminated, and what a model's answer
        # names itself with. It never travels in the data: the envelope carries the type.
        event_type=(Literal[event_type], event_type),
    )
    bound.__qualname__ = cls.__qualname__
    if isinstance(order_per, str) and order_per not in bound.model_fields:
        raise TypeError(f"{cls.__name__} has no field {order_per!r} to keep its order within")
    bound.__event__ = Binding(type=event_type, order_per=order_per)
    return bound
