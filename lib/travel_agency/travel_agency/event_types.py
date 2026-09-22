"""Every event type in the system, declared once, grouped by bounded context.

Components import these constants and never retype the strings. The catalog in
design/02_workflows_and_events.adoc is the authority on names and ownership.
"""

# planning — the request planning serves, written by whoever asks, and its answer
ITINERARY_REQUESTED = "planning.ItineraryRequested"
ITINERARY_PROPOSED = "planning.ItineraryProposed"
