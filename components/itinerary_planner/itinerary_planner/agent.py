"""The Itinerary Planner Agent: a LangGraph graph, as its developer built it.

Nothing here knows about events or a broker. What the graph consumes and produces is
declared where it is hosted, in `app.py`.
"""

from agentic_eda.hydration import hydration

from .graph import build_graph
from .prompts import ask
from .suppliers_clients import airline, hotels

agent = build_graph(ask=ask, airline=airline(), hotels=hotels(), hydration=hydration())
