"""The Front Desk — the application's minimal web UI, in its chapter 1 form.

A single page that watches every event flow through the system, live. Watch-only
for now: chat intake joins in chapter 2, the approval console in chapter 7. Out
of the book's page budget by design; included for convenience.
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse

from travel_agency import console
from travel_agency.broker import Event
from travel_agency.event_types import ITINERARY_PROPOSED, TRIP_REQUESTED
from travel_agency.kafka_broker import KafkaEventBroker

SOURCE = "FrontDesk"

log = logging.getLogger(SOURCE)

# One queue per connected browser; `relay` fans each event out to all of them.
watchers: set[asyncio.Queue] = set()


async def relay(event: Event) -> None:
    for queue in watchers:
        queue.put_nowait(event)


@asynccontextmanager
async def lifespan(app: FastAPI):
    console.configure_logging()
    async with KafkaEventBroker(
        os.environ["KAFKA_BOOTSTRAP_SERVERS"], client_name=SOURCE
    ) as broker:
        # One subscription per event type the system has so far; chapter 3
        # replaces this list with a single subscribe-all.
        await broker.subscribe(TRIP_REQUESTED, relay)
        await broker.subscribe(ITINERARY_PROPOSED, relay)
        consuming = asyncio.create_task(broker.run())
        yield
        consuming.cancel()


app = FastAPI(lifespan=lifespan)

PAGE = """\
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Front Desk</title>
<style>
  body { font-family: monospace; margin: 2rem; }
  .event { border-left: 3px solid #888; padding-left: 1rem; margin-bottom: 1rem;
           white-space: pre-wrap; }
</style>
</head>
<body>
<h1>Front Desk &mdash; live events</h1>
<div id="log"></div>
<script>
  new EventSource("/events").onmessage = (message) => {
    const entry = document.createElement("div");
    entry.className = "event";
    entry.textContent = JSON.stringify(JSON.parse(message.data), null, 2);
    document.getElementById("log").prepend(entry);
  };
</script>
</body>
</html>
"""


@app.get("/")
async def page() -> HTMLResponse:
    return HTMLResponse(PAGE)


@app.get("/events")
async def events() -> StreamingResponse:
    queue: asyncio.Queue = asyncio.Queue()
    watchers.add(queue)

    async def stream():
        try:
            while True:
                event = await queue.get()
                data = json.dumps(
                    {
                        "type": event.type,
                        "id": event.id,
                        "source": event.source,
                        "payload": event.payload,
                    }
                )
                yield f"data: {data}\n\n"
        finally:
            watchers.discard(queue)

    return StreamingResponse(stream(), media_type="text/event-stream")
