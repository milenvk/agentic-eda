"""The same agent on LangGraph Server: the activator attaches to the server's custom app.

For a team that runs LangGraph's own platform. The line is the one `itinerary_planner/app.py`
has; what differs is the host. Run it from this directory with `langgraph dev`, which needs
`langgraph-cli[inmem]`. It is outside the chapter's tests, since the server releases weekly.
"""

from fastapi import FastAPI

from agentic_eda import console, eda
from itinerary_planner.agent import agent, consumes, produces

console.configure_logging()

app = FastAPI()

eda.attach(app, agent, consumes=consumes, produces=produces)
