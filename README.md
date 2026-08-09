# Agentic EDA — The Travel Agency Application

Companion code for *Event-Driven Agentic Architecture: Building enterprise-grade multi-agent
systems* by Milen Kovachev. One Travel Agency application, built chapter by chapter on an
event-driven backbone: autonomous agents from four frameworks (LangGraph, Google ADK, LlamaIndex,
Pydantic AI) and traditional deterministic services, integrated through a swappable `EventBroker`
port with Kafka as the first adapter.

## How this repository works

**One branch per chapter.** Each `chNN` branch is the complete, runnable application exactly as it
stands at the end of that chapter, branched from the chapter before it:

```
git switch ch05        # the application as of Chapter 5
docker compose up      # that chapter's full stack
git diff ch04..ch05    # exactly what Chapter 5 added
```

`main` carries only this README, the application design, and tooling — never application code.
Chapter branches appear here as the book's chapters are written.

**Fixes cascade forward.** A change that belongs to chapter N is implemented on `chNN` and merged
forward through every later branch with [`scripts/cascade.sh`](scripts/cascade.sh). Merges flow
forward only, and published chapter branches are never rebased.

**Tags pin the book.** Chapter branches move as fixes cascade; tags don't. Each chapter is tagged
(`chNN-1.0`) when the manuscript freezes and re-tagged after errata, with a release per tag — so
the code in your printed copy is always reachable.

## The application design

| Document | Contents |
|---|---|
| [design/01_system_overview.adoc](design/01_system_overview.adoc) | The business, architecture, and every component: 12 agents, 3 vendor simulators, 4 deterministic components, the Ports |
| [design/02_workflows_and_events.adoc](design/02_workflows_and_events.adoc) | The workflow catalog and the event catalog |
| [design/03_chapter_mapping.adoc](design/03_chapter_mapping.adoc) | What each chapter adds to the system |

## Requirements

- Python 3.11+
- Docker with Docker Compose
- One cloud LLM API key (any LiteLLM-supported provider); [Ollama](https://ollama.com) as the
  optional zero-cost local fallback

Per-chapter setup instructions live in each chapter branch's README.
