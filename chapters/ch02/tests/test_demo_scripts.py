"""Chapter-level tests: what the three demo scripts publish, and how a reply is matched."""

import pytest
from malformed_request import NOT_A_TRIP
from overlapping_requests import nairobi_trip, sydney_trip
from pydantic import ValidationError
from request_trip import answers, lisbon_trip, request_itineraries

from agentic_eda.broker import Event
from travel_agency.event_types import ITINERARY_PROPOSED, ITINERARY_REQUESTED
from travel_agency.events.planning import ItineraryRequested
from travel_agency.sims import world


class RecordingBroker:
    def __init__(self) -> None:
        self.published: list[Event] = []

    async def publish(self, event_type, source, data, id=None, attributes=None) -> Event:
        event = Event(id=id or "e-1", type=event_type, source=source, data=data, **attributes)
        self.published.append(event)
        return event


def proposal(**attributes) -> Event:
    return Event(id="p-1", type=ITINERARY_PROPOSED, source="Planner", data={}, **attributes)


def test_the_running_example_is_the_trip_chapter_1_opens_with():
    trip = lisbon_trip()
    assert trip.origin == "New York"
    assert [stop.city for stop in trip.stops] == ["Madrid", "Lisbon"]
    assert (trip.stops[0].depart - trip.stops[0].arrive).days == 3  # three days in Madrid
    assert trip.travellers == 2


async def test_a_request_starts_a_thread_and_is_ordered_within_its_trip():
    broker = RecordingBroker()
    trip = lisbon_trip()

    request = await request_itineraries(broker, trip)

    assert request.type == ITINERARY_REQUESTED
    assert request.partitionkey == trip.trip_id
    assert request.correlationid not in (request.id, trip.trip_id)  # a label of its own
    assert ItineraryRequested.model_validate(request.data) == trip.model_copy(
        update={"attributes_": None}
    )


async def test_every_request_is_a_thread_of_its_own():
    broker = RecordingBroker()
    first = await request_itineraries(broker, nairobi_trip())
    second = await request_itineraries(broker, sydney_trip())
    assert first.correlationid != second.correlationid
    assert first.partitionkey != second.partitionkey


async def test_a_proposal_answers_the_request_sharing_its_correlation_id():
    request = await request_itineraries(RecordingBroker(), lisbon_trip())

    assert answers(request, proposal(correlationid=request.correlationid))
    assert not answers(request, proposal(correlationid="another-thread"))
    assert not answers(request, proposal())  # an event outside any thread


def test_the_malformed_request_breaks_the_contract_in_three_places():
    with pytest.raises(ValidationError) as rejected:
        ItineraryRequested.model_validate(NOT_A_TRIP)
    broken = {error["loc"][0] for error in rejected.value.errors()}
    assert broken == {"stops", "travellers", "budget"}


@pytest.mark.parametrize("trip", [lisbon_trip(), nairobi_trip(), sydney_trip()])
def test_every_city_a_demo_names_is_one_the_suppliers_know(trip):
    for city in [trip.origin, *(stop.city for stop in trip.stops)]:
        assert len(world.find_cities(city)) == 1, city
