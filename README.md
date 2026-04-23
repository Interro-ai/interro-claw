# Interro-Claw — Autonomous Development System

[![PyPI version](https://img.shields.io/pypi/v/interro-claw.svg)](https://pypi.org/project/interro-claw/)
[![Python](https://img.shields.io/pypi/pyversions/interro-claw.svg)](https://pypi.org/project/interro-claw/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Created by Interro-AI](https://img.shields.io/badge/Created%20by-Interro--AI-blue)](https://interro-ai.com)

An open-source, multi-agent AI orchestrator that **plans, builds, tests, secures, refactors, and deploys** software projects from a single CLI command. Works with **Claude, OpenAI, Ollama, NVIDIA NIM, or Groq** — cloud, local, or free Groq API.

| Doc                                                  | What's inside                                                                                                                 |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| **[README_ARCHITECTURE.md](README_ARCHITECTURE.md)** | System architecture, execution pipeline, project structure, configuration reference, DAG scheduling, agent internals          |
| **[README_FEATURES.md](README_FEATURES.md)**         | All 26 features explained in detail, USP comparison table (30 dimensions vs 6 competitors), token telemetry, MCP server guide |

---

## Quick Start (PyPI)

```bash
pip install interro-claw
interro-claw --init          # generates .env, walks you through provider setup
interro-claw --chat          # start chatting
```

---

## Installation (from source)

### Prerequisites

- **Python 3.11+** — check with `python --version`
- **Rust toolchain** — [install Rust](https://rustup.rs/) (needed for pydantic-core build)
- **Microsoft C++ Build Tools** — [download](https://visualstudio.microsoft.com/visual-cpp-build-tools/) (Windows only)

### Step 1: Clone and set up virtual environment

```bash
git clone https://github.com/interro-claw/interro-claw.git
cd interro-claw/interro_claw

# Create virtual environment
python -m venv .venv

# Activate it
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# Windows CMD:
.\.venv\Scripts\activate.bat
# macOS / Linux:
source .venv/bin/activate
```

### Step 2: Install Interro-Claw

```bash
# Install interro-claw as a CLI command (editable mode for development)
pip install -e .

# (Optional) Install with MCP server support
pip install -e ".[mcp]"

# (Optional) Install with dev tools (pytest, ruff)
pip install -e ".[dev]"
```

> **What does `pip install -e .` do?**
> It reads `pyproject.toml`, installs all dependencies, and registers the `interro-claw`
> command in your terminal. After install, just type `interro-claw`.

### Step 3: Set required environment variables

Interro-Claw needs **2 mandatory variables** to work. Everything else is optional.

#### Required Variables

| Variable                  | Description                                                         | Example       |
| ------------------------- | ------------------------------------------------------------------- | ------------- |
| `LLM_PROVIDER`            | Which LLM to use: `openai`, `claude`, `ollama`, `nvidia`, or `groq` | `openai`      |
| API key for your provider | See table below                                                     | `sk-proj-...` |

| Provider           | Required API Key Variable | Local? / Free?        |
| ------------------ | ------------------------- | --------------------- |
| OpenAI             | `OPENAI_API_KEY`          | No — cloud            |
| Claude (Anthropic) | `CLAUDE_API_KEY`          | No — cloud            |
| NVIDIA NIM         | `NVIDIA_API_KEY`          | No — cloud            |
| Ollama             | _(none — no key needed)_  | **Yes — fully local** |
| Groq               | `GROQ_API_KEY`            | **Yes — free tier**   |

#### Option A: Create a .env file (recommended)

```bash
# Copy the example file
cp .env.example .env

# Edit it — at minimum, set these two lines:
# LLM_PROVIDER=openai
# OPENAI_API_KEY=sk-proj-your-key-here
# Or for Groq (free):
# LLM_PROVIDER=groq
# GROQ_API_KEY=your-groq-key-here
# GROQ_MODEL=llama3-70b-8192
```

#### Option B: Set environment variables directly

```bash
# Windows PowerShell:
$env:LLM_PROVIDER = "openai"
$env:OPENAI_API_KEY = "sk-proj-your-key-here"

# Windows CMD:
set LLM_PROVIDER=openai
set OPENAI_API_KEY=sk-proj-your-key-here

# macOS / Linux:
export LLM_PROVIDER=openai
export OPENAI_API_KEY=sk-proj-your-key-here
```

#### Option C: Use Ollama locally (no API key, free)

```bash
# Windows PowerShell:
$env:LLM_PROVIDER = "ollama"
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
$env:OLLAMA_MODEL = "llama3"

# macOS / Linux:
export LLM_PROVIDER=ollama
export OLLAMA_BASE_URL=http://127.0.0.1:11434
export OLLAMA_MODEL=llama3
```

> **Corporate network?** If you get `403 URLBlocked` when using Ollama, add:
> `$env:NO_PROXY = "127.0.0.1,localhost"` (Windows) or `export NO_PROXY=127.0.0.1,localhost` (Linux/Mac)

#### Option D: Just run it — interactive setup

```bash
interro-claw --chat
# It will ask you to pick a provider and enter your API key
```

#### All Environment Variables Reference

<details>
<summary>Click to expand full variable list</summary>

**LLM Configuration:**

| Variable          | Default                               | Description                                        |
| ----------------- | ------------------------------------- | -------------------------------------------------- |
| `LLM_PROVIDER`    | _(required)_                          | `openai` / `claude` / `ollama` / `nvidia` / `groq` |
| `OPENAI_API_KEY`  | _(required for openai)_               | OpenAI API key                                     |
| `OPENAI_MODEL`    | `gpt-4o`                              | OpenAI model name                                  |
| `CLAUDE_API_KEY`  | _(required for claude)_               | Anthropic API key                                  |
| `CLAUDE_MODEL`    | `claude-sonnet-4-20250514`            | Claude model name                                  |
| `NVIDIA_API_KEY`  | _(required for nvidia)_               | NVIDIA NIM API key                                 |
| `NVIDIA_BASE_URL` | `https://integrate.api.nvidia.com/v1` | NVIDIA endpoint                                    |
| `NVIDIA_MODEL`    | `meta/llama-3.3-70b-instruct`         | NVIDIA model                                       |
| `OLLAMA_BASE_URL` | `http://localhost:11434`              | Ollama server URL                                  |
| `OLLAMA_MODEL`    | `llama3`                              | Ollama model name                                  |
| `GROQ_API_KEY`    | _(required for groq)_                 | Groq API key                                       |
| `GROQ_MODEL`      | `llama3-70b-8192`                     | Groq model name                                    |

**Orchestrator:**

| Variable                | Default | Description                                   |
| ----------------------- | ------- | --------------------------------------------- |
| `MAX_CONCURRENT_AGENTS` | `2`     | How many agents run in parallel               |
| `RATE_LIMIT_RPM`        | `20`    | Max LLM requests per minute                   |
| `LOG_LEVEL`             | `INFO`  | `DEBUG` / `INFO` / `WARNING` / `ERROR`        |
| `ENABLE_STREAMING`      | `0`     | `1` to stream tokens as they arrive           |
| `ENABLE_RESPONSE_CACHE` | `1`     | `1` to cache LLM responses                    |
| `CACHE_TTL_SECONDS`     | `3600`  | Cache expiry (seconds)                        |
| `MAX_REFLECTION_DEPTH`  | `1`     | Self-critique rounds per agent (0 to disable) |
| `ENABLE_REFLECTION`     | `1`     | `0` to disable self-reflection entirely       |

**Guardrails:**

| Variable                    | Default | Description                    |
| --------------------------- | ------- | ------------------------------ |
| `MAX_TOKENS_PER_CALL`       | `4096`  | Max output tokens per LLM call |
| `MAX_LLM_CALLS_PER_SESSION` | `200`   | Hard cap on total LLM calls    |
| `MAX_OUTPUT_CHARS`          | `50000` | Max output size per agent      |
| `MAX_AGENT_RUNTIME_SECONDS` | `300`   | Timeout per agent              |

**Project:**

| Variable             | Default           | Description                        |
| -------------------- | ----------------- | ---------------------------------- |
| `DEFAULT_PROJECT_ID` | `default`         | Default project for memory scoping |
| `SKILLS_DIR`         | `(auto-detected)` | Custom skills directory path       |

</details>

### Step 4: Verify installation

```bash
# Should print version and CLI help
interro-claw --version
interro-claw --help
```

**Troubleshooting:**

- `maturin failed` / `cargo build` errors → Install Rust and C++ Build Tools
- `interro-claw: command not found` → Run `pip install -e .` again (make sure your venv is active)
- `ModuleNotFoundError` → Make sure you ran `pip install -r requirements.txt` first

---

## Usage Guide

### Single-Shot Goal (one command, full agent orchestration)

Give Interro-Claw a goal and walk away. It will plan, assign agents, build, test, and verify:

```bash
# Build a complete project
interro-claw "Build a REST API with FastAPI and user authentication"

# With streaming (see tokens as they arrive)
interro-claw --stream "Create a React dashboard with charts"

# With verbose logging (see every agent decision, cache hit, telemetry)
interro-claw -v "Add a payment system with Stripe integration"
```

After the run completes, generated files are written to `artifacts/` and a session report is printed.

### Matrix Mode — Persistent Interactive Session

The most powerful mode. Opens a persistent shell where you can type goals, ask questions, and give follow-up instructions — all with full agent orchestration:

```bash
interro-claw --matrix-mode
```

**What happens in Matrix Mode:**

1. You type anything — a goal, a question, or a clarification
2. Interro-Claw's LLM classifies your intent:
   - **Goal** → Full multi-agent orchestration (plan → build → test → verify)
   - **Chat** → Direct LLM answer (no agents, instant response)
   - **Clarify** → Asks you for more details before proceeding
3. Conversation history is maintained across turns
4. Type `quit` or `exit` to end the session

```
> Build a REST API for a todo app
  [PlannerAgent] Decomposing goal into 6 tasks...
  [ArchitectAgent] Designing system architecture...
  [BackendAgent] Writing FastAPI endpoints...
  ...

> Now add authentication with JWT tokens
  [PlannerAgent] Updating plan with auth tasks...
  [SecurityAgent] Reviewing auth implementation...
  ...

> What files did we create?
  [Chat] We created the following files:
  - backend/main.py (FastAPI app)
  - backend/auth.py (JWT middleware)
  ...

> quit
  Session ended. Session ID: abc123def456
```

### Project Management — Isolate Your Work

Each project gets its own memory, sessions, and context. Perfect when working across multiple codebases:

```bash
# Create a new project (interactive wizard — asks for name, path, description)
interro-claw --create-project

# List all your registered projects
interro-claw --list-projects

# Run a goal scoped to a specific project
interro-claw --project my-api "Add rate limiting middleware"

# Matrix mode with project scoping
interro-claw --matrix-mode --project my-api
```

**What project IDs do:**

- All agent memory, learned patterns, and shared knowledge are scoped to that project
- Sessions are tracked per-project (so `--auto-resume` picks up the right one)
- File context and dependency graphs are project-specific
- If you don't specify `--project`, everything goes to the `default` project

### Session Resume — Pick Up Where You Left Off

Every run gets a unique session ID. You can resume any previous session:

```bash
# List your recent session IDs
interro-claw --get-session

# Output:
#   Session ID                  | Project  | Goal                              | Status
#   abc123def456                | my-api   | Build REST API with FastAPI       | completed
#   xyz789ghi012                | my-api   | Add authentication with JWT       | incomplete
#   ...

# Resume a specific session by ID
interro-claw --resume xyz789ghi012 "Continue adding JWT authentication"

# Auto-resume the last incomplete session (no need to remember IDs)
interro-claw --auto-resume "Keep going"

# Combine with project scoping
interro-claw --project my-api --auto-resume
```

**When to use resume:**

- Your terminal crashed or you closed it mid-run
- You want to give follow-up instructions on a previous session
- You stopped for lunch and want to continue

### Chat Mode — Just Talk to the LLM

No agents, no planning, no orchestration. Just direct conversation with your configured LLM:

```bash
interro-claw --chat
```

Maintains conversation history within the session. Useful for quick questions or debugging ideas.

### MCP Server Mode — Use Interro-Claw from VS Code Copilot / Claude Desktop

MCP (Model Context Protocol) lets AI assistants like **VS Code Copilot** or **Claude Desktop** call Interro-Claw's tools directly from chat. Interro-Claw runs as a local subprocess — Copilot spawns it, sends JSON-RPC messages over stdin/stdout, and displays results.

#### Step 1: Install with MCP support

```bash
pip install -e ".[mcp]"
```

#### Step 2: Configure VS Code

Create `.vscode/mcp.json` in your project:

```json
{
  "servers": {
    "interro-claw": {
      "command": "interro-claw",
      "args": ["--mcp"],
      "env": {
        "LLM_PROVIDER": "claude",
        "ANTHROPIC_API_KEY": "${input:anthropicKey}"
      }
    }
  },
  "inputs": [
    {
      "id": "anthropicKey",
      "type": "promptString",
      "description": "Anthropic API key for Interro-Claw",
      "password": true
    }
  ]
}
```

For **Claude Desktop**, add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "interro-claw": {
      "command": "interro-claw",
      "args": ["--mcp"],
      "env": {
        "LLM_PROVIDER": "claude",
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

#### Step 3: Use it in chat

Once configured, Copilot sees Interro-Claw's 8 tools and **automatically calls the right one** based on what you type. Here's how each tool activates:

| Tool                    | What it does                                                                                                   | Copilot calls it when you say...                                                    |
| ----------------------- | -------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `interro_plan`          | Deploys 9 agents with DAG scheduling to break a goal into parallel task batches                                | _"interro-claw plan a REST API"_, _"plan with agents"_, _"multi-agent plan"_        |
| `interro_execute`       | Full autonomous build: plan → build → test → secure → refactor with blast-radius pruning and snapshot rollback | _"interro-claw build a REST API"_, _"autonomous build"_, _"build with agents"_      |
| `interro_chat`          | Send a message to Interro-Claw's configured LLM (Claude/OpenAI/Ollama)                                         | _"interro-claw chat"_, _"ask interro-claw"_                                         |
| `interro_analyze`       | AST-level project analysis: languages, frameworks, dependency graph                                            | _"interro-claw analyze this project"_, _"analyze with interro-claw"_                |
| `interro_blast_radius`  | BFS traversal (4-depth) through dependency graph to find every affected file                                   | _"blast radius of auth.py"_, _"what depends on this file?"_, _"impact analysis"_    |
| `interro_memory_recall` | Search Interro-Claw's persistent memory (past decisions, patterns, conventions)                                | _"what did interro-claw learn?"_, _"recall memory"_, _"what patterns were found?"_  |
| `interro_session_list`  | List past sessions with IDs, goals, and status                                                                 | _"show my interro-claw sessions"_, _"what did interro-claw run?"_                   |
| `interro_telemetry`     | Token savings report: cache hits, blast radius pruning, cost saved                                             | _"how much did interro-claw save?"_, _"interro-claw telemetry"_, _"cache hit rate"_ |

#### When does Copilot call Interro-Claw vs handle it itself?

Copilot's LLM reads each tool's description and decides whether it or an external tool is a better fit:

| You type in Copilot chat                         | What happens               | Why                                                             |
| ------------------------------------------------ | -------------------------- | --------------------------------------------------------------- |
| _"create a button component"_                    | **Copilot handles it**     | Simple single-file edit — Copilot can do this natively          |
| _"use interro-claw to build a full-stack app"_   | **Interro-Claw activates** | Explicit mention of "interro-claw" matches tool triggers        |
| _"plan this with agents"_                        | **Interro-Claw activates** | Matches `interro_plan` trigger phrase "plan with agents"        |
| _"what's the blast radius of changing auth.py?"_ | **Interro-Claw activates** | Only `interro_blast_radius` can do dependency impact analysis   |
| _"build a REST API"_                             | **Copilot handles it**     | No explicit interro-claw mention; Copilot prefers its own tools |
| _"autonomous build of a microservice"_           | **Interro-Claw activates** | Matches `interro_execute` trigger "autonomous build"            |

**Key rule:** For reliable activation, include "interro-claw" or use unique phrases like "blast radius", "plan with agents", "autonomous build" in your prompt.

#### Example conversation in VS Code Copilot

```
You:     "Use interro-claw to plan a REST API with user authentication"
Copilot: [Calls interro_plan tool]
         "Interro-Claw generated a 6-task plan:
          Batch 0: ArchitectAgent — design system architecture
          Batch 1: BackendAgent — implement endpoints + SecurityAgent — JWT auth
          Batch 2: TestAgent — write integration tests
          Batch 3: RefactorAgent — cleanup and optimization"

You:     "Now execute that plan"
Copilot: [Calls interro_execute tool]
         "9 agents completed 6 tasks in 3 parallel batches.
          Files written to artifacts/. Session ID: abc123"

You:     "What's the blast radius if I change auth.py?"
Copilot: [Calls interro_blast_radius tool]
         "4 files affected: auth.py → routes.py → middleware.py → app.py"

You:     "How much did that save in tokens?"
Copilot: [Calls interro_telemetry tool]
         "Cache hit rate: 68%. Tokens saved: ~51,000. Est. cost saved: $0.15"
```

> **Note:** Interro-Claw must be installed locally — the MCP server runs as a subprocess on your machine via stdio transport. Remote hosting (SSE/HTTP) is not yet supported.

See [README_FEATURES.md — MCP Integration](README_FEATURES.md#what-is-mcp-model-context-protocol) for the full technical deep-dive.

### Memory Inspection CLI

Inspect and manage the SQLite memory database directly:

```bash
python memory_cli.py stats              # Memory statistics
python memory_cli.py recall AgentName   # Recall agent-specific memory
python memory_cli.py knowledge --topic backend   # Search shared knowledge
python memory_cli.py sessions           # List all sessions
python memory_cli.py clear-cache        # Clear response cache
```

---

## CLI Reference

| Flag               | Description                                                |
| ------------------ | ---------------------------------------------------------- |
| `"<goal>"`         | Single-shot: give a goal, get multi-agent orchestration    |
| `--matrix-mode`    | Persistent interactive session (goal/chat/clarify routing) |
| `--chat`           | Pure LLM conversation (no agents)                          |
| `--project <id>`   | Scope all memory and sessions to a named project           |
| `--create-project` | Create a new project interactively                         |
| `--list-projects`  | List all registered projects                               |
| `--resume <id>`    | Resume a previous session by its ID                        |
| `--auto-resume`    | Auto-resume the last incomplete session                    |
| `--get-session`    | List recent session IDs (use with `--resume`)              |
| `--stream`         | Stream LLM tokens as they arrive                           |
| `--verbose` / `-v` | Detailed logs + telemetry at session end                   |
| `--mcp`            | Run as MCP server (stdio transport)                        |
| `--version`        | Print version                                              |

---

## How It Works (30-Second Overview)

```
You: "Build a REST API with auth"
 │
 ▼
PlannerAgent → breaks goal into 6 tasks → assigns each to a specialist agent
 │
 ▼
DAG Scheduler → runs independent agents in parallel batches
 │
 ├─ Batch 0: ArchitectAgent (system design)
 ├─ Batch 1: BackendAgent + FrontendAgent (parallel)
 ├─ Batch 2: TestAgent + SecurityAgent (parallel)
 └─ Batch 3: RefactorAgent (cleanup)
 │
 ▼
Each Agent: selects relevant files → calls LLM (cached) → uses tools → self-reflects → guardrails check
 │
 ▼
Output: artifacts/ folder + session report + memory updated for next time
```

For the full architecture deep-dive, see [README_ARCHITECTURE.md](README_ARCHITECTURE.md).

For every feature explained, competitive comparison, and MCP setup, see [README_FEATURES.md](README_FEATURES.md).
