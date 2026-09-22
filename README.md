# Agentic EDA: a Framework, and the Travel Agency Built on It

Companion code for *Event-Driven Agentic Architecture: Building enterprise-grade multi-agent
systems* by Milen Kovachev. Two things are here, kept apart on purpose:

- **`agentic_eda`, a framework** for attaching an agent of any framework to an event broker:
  a swappable `EventBroker` port with Kafka as the first adapter, event contracts as code,
  and a container that validates what comes in and what goes out. It names no business.
- **The Travel Agency**, one application built on it chapter by chapter: autonomous agents
  from four frameworks (LangGraph, Google ADK, LlamaIndex, CrewAI), traditional
  deterministic services, and simulated suppliers.

To build an application of your own, start from [starter/](starter/): the smallest
application on the framework, in a business that is not travel, with a README walking
through making it yours.

## How this repository works

Everything lives on `main`, organized so the whole book's code is visible at a glance:

- **`components/`**: every component of the application as a self-contained directory
  containing sources, Dockerfile, pinned dependencies, and unit tests. Components are added
  and replaced as the book progresses, never rewritten in place, so each chapter's teaching
  code stays in the tree.
- **`lib/agentic_eda/`**: the framework, holding the `EventBroker` port and its adapters,
  the `@event` contracts, and the agent container. It never imports the application, and its
  test suite runs in an image without it. It is the book's reference implementation, taught
  one part per chapter, with no promise of a release cycle.
- **`lib/travel_agency/`**: the application's shared code, holding the event-type constants,
  the event catalog as code, and the simulators' world seed.
- **`starter/`**: a small application of another business on the framework alone, to copy
  and make your own.
- **`chapters/chNN/`**: one directory per chapter, with a README describing what the chapter
  demonstrates and how to run it, the Docker Compose files that assemble exactly that
  chapter's components, and the chapter's demo scripts.

Working in a chapter's directory brings up exactly that chapter's stack:

```sh
cd chapters/ch01
docker compose up -d --build
```

**Tags pin the book.** `main` moves as chapters are written and fixes land; tags don't. Each
chapter is tagged (`chNN-1.0`) when its manuscript freezes and re-tagged after errata, with a
release per tag, so the code in your printed copy is always reachable.

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
- An API key in `.env` for one of Gemini (free tier available), OpenAI, or Claude, or no
  key at all, choosing free local models via Ollama (see
  [Local models with Ollama](#local-models-with-ollama))

That is the whole list: every component, demo, and test runs in containers, identically on
Mac, Windows, and Linux. Host Python is never required.

## Local models with Ollama

Every model choice is a block in the root `.env` (see `.env.example`), and the stack always
reaches Ollama at the same internal address, so switching between the options below changes
nothing else, and none of them involves chapter-specific setup.

**In Docker, on the CPU (zero install).** Uncomment the Ollama block with `OLLAMA_ENABLED=1`
in `.env`. Works on every machine; the first start downloads the model (about 2 GB) into a
volume. It is also the slowest option: on macOS in particular, Docker cannot use Apple GPUs,
so containerized Ollama always runs on the CPU there.

**On a modern Mac, with the Apple GPU (recommended on Apple Silicon).** Run Ollama natively
on the host, where it uses the GPU through Metal automatically, and let the containers call
it. Install and start Ollama, then download the model once. (Installing the
[desktop app](https://ollama.com) instead of using brew works the same; it runs the same
server from the menu bar.)

```sh
brew install ollama
brew services start ollama
ollama pull llama3.2
```

Then use the host block in `.env` (`OLLAMA_API_BASE=http://host.docker.internal:11434`) and
leave `OLLAMA_ENABLED` unset: no Ollama container runs at all.

**On Linux or Windows, with an NVIDIA GPU.** The containerized Ollama uses the GPU directly:
set `OLLAMA_GPU=1` in place of `OLLAMA_ENABLED=1` in `.env` once the runtime is in place.

- *Windows:* Docker Desktop with the WSL 2 backend and a current NVIDIA driver. GPU support
  is built in; nothing more to set up.
- *Linux:* install the NVIDIA driver and the
  [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html),
  then register the runtime with Docker and restart the daemon:

  ```sh
  sudo nvidia-ctk runtime configure --runtime=docker
  sudo systemctl restart docker
  ```

- Verify on either system; this prints your GPU's name if containers can reach it:

  ```sh
  docker run --rm --gpus all ubuntu nvidia-smi
  ```

The default model is `llama3.2` (about 2 GB). A larger machine runs a larger model by
changing the `LLM_MODEL` string in `.env`; the download happens automatically.

Per-chapter setup instructions are in each chapter directory's README. A minimal web UI (a
chat front door with a live event view) joins in chapter 3 and gains a manager approval
console in chapter 8. The book's examples run from scripts and never depend on it; it is
included for convenience.
