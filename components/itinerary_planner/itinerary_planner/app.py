"""The app that hosts the Itinerary Planner Agent, with the activator attached to it."""

from fastapi import FastAPI

from agentic_eda import console, eda

from .agent import agent, consumes, produces

console.configure_logging()

app = FastAPI(title="Itinerary Planner Agent")

eda.attach(app, agent, consumes=consumes, produces=produces)
