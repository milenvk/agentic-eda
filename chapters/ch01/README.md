# Chapter 1: The Case for Agentic Event-Driven Architecture

The booking workflow the chapter watched fail, rebuilt decoupled behind the
`EventBroker` interface. A demo script publishes `booking.TripRequested`; the
Itinerary Planner Agent (a plain asyncio loop that calls an LLM, no framework)
consumes it on its own schedule and answers with `itinerary.ItineraryProposed`;
the script receives the reply by subscribing. Nothing waits on anything.

Components in play: Kafka (single KRaft container), the Itinerary Planner Agent
([components/itinerary_planner_minimal](../../components/itinerary_planner_minimal)),
and the audit consumer ([components/audit_consumer](../../components/audit_consumer)).
The demo script stands in for the front door until the Booking Agent arrives in
chapter 2.

## Setup

Requirements: git, Docker with Compose, an internet connection.

1. In the repository root, create your `.env` from the template:

   ```sh
   cp .env.example .env
   ```

2. Set up an API key. If you already have one (OpenAI, Claude, Gemini, or any
   of the [providers LiteLLM supports](https://docs.litellm.ai/docs/providers)),
   use it: pick that provider's block in `.env`, uncomment it, comment out the
   default, and paste your key. The pattern is always the provider's key
   variable plus its model string, as the comments in `.env.example` show.

3. No API key? Get one from Gemini for free, no billing required:

   - Open [Google AI Studio](https://aistudio.google.com/apikey) and sign in
     with any Google account.
   - Click **Create API key** and copy the key.
   - Paste it into `.env` after `GEMINI_API_KEY=`. That is the whole setup:
     the Gemini block is active by default.

4. Prefer no key at all? Choose Ollama, free local models: uncomment its
   block in `.env`, and the model server starts with the stack, downloading
   its model on first start (about 2 GB, one time; the planner waits until it
   is ready). To run Ollama natively and use your GPU instead (recommended on
   Apple Silicon), install it from
   [ollama.com/download](https://ollama.com/download) and follow
   [Local models with Ollama](../../README.md#local-models-with-ollama) in
   the repository README.

## The demo, in two terminals

Open two terminals, both in `chapters/ch01`. The **first terminal watches**:
it follows the whole conversation for the entire demo, and you never type in
it again. The **second terminal acts**: every command in the acts below runs
there, from sending requests to killing processes and starting new consumers.
In the watch stream, every line is prefixed with the component it came from
(`demo-1` is the customer's script, `itinerary-planner-1` is the agent), and
every event appears as a card (id, type, source, attributes, and payload,
with long values truncated) because the events moving between components are
the show, not the itinerary text.

### Terminal 1: start the system and watch

Build and start the stack (Kafka and the Itinerary Planner Agent) in the
background. The first run builds the images and can take several minutes;
later runs reuse the build cache and start in seconds. `--build` keeps the
images in sync with the source, so if you edit the code, the next start
rebuilds exactly what changed:

```sh
docker compose up -d --build
```

Then follow the conversation for the rest of the demo. The command names every
component the acts involve; the ones not running yet join the stream the
moment they start. Ctrl-C detaches without stopping anything:

```sh
docker compose --profile demo --profile audit logs -f demo itinerary-planner audit-consumer
```

On a fresh broker, the first start may log a few alarming-looking client
reports before the stack settles, such as `Topic ... not found in cluster
metadata` and `Group Coordinator Request failed`. They are routine: a topic
exists only once the first event is published to it, and a brand-new Kafka
elects its group coordinator on first contact. They resolve within seconds;
a real failure would stop the demo, not precede it.

## Act 1: the decoupled fix

In the second terminal, trigger the customer's script: it publishes one trip
request in the background and waits for the reply. The `--force-recreate` flag
makes rerunning this same command send a fresh request every time:

```sh
docker compose --profile demo up -d --build --force-recreate demo
```

Observe in the watch terminal, in order:

1. `demo-1` prints a PUBLISHED card for `booking.TripRequested`, then
   "waiting for the reply event...". The script is free the moment it has
   published.
2. `itinerary-planner-1` prints a RECEIVED card with the same event id, then
   `planning trip ...`. Every request takes 45 seconds, the chapter's
   inference time; a faster model is held to the same mark so the demo's pace
   never depends on your hardware or choice of model (`demo-1` prints a
   heartbeat meanwhile).
3. `itinerary-planner-1` prints a PUBLISHED card for
   `itinerary.ItineraryProposed`; its `request_id` is the request's event id.
4. `demo-1` receives that same reply as a RECEIVED card, matched by
   `request_id`, and prints a green ✔ SUCCESS.

The planner took its 45 seconds and nothing waited on it: the customer's side
was free after one publish, and the answer came back as an event. That is the
chapter's argument, running. (Act 3's audit consumer records every payload in
full.)

## Act 2: durability

The request survives the death of its consumer. The 45-second hold is your
window: from `planning trip ...` you have that long to strike.

In the second terminal, send a fresh request:

```sh
docker compose --profile demo up -d --build --force-recreate demo
```

When the watch terminal shows `planning trip ...`, kill the planner
mid-inference, then bring it back:

```sh
docker compose stop itinerary-planner
docker compose start itinerary-planner
```

Observe, in the watch terminal: the restarted planner prints a RECEIVED
card for the *same event id*. The planner never told the broker it had
finished, so the broker still considered the event outstanding and delivered
it again. The demo, untouched throughout, gets its reply. The request outlived
the process that accepted it.

## Act 3: a second consumer, zero publisher changes

In the second terminal, start the audit consumer next to the running stack.
No other service is touched, rebuilt, or restarted. Notice it joins the watch
stream the moment it starts:

```sh
docker compose --profile audit up -d --build audit-consumer
```

Send one more request:

```sh
docker compose --profile demo up -d --build --force-recreate demo
```

Afterwards, the full round trip (request and reply, complete payloads) is on
the durable audit record:

```sh
cat data/audit.log
```

Observe, in the watch terminal: the audit consumer's first act is to receive
*every event from the earlier acts*: requests and replies published before it
existed. Nothing was coded for that: the events sit on an immutable, durable
log, so a brand-new consumer simply starts reading from the beginning of
history. Then the fresh round trip arrives and `audit-consumer-1` records it
live. The script and planner published exactly as before; neither changed by
a single line. (The extra envelope fields in the log, `specversion`, `time`,
and friends, are chapter 2's subject.)

## Shutting down

Stop and remove all of the chapter's containers, including the optional
profile ones. Add `--volumes` to also discard Kafka's stored events and
Ollama's downloaded models:

```sh
docker compose --profile demo --profile audit down
```

## Tests

Run every chapter 1 test suite, each inside its component's own image, with
no Kafka, no network, no API key, and no `.env`:

```sh
./test.sh
```

The same suites can be run one at a time:
`docker compose -f compose.tests.yaml run --build --rm tests-itinerary-planner`, etc.

## Troubleshooting

- **The demo hangs forever in Act 1.** Look at the `itinerary-planner-1`
  lines in the stream: an invalid or missing API key shows up there, not in
  the demo.
- **`kafka` is unhealthy on first start.** Give it a few seconds; the
  healthcheck retries for a minute before anything else starts.
- **The first `docker compose up` with Ollama takes minutes.** The model
  (about 2 GB) downloads once into a volume, and the planner waits for it;
  later starts are quick. The first reply is also slower while the model loads
  into memory.
- **Ollama is slow.** You are likely running it in Docker on the CPU. See
  [Local models with Ollama](../../README.md#local-models-with-ollama) in the
  repository README for the GPU options: native Ollama on Macs, `OLLAMA_GPU=1`
  on NVIDIA machines.
- **45 seconds per request is too slow for you.** The planner holds every
  reply to the chapter's 45-second inference time so the acts are easy to
  follow. Set `PLANNING_SECONDS=0` in `.env` to remove the hold (Act 2's kill
  window shrinks to your model's real speed).
