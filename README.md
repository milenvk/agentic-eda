# Agentic EDA — The Travel Agency Application

Companion code for *Event-Driven Agentic Architecture: Building enterprise-grade multi-agent
systems* by Milen Kovachev. One Travel Agency application, built chapter by chapter on an
event-driven backbone: autonomous agents from four frameworks (LangGraph, Google ADK, LlamaIndex,
CrewAI) and traditional deterministic services, integrated through a swappable `EventBroker`
port with Kafka as the first adapter.

## How this repository works

Everything lives on `main`, organized so the whole book's code is visible at a glance:

- **`components/`** — every component of the application as a self-contained directory:
  sources, Dockerfile, pinned dependencies, and unit tests. Components are added and
  replaced as the book progresses, never rewritten in place, so each chapter's teaching
  code stays in the tree.
- **`lib/travel_agency/`** — the shared kernel: the `EventBroker` port, its adapters, and
  the event-type constants.
- **`chapters/chNN/`** — one directory per chapter: a README describing what the chapter
  demonstrates and how to run it, the Docker Compose files that assemble exactly that
  chapter's components, and the chapter's demo scripts.

```
cd chapters/ch01
docker compose up          # that chapter's stack
docker compose run --rm demo
```

**Tags pin the book.** `main` moves as chapters are written and fixes land; tags don't. Each
chapter is tagged (`chNN-1.0`) when its manuscript freezes and re-tagged after errata, with a
release per tag — so the code in your printed copy is always reachable.

## The application design

| Document | Contents |
|---|---|
| [design/01_system_overview.adoc](design/01_system_overview.adoc) | The business, architecture, and every component: 12 agents, 4 vendor simulators, 4 deterministic components, the Ports |
| [design/02_workflows_and_events.adoc](design/02_workflows_and_events.adoc) | The workflow catalog and the event catalog |
| [design/03_chapter_mapping.adoc](design/03_chapter_mapping.adoc) | What each chapter adds to the system |
| [design/04_implementation_design.adoc](design/04_implementation_design.adoc) | The low-level design: port surfaces, event envelope, naming, and repository conventions |

## Requirements

- git
- Docker with Docker Compose
- An internet connection
- An API key in `.env` for one of Gemini (free tier available), OpenAI, or Claude — or no
  key at all, choosing free local models via Ollama

That is the whole list: every component, demo, and test runs in containers, identically on
Mac, Windows, and Linux. Host Python is never required.

Per-chapter setup instructions are in each chapter directory's README. Every chapter also
ships a minimal web UI (compose profile `ui`) — a live event view, with chat intake joining
in chapter 2 and a manager approval console in chapter 7 — for watching the workflows from
the customer's seat. The book's examples run from scripts and never depend on those UI
components; they are included for convenience.
