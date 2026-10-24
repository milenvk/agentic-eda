# Chapter 3: The Business State and the Agent

The demo script that stood in for booking gives way to the Booking Agent, and the trip
approval workflow runs end to end for the first time: a request, the trip, planning's
proposal, the customer's replies in their own words, and the approval. The business's state
is the Trip, one class in the Booking Agent's component with the rules in code and one
operation per business action, each returning the one event that says what happened. The
Trip lives in a state store, PostgreSQL from this chapter, and the activator of chapter 2,
extended by one declaration for the state, loads the Trip before every activation and
commits it after. The agent is built on ADK, the book's second framework, and calls an LLM
on one event only: the customer's reply.

Components in play: Kafka, PostgreSQL, the Booking Agent
([components/booking_agent](../../components/booking_agent)), the Itinerary Planner Agent
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
  what it is told.
- [events/booking.py](../../lib/travel_agency/travel_agency/events/booking.py): booking's
  nine contracts.
- [customer_channel.py](customer_channel.py): the conversation, from the customer's side.

## Setup

The same `.env` as chapter 1, in the repository root. If you skipped chapter 1, follow
[its Setup section](../ch01/README.md#setup) first.

The Booking Agent asks its model to read a reply and call one of four tools. The smallest
model in `.env.example`, `llama3.2` on Ollama, reads about half of the replies the way a
larger model does: it asks a question where the words describe an itinerary, and rejects
where the words ask for a change. Act 1 says what that looks like. A larger local model,
such as `qwen2.5:7b` or `llama3.1:8b` in `.env`, reads every reply as scripted.

## The demo, in two terminals

Open two terminals and change to the chapter directory in both:

```sh
cd chapters/ch03
```

The **first terminal watches** for the whole demo. The **second terminal acts**: every
command in the acts below runs there. In the watch stream, every line is prefixed with the
component it came from, and every event appears as a card.

### Terminal 1: start the system and watch

Build and start the stack: Kafka, PostgreSQL, the Booking Agent, the Planner, the two
simulators, and the audit consumer. The first run builds five images and can take several
minutes; later runs reuse the build cache:

```sh
docker compose up -d --build
```

Then follow the conversation for the rest of the demo. Ctrl-C detaches without stopping
anything:

```sh
docker compose --profile demo logs -f demo demo-rejected demo-redelivered booking-agent itinerary-planner audit-consumer
```

Wait for `BookingAgent is subscribed and waiting for events` and the same line from
`ItineraryPlannerAgent` and `AuditConsumer` before the first act.

## Act 1: the trip approval workflow, from the request to the approval

In the second terminal, start the conversation: the running example's request, New York to
Lisbon for two with three days in Madrid on the way, six months from today, followed by four
replies in a customer's words:

```sh
docker compose --profile demo up -d --build --force-recreate demo
```

Observe in the watch terminal, in order:

1. `demo-1` prints a PUBLISHED card for `booking.TripRequested`. Its `partitionkey` is the
   conversation's id and its data has no trip id: no trip exists yet.
2. `booking-agent-1` receives it and, with no LLM call, publishes `booking.TripCreated` with
   a `trip_id` of 1 (or the next free number: the store assigned it). `demo-1` prints the id.
3. `booking-agent-1` receives its own `booking.TripCreated` and publishes
   `planning.ItineraryRequested` for the trip. Its `causationid` is the `TripCreated` event's
   id: the agent reached its next step by consuming its own event.
4. `itinerary-planner-1` plans as in chapter 2 and publishes `planning.ItineraryProposed`.
   `booking-agent-1` records the proposal on the Trip and publishes `booking.ProposalReady`;
   `demo-1` lists the itineraries.
5. The customer replies `Sounds good.` `booking-agent-1` runs its LLM over the reply, the
   proposal, and the trip's requirements; the words settle nothing, so the LLM calls
   `request_clarification` and `booking.ClarificationRequested` comes back with a question.
6. The customer replies `Could we leave a day later? The fares on that day are too high.`
   The LLM calls `change` with every journey's new date; the Trip moves the stays with
   their journeys, checks the dates as it checked the request, and `booking.TripChanged`
   is published. `booking-agent-1` consumes it and asks planning again, the reason in the
   request. A new proposal arrives.
7. The customer replies `No, all of these are too expensive for what they offer.`
   `booking.ItineraryRejected`, another planning request, another proposal.
8. The customer replies `The one with the morning flight, please.` The LLM resolves the
   description against the proposal's itineraries and calls `approve` with its rank;
   `booking.ItineraryApproved` ends the workflow, and `demo-1` prints a green ✔ and a
   `grep` command for the whole workflow in the audit record.

Every event from the request on carries the same `correlationid`, and from
`booking.TripCreated` on, each one's `partitionkey` is the trip's id. The agent set none of
them.

A small model may read a reply differently: reject instead of changing the dates, or ask
which itinerary where the words describe one. The script follows whatever booking publishes,
so the conversation still runs; it ends early when an approval comes before the fourth reply,
and it ends unapproved when the fourth reply earns a question. Either way every event is in
the audit record, and the Trip is in PostgreSQL where the conversation left it. An
LLM that answers in prose instead of calling a tool fails its activation, which the broker
redelivers: `booking-agent-1` then shows the same `booking.CustomerReplied` received twice,
and the second reading usually calls a tool.

The Trip is in PostgreSQL. Read the row while the stack runs:

```sh
docker compose exec postgres psql -U agency -c "select id, status, version, request_event_id from trips"
```

The `version` is the number of activations that changed the trip, and the `state` column,
left out above, is the Trip as the activator last committed it.

## Act 2: a request that is no business request

Send a request whose journeys are out of order, the way home first:

```sh
docker compose --profile demo up -d --build --force-recreate demo-rejected
```

Observe in the watch terminal:

1. `demo-rejected-1` prints a PUBLISHED card. The event is valid against its contract, so
   the activator lets it through to the agent.
2. `booking-agent-1` publishes `booking.TripRequestRejected` under the conversation's key,
   its `reason` naming the broken rule. The Trip's `create` operation checked the rules in
   code; no LLM was involved, no trip was created, and planning was never asked.

Chapter 2's malformed request stopped at the boundary, where the contract is checked. This
one passed the boundary and stopped at the Trip, where the rules are.

## Act 3: one request, delivered twice

Publish a request and then the very same event again, same id and all, as a broker that
promises at-least-once delivery may do:

```sh
docker compose --profile demo up -d --build --force-recreate demo-redelivered
```

Observe in the watch terminal:

1. `demo-redelivered-1` prints two PUBLISHED cards with the same `id`.
2. `booking-agent-1` prints two RECEIVED cards and one `booking.TripCreated`. For the
   second delivery it logs `already handled`: the store keeps the request's event id under
   a unique index, so the redelivery found the trip the first delivery created, and the
   event's id was already recorded against it.
3. The trip goes on to planning like any other, so a `booking.ProposalReady` may arrive
   meanwhile. After 30 seconds with no second `TripCreated`, `demo-redelivered-1` prints a
   green ✔.

## Shutting down

Stop and remove all of the chapter's containers. Add `--volumes` to also discard Kafka's
stored events, the trips in PostgreSQL, and Ollama's downloaded models:

```sh
docker compose --profile demo down
```

The audit record in `data/audit.log` stays on disk. Delete the file to start the next run
with an empty record.

## Tests

Run every chapter 3 test suite, each inside its component's own image, with no Kafka, no
model, no API key, and no `.env`:

```sh
./test.sh
```

The Booking Agent's suite runs the whole workflow through the activator on the in-memory
broker and the in-memory state store, with a scripted LLM in place of a model and a plain
function in place of the Planner: a request, the proposal, each of the four replies, and a
redelivered request. The library's PostgreSQL adapter is tested against a database the test
runner starts.

## Troubleshooting

- **Nothing follows the request.** Look at the `booking-agent-1` lines in the stream. A
  database it cannot reach shows up at startup, and a model's refusal to call a tool shows
  up as a failed activation, redelivered.
- **The same reply is read again and again.** The LLM answers in prose every time. A larger
  model in `.env` ends it; so does stopping the Booking Agent, which leaves the trip where it
  was in PostgreSQL.
- **Ollama is slow.** A reply is one model call, a proposal several. See
  [Local models with Ollama](../../README.md#local-models-with-ollama) in the repository
  README for the GPU options.
