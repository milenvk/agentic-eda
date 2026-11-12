# Chapter 3: The Business State and the Agent

The demo script that stood in for booking gives way to the Booking agent, and the trip
approval workflow runs end to end for the first time: a request, the trip, planning's
proposal, the customer's replies in their own words, and the approval. The business's state
is the Trip, one class in the Booking agent's component with the rules in code and one
operation per business action, each returning the one event that says what happened. The
Trip lives in a state store, PostgreSQL from this chapter, and the activator of chapter 2,
extended by one declaration for the state, loads the Trip before every activation and
commits it after. The agent is built on ADK, the book's second framework, and calls an LLM
on one event only: the customer's reply.

Components in play: Kafka, PostgreSQL, the Booking agent
([components/booking_agent](../../components/booking_agent)), the Itinerary Planner agent
of chapter 2 with its two suppliers, and the audit consumer. The demo scripts stand in for
the customer channel until the Front Desk arrives in chapter 4.

Where to read the code, in the order the chapter teaches it:

- [trip.py](../../components/booking_agent/booking_agent/trip.py): the Trip, its rules, and
  its operations, plain Python that knows no store, broker, framework, or LLM.
- [state.py](../../lib/agentic_eda/agentic_eda/state.py): the StateStore port, four calls;
  [postgres_state_store.py](../../lib/agentic_eda/agentic_eda/postgres_state_store.py) and
  [memory_state_store.py](../../lib/agentic_eda/agentic_eda/memory_state_store.py), its two
  adapters.
- [app.py](../../components/booking_agent/booking_agent/app.py): the three declarations,
  `consumes`, `produces`, and `state`, and the activator attached inside ADK's own app.
- [agent.py](../../components/booking_agent/booking_agent/agent.py): the custom agent's
  dispatch on the event's class, the four tools landing in the Trip's operations, and the
  `LlmAgent` that reads the reply; [prompts/reply.v1.md](../../components/booking_agent/booking_agent/prompts/reply.v1.md),
  what it is told, and [prompts/\_\_init\_\_.py](../../components/booking_agent/booking_agent/prompts/__init__.py),
  how the Trip is written for it.
- [events/booking.py](../../lib/travel_agency/travel_agency/events/booking.py): booking's
  nine contracts.
- The customer channel, one script per act: [customer_channel.py](customer_channel.py),
  [change_of_mind.py](change_of_mind.py), [redelivered_request.py](redelivered_request.py), and
  [rejected_request.py](rejected_request.py).

## Setup

