"""Unit tests for publish_fact: an event instance published with its type and its key."""

from examples import ITINERARY_REQUESTED, REQUEST, ItineraryRequested

from agentic_eda.broker import WireEvent
from agentic_eda.contracts import EventContract, event
from agentic_eda.publishing import publish_fact


class RecordingBroker:
    async def publish(self, event_type, source, data, id=None, attributes=None) -> WireEvent:
        return WireEvent(id="e-1", type=event_type, source=source, data=data, **(attributes or {}))


async def test_the_type_the_data_and_the_key_come_from_the_event():
    request = ItineraryRequested.model_validate(REQUEST)

    published = await publish_fact(RecordingBroker(), "RequestTripScript", request)

    assert published.type == ITINERARY_REQUESTED
    assert published.source == "RequestTripScript"
    assert published.data == REQUEST
    assert published.partitionkey == "trip-1"


async def test_the_publisher_adds_what_only_it_knows():
    request = ItineraryRequested.model_validate(REQUEST)
    attributes = {"correlationid": "thread-7"}

    published = await publish_fact(RecordingBroker(), "RequestTripScript", request, attributes)

    assert published.correlationid == "thread-7"
    assert attributes == {"correlationid": "thread-7"}  # the caller's dictionary is left alone


async def test_an_event_declaring_no_order_is_published_without_a_key():
    @event("system.SweepDue")
    class SweepDue(EventContract):
        pass

    published = await publish_fact(RecordingBroker(), "Scheduler", SweepDue())

    assert not hasattr(published, "partitionkey")
