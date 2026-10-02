"""Event contracts: one Pydantic class per kind of event, bound with ``@event``.

An ``@event`` class is the contract for a kind of event: what its data holds, which
type names it on the wire, and, for an event with an order to keep, which of its
fields that order is kept within. The ``WireEvent`` of the port is a different thing: one occurrence on the wire, the envelope
around that data.
"""

from dataclasses import dataclass
from types import NoneType
from typing import Literal, get_args

from pydantic import BaseModel, create_model
from pydantic.json_schema import SkipJsonSchema

from .envelope import ContextAttributes


# The two fields of an event class that are not its data: the envelope carries both.
NOT_DATA = {"attributes_", "event_type"}


class EventContract(BaseModel):
    """The base of every event class: its data, with the event's attributes beside it.

    ``attributes_`` is filled by the activator on the way in and overwritten on the
    way out. It is left out of the JSON schema, so a model reads it and is never asked
    to fill it.
    """

    attributes_: SkipJsonSchema[ContextAttributes | None] = None


class Nothing(EventContract):
    """The answer of an agent that decided to publish nothing, and why.

    A positive answer rather than silence: the activator logs the reason and publishes
    nothing, and an agent that simply failed to answer is still caught.
    """

    event_type: Literal["nothing"] = "nothing"
    reason: str


@dataclass(frozen=True)
class Binding:
    """What ``@event`` records about a class: its type on the wire and its ordering."""

    type: str
    order_per: str | None


def data_of(fact: EventContract) -> dict:
    """An event's data as it is published: its own fields, as JSON values.

    An optional field left at its default is left out, as an unset attribute of the
    envelope is. A required field is always there, null included. Nothing stated is lost
    that way, because `@event` refuses a class with any default other than None.
    """
    return fact.model_dump(mode="json", exclude=NOT_DATA, exclude_defaults=True)


def key_of(fact: EventContract) -> str | None:
    """The key an event is ordered by: the value of the field named by its class, if any.

    The key is read from the event's own data, so every publisher of the event computes
    the same one.
    """
    order_per = binding_of(fact).order_per
    return None if order_per is None else str(getattr(fact, order_per))


def meanings_of(contract: type[BaseModel]) -> str:
    """What a contract's fields mean, as text for a prompt.

    Each class of the contract is one line with its docstring. Beneath it, one line per
    field that has a description or holds another class, which the line names:
    `budget (Money or null): Upper limit for the whole trip.` The text is read from the
    contract's JSON Schema, so an LLM is told what any other reader of the schema is told.
    """
    schema = contract.model_json_schema()
    classes = {schema["title"]: schema, **schema.get("$defs", {})}
    lines = []
    for name, described in classes.items():
        fields = [_meaning(*field) for field in described.get("properties", {}).items()]
        fields = [line for line in fields if line]
        if "description" in described or fields:
            lines += [f"{name}: {described.get('description', '')}".rstrip(": "), *fields]
    return "\n".join(lines)


def _meaning(field: str, about: dict) -> str:
    """One field's line, or nothing where the schema says nothing beyond its plain type."""
    held = _classes_held(about)
    name = f"{field} ({held})" if held else field
    if "description" in about:
        return f"  {name}: {about['description']}"
    return f"  {name}" if held else ""


def _classes_held(about: dict) -> str:
    """The classes a field holds, in words: `Money or null`, `list of Stay`."""
    if "$ref" in about:
        return about["$ref"].rsplit("/", 1)[-1]
    if about.get("type") == "array":
        held = _classes_held(about.get("items", {}))
        return f"list of {held}" if held else ""
    options = about.get("anyOf") or about.get("oneOf") or []
    held = [_classes_held(option) for option in options]
    if not any(held):
        return ""  # plain values only
    return " or ".join(one or option["type"] for one, option in zip(held, options, strict=True))


def binding_of(subject: object) -> Binding | None:
    """The binding of an event class or of an instance of one, if it has one."""
    cls = subject if isinstance(subject, type) else type(subject)
    return getattr(cls, "__event__", None)


def event(*args, order_per: str | None = None):
    """Bind a class to its event type and, for an event with an order to keep, to the
    field that order is kept within.

    As a decorator, on a class of your own::

        @event(ITINERARY_PROPOSED, order_per="trip_id")
        class ItineraryProposed(EventContract): ...

    As a function, on a class you do not own, which comes back as a subclass an agent
    still receives as an instance of its own class::

        TripRequest = event(TripRequest, ITINERARY_REQUESTED, order_per="trip_id")

    ``order_per`` names a required field holding the id of the subject of the events, such
    as a trip. Events sharing that field's value are delivered in publish order, one at a
    time, and nothing is promised across values. Without ``order_per`` no order is kept:
    the event is published without a key.
    """
    if args and isinstance(args[0], type):
        cls, event_type = args
        return _bind(cls, event_type, order_per)
    (event_type,) = args
    return lambda cls: _bind(cls, event_type, order_per)


def _bind(cls: type[BaseModel], event_type: str, order_per) -> type[EventContract]:
    _require_no_default_but_none(cls, checked=set())
    bases = (cls,) if issubclass(cls, EventContract) else (cls, EventContract)
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
    if order_per is not None:
        _require_a_value_to_order_by(bound, order_per)
    bound.__event__ = Binding(type=event_type, order_per=order_per)
    return bound


def _require_a_value_to_order_by(cls: type[BaseModel], order_per: str) -> None:
    """An event's order is kept within a value, so the field is there on every event."""
    field = cls.model_fields.get(order_per)
    if field is None:
        raise TypeError(f"{cls.__name__} has no field {order_per!r} to keep its order within")
    if not field.is_required() or NoneType in get_args(field.annotation):
        raise TypeError(
            f"{cls.__name__}.{order_per} may be missing or null, and events without a "
            f"value there would share one key: make the field required"
        )


def _require_no_default_but_none(cls: type[BaseModel], checked: set[type]) -> None:
    """A default is left out of the published data, so the only one allowed says nothing."""
    checked.add(cls)
    for name, field in cls.model_fields.items():
        if name in NOT_DATA:
            continue
        if not field.is_required() and (field.default_factory or field.default is not None):
            raise TypeError(
                f"{cls.__name__}.{name} has a default, which would be missing from the "
                f"published data: make it required, or declare `{name}: ... | None = None`"
            )
        for nested in _classes_in(field.annotation):
            if nested not in checked:
                _require_no_default_but_none(nested, checked)


def _classes_in(annotation) -> list[type[BaseModel]]:
    """The Pydantic classes an annotation names, however deep: `list[Stop]`, `Money | None`."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    return [cls for part in get_args(annotation) for cls in _classes_in(part)]
