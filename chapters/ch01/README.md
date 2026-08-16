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

All commands below run from the `chapters/ch01` directory.

## Act 1 — the decoupled fix

```sh
# Build and start the stack (Kafka + the Itinerary Planner Agent) in the
# background. The first run builds the images and can take several minutes;
# later runs start in seconds.
docker compose up -d

# Publish a trip request, then wait for the itinerary to arrive as an event.
docker compose run --rm demo

# Optional, in a second terminal: the planner's side of the same conversation —
# it prints a RECEIVED card for the request and a PUBLISHED card for the reply.
docker compose logs -f itinerary-planner
```

The demo prints each event as a card — id, type, source, attributes, and
payload, with long values truncated — because the events moving between
components are the show, not the itinerary text. The reply card arrives some
30–60 seconds later, however long the model's reasoning takes, because nothing
is waiting on it. (The audit consumer in Act 3 records every payload in full.)

## Act 2 — durability

Run the demo again, and while the planner's log shows `planning trip ...`, kill
the consumer mid-inference:

```sh
# In one terminal: publish another trip request and wait for the reply.
docker compose run --rm demo

# In a second terminal: watch the planner receive the request...
docker compose logs -f itinerary-planner

# ...and while it is reasoning, kill it mid-inference, then bring it back.
docker compose stop itinerary-planner
docker compose start itinerary-planner
```

The planner never told the broker it had finished, so the broker still considers
the event outstanding: on restart the *same event* is delivered again, the
planner reasons again, and the reply still arrives. The request outlived the
process that accepted it.

## Act 3 — a second consumer, zero publisher changes

```sh
# Start the audit consumer next to the running stack. No other service is
# touched, rebuilt, or restarted.
docker compose --profile audit up -d

# Publish one more trip request.
docker compose run --rm demo

# The request and the reply are both on the durable record.
cat data/audit.log
```

The audit consumer subscribes to the events the script and planner already
publish and appends every one to a durable record — and neither publisher
changed by a single line. (The extra envelope fields you'll see in the log —
`specversion`, `time`, and friends — are chapter 2's subject.)

## Watching in a browser (optional)

```sh
# Start the Front Desk page, then open http://localhost:8000.
docker compose --profile ui up -d
```

The Front Desk streams every event live while you run the acts.

## Tests

```sh
# Run every chapter 1 test suite, each inside its component's own image.
./test.sh
```

Runs every suite, each inside its component's own image — no Kafka, no network,
no API key, no `.env`. The same suites can be run one at a time:
`docker compose -f compose.tests.yaml run --build --rm tests-itinerary-planner`, etc.

## Shutting down

```sh
# Stop and remove all of the chapter's containers, including the optional
# audit and ui ones. Add --volumes to also discard Kafka's stored events
# and Ollama's downloaded models.
docker compose --profile audit --profile ui down
```

## Troubleshooting

- **The demo hangs forever in Act 1** — check the planner's logs
  (`docker compose logs itinerary-planner`): an invalid or missing API key
  shows up there, not in the demo.
- **`kafka` is unhealthy on first start** — give it a few seconds; the
  healthcheck retries for a minute before anything else starts.
- **The first `docker compose up` with Ollama takes minutes** — the model
  (about 2 GB) downloads once into a volume, and the planner waits for it;
  later starts are quick. The first reply is also slower while the model loads
  into memory.
- **You changed the code but the behavior did not change** — Compose reuses
  built images. Add `--build` (`docker compose up -d --build`,
  `docker compose run --build --rm demo`) to rebuild from your sources.
