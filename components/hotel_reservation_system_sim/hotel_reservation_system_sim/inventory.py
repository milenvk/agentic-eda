"""The hotels' inventory: rooms left and rates, generated from the world for any nights.

Nothing is stored: each hotel rolls dice seeded by its name and the nights asked about, so
the same question finds the same rooms at the same rates on every run.
"""

from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel

from travel_agency.sims import world
from travel_agency.sims.world import City

MOST_GUESTS_PER_ROOM = 4
MOST_ROOMS_LEFT = 6
FAMILY_ROOM_MARKUP = 1.3  # a family room sleeps three or four
OFFER_MINUTES = 30

# Per rate plan: its markup, then its cancellation policy.
RATE_PLANS = {
    "FLEXIBLE": (1.0, "free cancellation until 48 hours before arrival"),
    "ADVANCE": (0.85, "no refund once booked"),
}


class RoomOffer(BaseModel):
    offer_id: str
    hotel: str
    area: str
    stars: int
    check_in: date
    check_out: date
    rooms_left: int
    room: str  # double or family
    rate_plan: str
    cancellation: str
    total: float  # for every room and every night together
    currency: str
    expires_at: datetime


def availability(
    city: City, check_in: date, check_out: date, rooms: int, guests: int
) -> list[RoomOffer]:
    """Each hotel with rooms enough for the party, under each rate plan."""
    nights = (check_out - check_in).days
    family = guests > 2 * rooms  # more than two guests share a room
    room_markup = FAMILY_ROOM_MARKUP if family else 1.0
    asked = f"{check_in:%Y%m%d}-{nights}N"
    expires_at = datetime.now(UTC) + timedelta(minutes=OFFER_MINUTES)

    offers = []
    for number, hotel in enumerate(city.hotels, start=1):
        roll = world.dice("rooms", hotel.name, check_in, check_out)
        rooms_left = roll.randint(0, MOST_ROOMS_LEFT)
        season = roll.uniform(0.85, 1.3)  # how busy these nights are
        if rooms_left < rooms:
            continue
        nightly = hotel.nightly * season * room_markup
        for plan, (markup, cancellation) in RATE_PLANS.items():
            offers.append(
                RoomOffer(
                    offer_id=f"{city.code}{number}-{asked}-{plan}-{rooms}R{guests}G",
                    hotel=hotel.name,
                    area=hotel.area,
                    stars=hotel.stars,
                    check_in=check_in,
                    check_out=check_out,
                    rooms_left=rooms_left,
                    room="family" if family else "double",
                    rate_plan=plan,
                    cancellation=cancellation,
                    total=round(nightly * markup * nights * rooms, 2),
                    currency=world.CURRENCY,
                    expires_at=expires_at,
                )
            )
    return offers
