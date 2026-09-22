"""The app hosting the agent, with the container attached to it: the one line of plumbing."""

from fastapi import FastAPI

from agentic_eda import console, eda

from .agent import triage
from .events import ReviewReceived, ReviewTriaged

console.configure_logging()

app = FastAPI(title="Review Triage Agent")

eda.attach(
    app,
    triage,
    consumes=eda.consumes(ReviewReceived),
    produces=eda.produces(ReviewTriaged),
    source="ReviewTriageAgent",
)
