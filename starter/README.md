# Starter: your own application on `agentic_eda`

The smallest application built on the book's framework, in a business that is not travel.
A shop receives product reviews. One agent triages each review: is it positive or negative,
what does it say in a sentence, and does the customer need a reply from a person. A review
comes in as `reviews.ReviewReceived`, and its triage goes out as `reviews.ReviewTriaged`.

Nothing here imports the Travel Agency. The image holds the framework
([lib/agentic_eda](../lib/agentic_eda)) and this directory, and that is all an application
of your own needs.

## Read it

Four files, about a hundred and fifty lines together, in this order:

1. [review_triage/events.py](review_triage/events.py): the two contracts. Each is a
   Pydantic class bound by `@event` to its type on the wire.
2. [review_triage/agent.py](review_triage/agent.py): the agent, a plain async function. A
   typed review comes in, a typed triage goes out, and nothing in the file knows that a
   broker exists.
3. [review_triage/app.py](review_triage/app.py): the app hosting the agent, and the one
   line attaching the activator to it. The activator subscribes, validates each event
   against its contract, calls the agent, validates the answer, and publishes it with the
   request's `correlationid` and its `causationid`.
4. [send_review.py](send_review.py): a script standing in for the shop. It publishes a
   review through the `EventBroker` port and waits for the triage as an event.

## Run it

Requirements: Docker with Compose, and the repository's `.env` with a model chosen. If you
have not created it yet, follow [chapter 1's Setup](../chapters/ch01/README.md#setup).

Open two terminals, both in `starter`. In the first, build and start Kafka and the agent,
then follow the conversation. The first build can take a few minutes:

```sh
docker compose up -d --build
docker compose --profile demo logs -f review-triage send-review
```

Wait for `ReviewTriageAgent is subscribed and waiting for events`. Kafka's routine
fresh-start reports, explained in chapter 1's README, may precede it.

In the second terminal, send a review:

```sh
docker compose --profile demo up -d --build --force-recreate send-review
```

Observe in the first terminal: `send-review-1` prints a PUBLISHED card for
`reviews.ReviewReceived`, `review-triage-1` prints a RECEIVED card with the same event id
and then a PUBLISHED card for `reviews.ReviewTriaged`, and `send-review-1` receives that
event, matched to its review by `correlationid`.

To send a review in your own words, run the script in the foreground with the review as
its arguments:

```sh
docker compose --profile demo run --rm send-review python send_review.py The laces are too short but I love the colour
```

Stop and remove the containers when you are done:

```sh
docker compose --profile demo down
```

Run the test, which needs no Kafka, no model, and no `.env`:

```sh
./test.sh
```

## Make it your own

Work in this order, running `./test.sh` and the demo after each step.

1. **Name it.** Rename the `review_triage` package, and change the name in
   `pyproject.toml`, in the `CMD` of the `Dockerfile`, in `compose.yaml`, and in the
   `source` argument of `eda.attach`. The `source` is the component's name on every event
   published by it, and its consumer group on the broker.
2. **Replace the two events.** Write your own type constants and `@event` classes in
   `events.py`. A type is `<context>.<FactInPastTense>`, and the context before the dot
   becomes the topic. No order is kept between events by default. Where one subject (an
   order, a ticket, a patient) has several events and their order matters, name the field
   holding the subject's id, as in `@event(ORDER_SHIPPED, order_per="order_id")`: one
   subject's events are then handled in publish order, one at a time, while different
   subjects never wait for each other.
3. **Replace the agent.** Keep its shape: one consumed class in, one produced class out.
   Let the model judge and let code carry the facts, as `triage` does with `review_id`:
   a model asked to retype an id or an amount will sometimes retype it wrong.
4. **Publish from your own side.** `send_review.py` shows the whole of it: `data_of(fact)`
   for the data, and a fresh `correlationid` for a new thread.

Where to look when the starter's shape is too small:

- **An agent built with a framework.** The activator takes a compiled LangGraph graph as
  it takes a function: see the Itinerary Planner's
  [agent.py](../components/itinerary_planner/itinerary_planner/agent.py) and
  [app.py](../components/itinerary_planner/itinerary_planner/app.py). The attach block is
  the same, and the agent module never imports `eda`.
- **More than one possible answer, or none.** `eda.produces(A, B)` lets the agent answer
  with either class, and adding `eda.Nothing` lets it decline with a reason. Silence is
  never taken for an answer: an agent that returns nothing without saying so fails its
  activation.
- **A second component.** Any component that declares `eda.consumes(ReviewTriaged)`
  receives every triage, and nothing in the agent here changes. Give each component its
  own directory, image, and `source`.
- **How the inside works.** Each chapter of the book teaches one part of the framework,
  and [the design](../design/04_implementation_design.adoc) is its reference.

## Taking it with you

The starter builds inside this repository because its `Dockerfile` copies the framework
from the tree. To move it into a repository of your own:

1. Copy this directory, and copy [compose/kafka.yaml](../compose/kafka.yaml) beside it.
   Copy `compose/ollama.yaml` too if you use a local model, or delete its `include` entry
   and the two `ollama` entries under `depends_on`.
2. In `compose.yaml` and `compose.tests.yaml`, set the build `context` to `.` and the
   `dockerfile` to `Dockerfile`, and point the `include` and `env_file` paths at your own
   copies.
3. In the `Dockerfile`, replace the two `COPY` lines and the `RUN` line with these, which
   install the framework from GitHub instead of from the tree:

   ```dockerfile
   COPY . starter
   RUN pip install --no-cache-dir \
       "agentic-eda @ https://github.com/milenvk/agentic-eda/archive/refs/heads/main.zip#subdirectory=lib/agentic_eda" \
       "./starter[dev]"
   ```

   For a build that never changes under you, replace `refs/heads/main` with a commit's
   hash.

The framework is the book's reference implementation. It is read and taught chapter by
chapter, and it carries no promise of a release cycle, so pin a commit.
