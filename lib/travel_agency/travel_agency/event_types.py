"""Every event type in the system, declared once, grouped by bounded context.

Components import these constants and never retype the strings. The catalog in
design/02_workflows_and_events.adoc is the authority on names and ownership.
"""

# booking — a customer's request and replies, written by whoever asks, and the Booking
# Agent's events about the trip
TRIP_REQUESTED = "booking.TripRequested"
TRIP_REQUEST_REJECTED = "booking.TripRequestRejected"
TRIP_CREATED = "booking.TripCreated"
PROPOSAL_READY = "booking.ProposalReady"
CUSTOMER_REPLIED = "booking.CustomerReplied"
ITINERARY_APPROVED = "booking.ItineraryApproved"
ITINERARY_REJECTED = "booking.ItineraryRejected"
TRIP_CHANGED = "booking.TripChanged"
CLARIFICATION_REQUESTED = "booking.ClarificationRequested"

# planning — the request planning serves, written by whoever asks, and its answer
ITINERARY_REQUESTED = "planning.ItineraryRequested"
ITINERARY_PROPOSED = "planning.ItineraryProposed"