The same `.env` as chapter 1, in the repository root. If you skipped chapter 1, follow
[its Setup section](../ch01/README.md#setup) first.

The Booking agent asks its model to read a reply and call one of four tools. The default
model in `.env.example`, `qwen3:4b-instruct` on Ollama, reads every scripted reply as
intended. Smaller models, `llama3.2` among them, ask a question where the words describe an
itinerary or reject where they ask for a change, so keep the default or go larger.

## The demo, in two terminals

Open two terminals and change to the chapter directory in both:

```sh
cd chapters/ch03
```

The **first terminal watches** for the whole demo. The **second terminal acts**: every
command in the acts below runs there. In the watch stream, every line is prefixed with the
component it came from, and every event appears as a card.

### Terminal 1: start the system and watch

Build and start the stack: Kafka, PostgreSQL, the Booking agent, the Planner, the two
simulators, and the audit consumer. The first run builds five images and can take several
minutes; later runs reuse the build cache:

```sh
docker compose up -d --build
```

Then follow the conversation for the rest of the demo. Ctrl-C detaches without stopping
anything:

```sh
docker compose --profile demo logs -f demo demo-change demo-redelivered \
    demo-rejected booking-agent itinerary-planner audit-consumer
```

Wait for `BookingAgent is subscribed and waiting for events` and the same line from
`ItineraryPlannerAgent` and `AuditConsumer` before the first act.

## Act 1: a trip, booked

In the second terminal, start the conversation: the running example's request, New York to
Lisbon for two with three days in Madrid on the way, six months from today, followed by one
reply that approves an itinerary:

```sh
docker compose --profile demo up -d --build --force-recreate demo
```

Observe in the watch terminal, in order:

1. `demo-1` prints the request in a customer's words, then a PUBLISHED card for
   `booking.TripRequested`. Its `partitionkey` is the conversation's id and its data has no
   trip id: no trip exists yet.
2. `booking-agent-1` receives it and, with no LLM call, publishes `booking.TripCreated` with
   a `trip_id` of 1 (or the next free number: the store assigned it). `demo-1` prints the id.
3. `booking-agent-1` receives its own `booking.TripCreated` and publishes
   `planning.ItineraryRequested` for the trip. Its `causationid` is the `TripCreated` event's
   id: the agent reached its next step by consuming its own event.
4. `itinerary-planner-1` plans as in chapter 2 and publishes `planning.ItineraryProposed`.
   `booking-agent-1` records the proposal on the Trip and publishes `booking.ProposalReady`;
   `demo-1` lists the itineraries.
5. The customer replies `The cheapest one, please.` `booking-agent-1` runs its LLM over the
   reply and the proposal, logs `the LLM decided: ItineraryApproved`, and publishes
   `booking.ItineraryApproved` with the rank the Trip accepted. `demo-1` prints a green ✔
   and two commands.

Every event from the request on carries the same `correlationid`, and from
`booking.TripCreated` on, each one's `partitionkey` is the trip's id. The agent set none of
them. Run the first printed command to count the workflow's events in the audit record:

```sh
grep <correlationid> data/audit.log | wc -l
```

Run the second to read the Trip in PostgreSQL. The `version` is the number of activations
that changed the trip, and the `state` column, left out here, is the Trip as the activator
last committed it:

```sh
docker compose exec postgres psql -U agency \
    -c "select id, status, version from trips where id = <trip_id>"
```

A different model may read the reply differently, and ask which itinerary instead of
approving. The script follows whatever booking publishes, and ends unapproved when its one
reply earns a question. Either way every event is in the audit record, and the Trip is in
PostgreSQL where the conversation left it.

## Act 2: the customer changes their mind

A second conversation, with three replies:

```sh
docker compose --profile demo up -d --build --force-recreate demo-change
```

Observe in the watch terminal, after the request, the trip, and the first proposal as in
Act 1:

1. The customer replies `Thanks, got it.` The words settle nothing, so the LLM calls
   `request_clarification` and `booking.ClarificationRequested` comes back with a question
   and two options.
2. The customer replies `Could we leave a day later? The fares on that day are too high.`
   The reply's `answering` field carries the question. The LLM calls `change` with every
   journey's new date; the Trip moves the stays with their journeys, checks the dates as it
   checked the request, and `booking.TripChanged` is published with the new requirements.
   `booking-agent-1` consumes it and asks planning again, the reason in the request. A new
   proposal arrives.
3. The customer replies `The cheapest one, please.` `booking.ItineraryApproved` ends the
   conversation.

If the LLM first calls `change` with one journey's date, the Trip refuses it and the log
shows `the LLM's call of change was refused`; the LLM then calls again with every date. The
refusal is in the log, never on the wire.

## Act 3: a request delivered twice

A third conversation, whose request is published twice with the same id, as a broker that
promises at-least-once delivery may deliver it:

```sh
docker compose --profile demo up -d --build --force-recreate demo-redelivered
```

Observe in the watch terminal:

1. `demo-redelivered-1` prints two PUBLISHED cards with the same `id`.
2. `booking-agent-1` prints two RECEIVED cards and one `booking.TripCreated`. For the
   second delivery it logs `already handled`: the store keeps the request's event id under
   a unique index, so the redelivery found the trip the first delivery created, and the
   event's id was already recorded against it.
3. The proposal arrives, the script lists the itineraries, prints a green ✔, and stops with
   the command below.

Read the trip's row: one trip, at status `proposed`, its `version` counting the activations
that changed it:

```sh
docker compose exec postgres psql -U agency \
    -c "select id, status, version from trips where id = <trip_id>"
```

## Act 4: a request the Trip refuses

Send a request whose journeys are out of order, the way home first:

```sh
docker compose --profile demo up -d --build --force-recreate demo-rejected
```

Observe in the watch terminal:

1. `demo-rejected-1` prints a PUBLISHED card. The event is valid against its contract, so
   the activator lets it through to the agent.
2. `booking-agent-1` publishes `booking.TripRequestRejected` under the conversation's key,
   its `reason` naming the broken rule. The Trip's `open` operation checked the rules in
   code; no LLM was involved, no trip was opened, and planning was never asked.

Chapter 2's malformed request stopped at the boundary, where the contract is checked. This
one passed the boundary and stopped at the Trip, where the rules are. The activator had
created the trip's row before the activation, as it does for every request, so a row at
status `new` remains, with the request's event id recorded against it: a redelivery of the
refused request is refused once.

## Shutting down

Stop and remove all of the chapter's containers. Add `--volumes` to also discard Kafka's
stored events, the trips in PostgreSQL, and Ollama's downloaded models:

```sh
docker compose --profile demo down
```

The audit record in `data/audit.log` stays on disk. Delete it to start the next run clean.

## Tests

Run every chapter 3 test suite, each inside its component's own image, with no Kafka, no
model, no API key, and no `.env`:

```sh
./test.sh
```

The Booking agent's suite runs the whole workflow through the activator on the in-memory
broker and the in-memory state store, with a scripted LLM in place of a model and a plain
function in place of the Planner: a request, the proposal, each kind of reply, and a
redelivered request. The library's PostgreSQL adapter is tested against a database the test
runner starts.

## Troubleshooting

- **Nothing follows the request.** Look at the `booking-agent-1` lines in the stream. A
  database it cannot reach shows up at startup, and a model's refusal to call a tool shows
  up as a failed activation, redelivered.
- **The same reply is read again and again.** The LLM answers in prose every time. A larger
  model in `.env` ends it; so does stopping the Booking agent, which leaves the trip where it
  was in PostgreSQL.
- **Ollama is slow.** A reply is one model call, a proposal several. See
  [Local models with Ollama](../../README.md#local-models-with-ollama) in the repository
  README for the GPU options.
