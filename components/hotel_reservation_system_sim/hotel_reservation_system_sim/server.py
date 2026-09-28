"""The Hotel Reservation System simulator: a hotel supplier's inventory, served over MCP."""

from datetime import date
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from travel_agency.sims import world

from . import inventory
from .inventory import RoomOffer

mcp = MCPServer("Hotel Reservation System (simulator)")


class Availability(BaseModel):
    offers: list[RoomOffer]


@mcp.tool()
def search_availability(
    city: str,
    check_in: date,
    check_out: date,
    rooms: Annotated[int, Field(ge=1)],
    adults: Annotated[int, Field(ge=1)],
    child_ages: list[Annotated[int, Field(ge=0, le=17)]],
) -> Availability:
    """Rooms free in a city for the nights from check-in to check-out.

    One offer per hotel and rate plan, each with the rooms left, the type of room, the
    cancellation policy, and the total for the whole stay. A room sleeps four guests at
    most, and an infant under 2 sleeps in a cot and is not counted. A hotel without rooms
    enough is left out.
    """
    # A ToolError's message reaches the caller; any other exception's text stays here.
    if check_out <= check_in:
        raise ToolError("check_out must be after check_in")
    matches = world.find_cities(city)
    if len(matches) != 1:
        raise ToolError(f"no single city is called {city}")
    guests = adults + sum(1 for age in child_ages if age >= 2)
    if guests > rooms * inventory.MOST_GUESTS_PER_ROOM:
        raise ToolError(f"{guests} guests do not fit in {rooms} rooms")
    offers = inventory.availability(matches[0], check_in, check_out, rooms, guests)
    return Availability(offers=offers)
