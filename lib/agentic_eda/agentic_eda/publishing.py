"""Publishing an event instance: the one place its type and its ordering key are derived.

The activator publishes every answer through ``publish_fact``, and so does any publisher
outside an activation: a demo script, an edge adapter, a relay. An event's key is therefore
the same whichever of them publishes it, because it is read from the event's own data.
"""

from .broker import PARTITION_KEY, EventBroker, WireEvent
from .contracts import EventContract, binding_of, data_of, key_of


async def publish_fact(
    broker: EventBroker,
    source: str,
    fact: EventContract,
    attributes: dict[str, str] | None = None,
) -> WireEvent:
    """Publish an event instance through the port.

    The type and the key are taken from the event's class, and the data from its fields.
    ``attributes`` holds what only the publisher knows, such as the workflow's
    ``correlationid``.
    """
    attributes = dict(attributes or {})
    key = key_of(fact)
    if key is not None:
        attributes[PARTITION_KEY] = key
    return await broker.publish(
        binding_of(fact).type, source, data_of(fact), attributes=attributes
    )
