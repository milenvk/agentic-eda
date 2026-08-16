# Chapter 1 — The Case for Agentic Event-Driven Architecture

The booking workflow the chapter watched fail, rebuilt decoupled behind the
`EventBroker` interface. A demo script publishes `booking.TripRequested`; the
Itinerary Planner Agent — a plain asyncio loop that calls an LLM, no framework —
consumes it on its own schedule and answers with `itinerary.ItineraryProposed`;
the script receives the reply by subscribing. Nothing waits on anything.

Components in play: Kafka (single KRaft container), the Itinerary Planner Agent
([components/itinerary_planner_minimal](../../components/itinerary_planner_minimal)),
the audit consumer ([components/audit_consumer](../../components/audit_consumer)),
and optionally the Front Desk UI ([components/front_desk](../../components/front_desk)).
The demo script stands in for the front door until the Booking Agent arrives in
chapter 2.

## Setup

Requirements: git, Docker with Compose, an internet connection.

Copy `.env.example` (repository root) to `.env` and pick one of its four model
blocks: Gemini (default, free tier), OpenAI, Claude, or Ollama. The Ollama
choice needs no key at all — the local model server starts with the stack and
downloads its model on first start (about 2 GB, one time; the planner waits
until it is ready). Any other LiteLLM-supported provider (DeepSeek, Mistral,
Groq, …) works the same way: its key variable plus the model string, as the
comments in `.env.example` show.

## How the demo reads

Everything happens in one terminal, in `chapters/ch01`. Both sides of the
conversation stream into it, and every line is prefixed with the component it
came from — `demo-1` is the customer's script, `itinerary-planner-1` is the
agent. Every event appears as a card — id, type, source, attributes, and
payload, with long values truncated — because the events moving between
components are the show, not the itinerary text.

## Act 1 — the decoupled fix

```sh
# Build and start the stack (Kafka + the Itinerary Planner Agent) in the
# background. The first run builds the images and can take several minutes;
# later runs start in seconds.
docker compose up -d

# Trigger the customer's script in the background: it publishes one trip
# request and waits for the reply. (--force-recreate makes rerunning this
# command send a fresh request every time.)
docker compose --profile demo up -d --force-recreate demo

# Watch both sides of the conversation, line-labeled by component.
# Ctrl-C detaches from the stream; nothing stops.
docker compose logs -f --since 30s demo itinerary-planner
```

Observe, in order:

1. `demo-1` prints a PUBLISHED card for `booking.TripRequested`, then
   "waiting for the reply event..." — the script is free the moment it has
   published.
2. `itinerary-planner-1` prints a RECEIVED card with the same event id, then
   `planning trip ...` while the model reasons (30–60 seconds; `demo-1`
   prints a heartbeat meanwhile).
3. `itinerary-planner-1` prints a PUBLISHED card for
   `itinerary.ItineraryProposed`; its `request_id` is the request's event id.
4. `demo-1` receives that same reply as a RECEIVED card, matched by
   `request_id`.

The model spent the whole time reasoning and nothing waited on it: the
customer's side was free after one publish, and the answer came back as an
event. That is the chapter's argument, running. (Act 3's audit consumer
records every payload in full.)

## Act 2 — durability

The request survives the death of its consumer. The stream stays in your main
terminal; only the kill itself needs a second one, because it must hit the
planner and nothing else.

```sh
# Main terminal: send a fresh request and watch the conversation.
docker compose --profile demo up -d --force-recreate demo
docker compose logs -f --since 30s demo itinerary-planner
```

```sh
# Second terminal, while the stream shows "planning trip ...": kill the
# planner mid-inference...
docker compose stop itinerary-planner

# ...and bring it back.
docker compose start itinerary-planner
```

Observe, back in the main terminal: the restarted planner prints a RECEIVED
card for the *same event id*. The planner never told the broker it had
finished, so the broker still considered the event outstanding and delivered
it again. The demo, untouched throughout, gets its reply. The request outlived
the process that accepted it.

## Act 3 — a second consumer, zero publisher changes

```sh
# Start the audit consumer next to the running stack. No other service is
# touched, rebuilt, or restarted.
docker compose --profile audit up -d

# Send one more request, and this time watch three components.
docker compose --profile demo up -d --force-recreate demo
docker compose logs -f --since 30s demo itinerary-planner audit-consumer

# Afterwards: the full round trip — request and reply, complete payloads —
# is on the durable audit record.
cat data/audit.log
```

Observe: `audit-consumer-1` records both events of the round trip, and the
script and planner published them exactly as before — neither changed by a
single line. (The extra envelope fields in the log — `specversion`, `time`,
and friends — are chapter 2's subject.)

## Watching in a browser (optional)

```sh
# Start the Front Desk page, then open http://localhost:8000.
docker compose --profile ui up -d
```

The Front Desk streams every event live while you run the acts.

## Shutting down

```sh
# Stop and remove all of the chapter's containers, including the optional
# profile ones. Add --volumes to also discard Kafka's stored events and
# Ollama's downloaded models.
docker compose --profile demo --profile audit --profile ui down
```

## Tests

```sh
# Run every chapter 1 test suite, each inside its component's own image.
./test.sh
```

Runs every suite, each inside its component's own image — no Kafka, no network,
no API key, no `.env`. The same suites can be run one at a time:
`docker compose -f compose.tests.yaml run --build --rm tests-itinerary-planner`, etc.

## Troubleshooting

- **The demo hangs forever in Act 1** — look at the `itinerary-planner-1`
  lines in the stream: an invalid or missing API key shows up there, not in
  the demo.
- **`kafka` is unhealthy on first start** — give it a few seconds; the
  healthcheck retries for a minute before anything else starts.
- **The first `docker compose up` with Ollama takes minutes** — the model
  (about 2 GB) downloads once into a volume, and the planner waits for it;
  later starts are quick. The first reply is also slower while the model loads
  into memory.
- **You changed the code but the behavior did not change** — Compose reuses
  built images. Add `--build` (`docker compose up -d --build`) to rebuild
  from your sources.
