"""Every event type in the system, declared once, grouped by bounded context.

Components import these constants and never retype the strings. The catalog in
design/02_workflows_and_events.adoc is the authority on names and ownership.
"""

# booking — the front door and the booking lifecycle
TRIP_REQUESTED = "booking.TripRequested"

# planning — trip planning and assembly
ITINERARY_PROPOSED = "planning.ItineraryProposed"
