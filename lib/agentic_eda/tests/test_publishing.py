"""Unit tests for publish_fact and derived_id: an event instance published with its type, its key, and its id."""

import uuid

from examples import ITINERARY_REQUESTED, REQUEST, ItineraryRequested

from agentic_eda.broker import WireEvent
from agentic_eda.contracts import EventContract, event
from agentic_eda.publishing import derived_id, publish_fact


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
    attributes = {"correlationid": "workflow-7"}

    published = await publish_fact(RecordingBroker(), "RequestTripScript", request, attributes)

    assert published.correlationid == "workflow-7"
    assert attributes == {"correlationid": "workflow-7"}  # the caller's dictionary is left alone


async def test_an_event_declaring_no_order_is_published_without_a_key():
    @event("system.SweepDue")
    class SweepDue(EventContract):
        pass

    published = await publish_fact(RecordingBroker(), "Scheduler", SweepDue())

    assert not hasattr(published, "partitionkey")


def test_a_derived_id_repeats_for_one_cause_and_tells_the_rest_apart():
    one = derived_id("Planner", "req-1", "planning.ItineraryProposed", 0)

    assert one == derived_id("Planner", "req-1", "planning.ItineraryProposed", 0)
    assert uuid.UUID(one).version == 5 and len(one) == 36  # a fixed-length hash, whatever the depth
    others = {
        derived_id("Booking", "req-1", "planning.ItineraryProposed", 0),  # another component
        derived_id("Planner", "req-1", "planning.ItineraryRequestSuperseded", 0),  # another type
        derived_id("Planner", "req-1", "planning.ItineraryProposed", 1),  # the next of its type
        derived_id("Planner", "req-2", "planning.ItineraryProposed", 0),  # another cause
    }
    assert one not in others and len(others) == 4


async def test_a_publisher_passes_the_id_it_derived():
    request = ItineraryRequested.model_validate(REQUEST)

    class KeepingBroker(RecordingBroker):
        async def publish(self, event_type, source, data, id=None, attributes=None):
            return WireEvent(id=id or "generated", type=event_type, source=source, data=data, **(attributes or {}))  # fmt: skip

    derived = await publish_fact(KeepingBroker(), "Script", request, id="derived-1")
    generated = await publish_fact(KeepingBroker(), "Script", request)

    assert (derived.id, generated.id) == ("derived-1", "generated")
