"""Chapter-level tests: what the customer channel publishes, and how it reads what comes back."""

import asyncio
from datetime import date

from change_of_mind import REPLIES
from customer_channel import APPROVAL, Conversation, in_words, lisbon_trip

from agentic_eda.broker import WireEvent
from travel_agency import event_types
from travel_agency.events.booking import TripRequested
from supplier_world import world


class RecordingBroker:
    def __init__(self) -> None:
        self.published: list[WireEvent] = []
        self.subscribed: list[str] = []

    async def publish(self, event_type, source, data, id=None, attributes=None) -> WireEvent:
        event = WireEvent(id=id or f"e-{len(self.published)}", type=event_type, source=source, data=data, **attributes)  # fmt: skip
        self.published.append(event)
        return event

    async def subscribe(self, event_type, handler, mode="broadcast") -> None:
        self.subscribed.append(event_type)
        self.handler = handler


def test_the_running_example_asks_for_dates_in_the_future_and_in_order():
    trip = lisbon_trip(conversation_id="conv-1")
    dates = [j.departure_date for j in trip.origin_destinations]
    assert dates == sorted(dates) and dates[0] > date.today()
    assert [stay.city for stay in trip.stays] == ["MAD", "LIS"]
    assert "trip_id" not in trip.model_dump()  # no trip exists yet
    for code in [*(j.origin for j in trip.origin_destinations), *(s.city for s in trip.stays)]:
        assert code in world.CITIES, code


async def test_a_request_is_keyed_by_the_conversation_and_labelled_with_the_workflow():
    broker = RecordingBroker()
    conversation = Conversation(broker)
    request = await conversation.say(lisbon_trip(conversation_id="conv-1"))

    assert request.type == event_types.TRIP_REQUESTED
    assert request.partitionkey == "conv-1"
    assert request.correlationid == conversation.correlation_id
    assert TripRequested.model_validate(request.data).conversation_id == "conv-1"


async def test_the_channel_hears_only_its_own_workflow():
    broker = RecordingBroker()
    conversation = Conversation(broker)
    await conversation.listen()
    assert event_types.TRIP_CREATED in broker.subscribed
    assert event_types.CUSTOMER_REPLIED not in broker.subscribed  # its own words, not booking's

    def created(correlation: str) -> WireEvent:
        return WireEvent(id="c", type=event_types.TRIP_CREATED, source="BookingAgent", data={"trip_id": 1}, correlationid=correlation)  # fmt: skip

    await broker.handler(created("another-workflow"))
    await broker.handler(created(conversation.correlation_id))
    heard = await asyncio.wait_for(conversation.hear(), timeout=1)
    assert heard.correlationid == conversation.correlation_id
    assert conversation.arrived.empty()


def test_the_replies_are_a_question_a_change_and_an_approval():
    assert len(REPLIES) == 3 and REPLIES[-1] == APPROVAL
    assert all(reply[0].isupper() and reply.endswith((".", "?")) for reply in REPLIES)


def test_the_request_in_words_names_the_journeys_and_the_budget():
    words = in_words(lisbon_trip(conversation_id="conv-1"))
    assert words.startswith("2 adults, New York to Madrid on ")
    assert "Madrid to Lisbon on " in words and "Lisbon to New York on " in words
    assert words.endswith("with a budget of 3,500 USD.")
