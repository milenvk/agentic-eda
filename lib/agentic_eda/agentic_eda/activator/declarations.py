"""What an agent's module declares: the events it reacts to, the events it answers with,
and, for an agent that owns business state, the class holding that state."""

from dataclasses import dataclass
from types import NoneType
from typing import Annotated, Union, get_args

from pydantic import BaseModel, Field, ValidationError, create_model

from ..contracts import EventContract, Nothing, binding_of


@dataclass(frozen=True)
class Consumes:
    classes: tuple[type[EventContract], ...]
    interrupting: frozenset[type[EventContract]]

    def by_type(self) -> dict[str, type[EventContract]]:
        return {binding_of(cls).type: cls for cls in self.classes}


class PureConsumer:
    """What ``produces()`` with no classes returns: an agent that answers with nothing."""


@dataclass(frozen=True)
class State:
    cls: type[BaseModel]
    key: str


def consumes(*classes: type[EventContract], interrupting=()) -> Consumes:
    """The event classes an agent reacts to, checked the moment the module loads.

    An option about particular classes names them, and they are among the declared ones.
    """
    for cls in classes:
        _require_event(cls)
    strangers = [cls.__name__ for cls in interrupting if cls not in classes]
    if strangers:
        raise TypeError(f"interrupting names classes not among the consumed ones: {strangers}")
    return Consumes(classes=tuple(classes), interrupting=frozenset(interrupting))


def produces(*classes: type[EventContract]):
    """The event classes an agent answers with, which is also its typed-output schema.

    One class comes back as itself. Wherever there is a choice, several classes or a
    class and ``Nothing``, a wrapper comes back holding their union under one field,
    because a strict schema wants an object at its root and refuses a union there. Hand
    the result to the framework's typed-output line either way.
    """
    if not classes:
        return PureConsumer
    for cls in classes:
        if cls is not Nothing:
            _require_event(cls)
            _require_strict(cls)
    if len(classes) == 1 and classes[0] is not Nothing:
        return classes[0]
    members = Union[classes]  # noqa: UP007 - built at run time from the declared classes
    fact = (
        (Annotated[members, Field(discriminator="event_type")], ...)
        if len(classes) > 1
        else (members, ...)
    )
    answer = create_model("Answer", fact=fact)
    answer.__produces__ = tuple(classes)
    return answer


def state(cls: type[BaseModel], *, key: str) -> State:
    """The class holding the agent's business state, and the field naming one state's id.

    The activator loads the state whose id a consumed event carries in that field, and
    creates one for an event whose class has no such field, which is how a request becomes
    a trip. A new state is built from its id alone, so every other field has a default.
    """
    if not (isinstance(cls, type) and issubclass(cls, BaseModel)):
        raise TypeError(f"{cls!r} is not a Pydantic class")
    if key not in cls.model_fields:
        raise TypeError(f"{cls.__name__} has no field {key!r} to hold its id")
    try:
        cls.model_validate({key: 0})
    except ValidationError as error:
        raise TypeError(
            f"a new {cls.__name__} is built from its {key} alone, so every other field "
            f"needs a default:\n{error}"
        ) from error
    return State(cls=cls, key=key)


def produced_classes(declaration) -> tuple[type[EventContract], ...]:
    """The classes behind whatever ``produces`` returned."""
    if declaration is PureConsumer:
        return ()
    return getattr(declaration, "__produces__", (declaration,))


def _require_event(cls: type) -> None:
    if binding_of(cls) is None:
        raise TypeError(f"{getattr(cls, '__name__', cls)!r} is not an @event class")


def _require_strict(cls: type[BaseModel]) -> None:
    # A strict schema makes every property required, so a field that may be left out is
    # written as a union with None, which a model can still answer.
    for name, field in cls.model_fields.items():
        if name in ("attributes_", "event_type") or field.is_required():
            continue
        if NoneType not in get_args(field.annotation):
            raise TypeError(
                f"{cls.__name__}.{name} may be left out and cannot be null, which a strict "
                f"schema cannot express: declare it as `{name}: ... | None = None`"
            )
