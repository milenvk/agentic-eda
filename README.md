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
  key at all, choosing free local models via Ollama (see
  [Local models with Ollama](#local-models-with-ollama))

That is the whole list: every component, demo, and test runs in containers, identically on
Mac, Windows, and Linux. Host Python is never required.

## Local models with Ollama

Every model choice is a block in the root `.env` (see `.env.example`), and the stack always
reaches Ollama at the same internal address — so switching between the options below changes
nothing else, and none of them involves chapter-specific setup.

**In Docker, on the CPU — zero install.** Uncomment the Ollama block with `OLLAMA_ENABLED=1`
in `.env`. Works on every machine; the first start downloads the model (about 2 GB) into a
volume. It is also the slowest option: on macOS in particular, Docker cannot use Apple GPUs,
so containerized Ollama always runs on the CPU there.

**On a modern Mac, with the Apple GPU (recommended on Apple Silicon).** Run Ollama natively
on the host — it uses the GPU through Metal automatically — and let the containers call it:

```sh
# Install and start Ollama on the host. (Or download the desktop app from
# https://ollama.com — it runs the same server from the menu bar.)
brew install ollama
brew services start ollama

# Download the model once.
ollama pull llama3.2
```

Then use the host block in `.env` (`OLLAMA_API_BASE=http://host.docker.internal:11434`) and
leave `OLLAMA_ENABLED` unset — no Ollama container runs at all.

**On Linux or Windows, with an NVIDIA GPU.** The containerized Ollama uses the GPU directly:
set `OLLAMA_GPU=1` in place of `OLLAMA_ENABLED=1` in `.env` once the runtime is in place.

- *Windows:* Docker Desktop with the WSL 2 backend and a current NVIDIA driver — GPU support
  is built in, nothing more to set up.
- *Linux:* install the NVIDIA driver and the
  [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html),
  then register the runtime with Docker:

  ```sh
  # Wire the NVIDIA runtime into Docker and restart the daemon.
  sudo nvidia-ctk runtime configure --runtime=docker
  sudo systemctl restart docker
  ```

- Verify on either system:

  ```sh
  # Prints your GPU's name if containers can reach it.
  docker run --rm --gpus all ubuntu nvidia-smi
  ```

The default model is `llama3.2` (about 2 GB). A larger machine runs a larger model by
changing the `LLM_MODEL` string in `.env`; the download happens automatically.

Per-chapter setup instructions are in each chapter directory's README. Every chapter also
ships a minimal web UI (compose profile `ui`) — a live event view, with chat intake joining
in chapter 2 and a manager approval console in chapter 7 — for watching the workflows from
the customer's seat. The book's examples run from scripts and never depend on those UI
components; they are included for convenience.
