# Chapter 1 — The Case for Agentic Event-Driven Architecture

The booking workflow the chapter watched fail, rebuilt decoupled behind the
`EventBroker` interface. A demo script publishes `booking.TripRequested`; the
Itinerary Planner Agent — a plain asyncio loop that calls an LLM, no framework —
consumes it on its own schedule and answers with `itinerary.ItineraryProposed`;
the script receives the reply by subscribing. Nothing waits on anything.

Components in play: Kafka (single KRaft container), the Itinerary Planner Agent
([components/itinerary_planner_minimal](../../components/itinerary_planner_minimal)),
and the audit consumer ([components/audit_consumer](../../components/audit_consumer)).
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

Build and start the stack — Kafka and the Itinerary Planner Agent — in the
background. The first run builds the images and can take several minutes;
later runs start in seconds:

```sh
docker compose up -d
```

Trigger the customer's script: it publishes one trip request in the background
and waits for the reply. The `--force-recreate` flag makes rerunning this same
command send a fresh request every time:

```sh
docker compose --profile demo up -d --force-recreate demo
```

Watch both sides of the conversation, line-labeled by component. Ctrl-C
detaches from the stream; nothing stops:

```sh
docker compose logs -f --since 30s demo itinerary-planner
```

On a fresh broker, the first start may log a few alarming-looking client reports —
`Topic ... not found in cluster metadata`, `Group Coordinator Request failed` —
before the stack settles. They are routine: a topic exists only once the first
event is published to it, and a brand-new Kafka elects its group coordinator on
first contact. Both resolve within seconds; a real failure would stop the demo,
not precede it.

Observe, in order:

1. `demo-1` prints a PUBLISHED card for `booking.TripRequested`, then
   "waiting for the reply event..." — the script is free the moment it has
   published.
2. `itinerary-planner-1` prints a RECEIVED card with the same event id, then
   `planning trip ...`. Every request takes 45 seconds — the chapter's
   inference time; a faster model is held to the same mark so the demo's pace
   never depends on your hardware or choice of model (`demo-1` prints a heartbeat meanwhile).
3. `itinerary-planner-1` prints a PUBLISHED card for
   `itinerary.ItineraryProposed`; its `request_id` is the request's event id.
4. `demo-1` receives that same reply as a RECEIVED card, matched by
   `request_id`, and prints a green ✔ SUCCESS.

The planner took its 45 seconds and nothing waited on it: the customer's side
was free after one publish, and the answer came back as an event. That is the
chapter's argument, running. (Act 3's audit consumer records every payload in
full.)

## Act 2 — durability

The request survives the death of its consumer. The stream stays in your main
terminal; only the kill itself needs a second one, because it must hit the
planner and nothing else. The 45-second hold is your window: from
`planning trip ...` you have that long to strike.

In the main terminal, send a fresh request and watch the conversation:

```sh
docker compose --profile demo up -d --force-recreate demo
docker compose logs -f --since 30s demo itinerary-planner
```

In the second terminal, while the stream shows `planning trip ...`, kill the
planner mid-inference, then bring it back:

```sh
docker compose stop itinerary-planner
docker compose start itinerary-planner
```

Observe, back in the main terminal: the restarted planner prints a RECEIVED
card for the *same event id*. The planner never told the broker it had
finished, so the broker still considered the event outstanding and delivered
it again. The demo, untouched throughout, gets its reply. The request outlived
the process that accepted it.

## Act 3 — a second consumer, zero publisher changes

Start the audit consumer next to the running stack. No other service is
touched, rebuilt, or restarted:

```sh
docker compose --profile audit up -d
```

Send one more request, and this time watch three components:

```sh
docker compose --profile demo up -d --force-recreate demo
docker compose logs -f --since 30s demo itinerary-planner audit-consumer
```

Afterwards, the full round trip — request and reply, complete payloads — is on
the durable audit record:

```sh
cat data/audit.log
```

Observe: `audit-consumer-1` records both events of the round trip, and the
script and planner published them exactly as before — neither changed by a
single line. (The extra envelope fields in the log — `specversion`, `time`,
and friends — are chapter 2's subject.)

## Shutting down

Stop and remove all of the chapter's containers, including the optional
profile ones. Add `--volumes` to also discard Kafka's stored events and
Ollama's downloaded models:

```sh
docker compose --profile demo --profile audit down
```

## Tests

Run every chapter 1 test suite, each inside its component's own image — no
Kafka, no network, no API key, no `.env`:

```sh
./test.sh
```

The same suites can be run one at a time:
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
- **Ollama is slow** — you are likely running it in Docker on the CPU. See
  [Local models with Ollama](../../README.md#local-models-with-ollama) in the
  repository README for the GPU options: native Ollama on Macs, `OLLAMA_GPU=1`
  on NVIDIA machines.
- **You changed the code but the behavior did not change** — Compose reuses
  built images. Add `--build` (`docker compose up -d --build`) to rebuild
  from your sources.
- **45 seconds per request is too slow for you** — the planner holds every
  reply to the chapter's 45-second inference time so the acts are easy to
  follow. Set `PLANNING_SECONDS=0` in `.env` to remove the hold (Act 2's kill
  window shrinks to your model's real speed).
