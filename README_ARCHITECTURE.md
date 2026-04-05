# Interro-Claw — Architecture & Technical Reference

> This document covers system architecture, execution pipeline, configuration, and internal design.
> For features, USP comparison, and user-facing capabilities, see [README_FEATURES.md](README_FEATURES.md).

---

## System Requirements

- **Python 3.11+** (check with `python --version`)
- **Rust toolchain** ([Install Rust](https://rustup.rs/)) — needed for pydantic-core build
- **Microsoft C++ Build Tools** ([Download](https://visualstudio.microsoft.com/visual-cpp-build-tools/)) — Windows only

**Troubleshooting:**

- `maturin failed` / `cargo build` errors → install Rust and C++ Build Tools
- `subprocess-exited-with-error` for pydantic-core → check Python version

---

## Project Structure

```
orchestrator.py                    ← Master controller + DAG-aware task dispatcher
├── config.py                      ← All settings (LLM, memory, guardrails, ADS, etc.)
├── llm_client.py                  ← Unified Claude / OpenAI / Ollama / NVIDIA NIM
│                                     (2-level cache + retry + streaming)
├── memory.py                      ← SQLite memory (7 tables + vector search + projects)
├── telemetry.py                   ← Token reduction telemetry (6 metrics)
├── memory_cli.py                  ← CLI to inspect/manage memory DB
├── task_queue.py                  ← Priority heap + concurrency + rate limiting
├── guardrails.py                  ← Base safety layer
├── skills_manager.py              ← Auto-loads .md skill files into agent prompts
├── agent_tools.py                 ← Tool registry (built-in tools agents can invoke)
├── project_context.py             ← Project analysis (languages, frameworks, deps)
├── dep_graph.py                   ← Dependency graph + blast-radius BFS
├── file_selector.py               ← Intelligent file selection with blast-radius scoring
├── context_chunker.py             ← AST-aware file chunking
├── result_verifier.py             ← 4-axis output verification
├── profiler.py                    ← Performance profiling (cProfile, Scalene, Lighthouse)
├── model_router.py                ← Smart model routing (heavy/medium/light)
├── hitl.py                        ← Human-in-the-loop checkpoints
├── mcp_server.py                  ← MCP server (8 tools, 2 resources)
│
├── memory/                        ← 3-Layer Memory Hierarchy
│   ├── short_term.py              ← Per-task JSON ephemeral memory (STM)
│   ├── working.py                 ← Per-project SQLite working memory (WM)
│   └── long_term.py               ← Global SQLite long-term memory (LTM)
│
├── graph_engine/                  ← Project Graph Engine
│   └── engine.py                  ← AST-based symbol extraction + incremental SHA256 hashing
│
├── context_engine/                ← Unified Context Engine
│   └── engine.py                  ← Assembles AgentContext from all sources
│
├── indexer/                       ← File Indexer
│   └── file_indexer.py            ← Incremental file indexing with symbol extraction
│
├── guardrails_v2/                 ← Enhanced Guardrails
│   ├── enhanced.py                ← 17 anti-pattern detectors, loop prevention
│   └── snapshots.py               ← Snapshot manager with rollback support
│
├── sandbox/                       ← Execution Sandbox
│   └── runner.py                  ← Isolated subprocess execution (Python/Node/Shell)
│
├── delegation/                    ← Agent Delegation Protocol
│   └── protocol.py                ← Async inter-agent task delegation
│
├── dag_scheduler/                 ← DAG Task Scheduler
│   └── scheduler.py               ← Topological sort + parallel batch detection
│
├── skills/                        ← Skill .md files (auto-loaded at startup)
│   ├── python-best-practices.md
│   ├── azure-deployment.md
│   ├── frontend-standards.md
│   ├── security-guidelines.md
│   ├── testing-strategy.md
│   └── ... (11 skill files)
│
└── agents/
    ├── base_agent.py              ← Base: reflection, tools, 3-layer memory, delegation
    ├── planner_agent.py           ← Goal → structured JSON task plan
    ├── architect_agent.py         ← System design, tech stack, folder structure
    ├── backend_agent.py           ← FastAPI / Node.js backend code
    ├── frontend_agent.py          ← React / Next.js frontend code
    ├── ops_agent.py               ← Bicep/Terraform, CI/CD, Docker
    ├── test_agent.py              ← Playwright E2E, pytest integration tests
    ├── security_agent.py          ← Threat modeling, static analysis, STRIDE
    └── refactor_agent.py          ← Performance, readability, UX improvements
```

---

## 3-Layer Memory Hierarchy

```
Short-Term Memory (STM)          Working Memory (WM)           Long-Term Memory (LTM)
  Per-task, ephemeral              Per-project, persistent        Global, cross-project
  JSON files in runtime/           SQLite per project             SQLite global DB
  ┌──────────────────┐            ┌──────────────────┐          ┌──────────────────┐
  │ task variables    │            │ summaries        │          │ patterns         │
  │ intermediate      │            │ file_context     │          │ coding_style     │
  │ scratch data      │            │ dependency_info  │          │ optimization     │
  │ cleared on finish │            │ reasoning_chain  │          │ strategies       │
  └──────────────────┘            └──────────────────┘          └──────────────────┘
```

**Central memory.py (7 SQLite tables):**

| Table              | Purpose                                    |
| ------------------ | ------------------------------------------ |
| `agent_memory`     | Per-agent reasoning, decisions, learnings  |
| `shared_knowledge` | Cross-agent facts with confidence scores   |
| `session_history`  | Full task → response audit trail           |
| `task_memory`      | Per-task step/diff/reasoning logs          |
| `response_cache`   | Content-addressable LLM response cache     |
| `vectors`          | Embedding-based semantic similarity search |
| `projects`         | Multi-project registry with metadata       |

---

## DAG-Based Task Scheduling

```
PlannerAgent generates plan → DAGScheduler builds execution graph
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
            Batch 0:         Batch 1:         Batch 2:
            ArchitectAgent   Backend + Front   Test + Security
            (sequential)     (parallel)        (parallel)
                                    │
                                    ▼
                              Batch 3:
                              RefactorAgent
```

**Default dependency rules:**

```
Planner/Architect → (no deps)
Backend/Frontend  → Architecture
Ops               → Architecture
Tests             → Backend + Frontend
Security          → Backend + Frontend + Ops
Refactor          → Backend + Frontend + Tests + Security
```

Tasks at the same depth run **in parallel**. Dependencies between batches are enforced via Kahn's algorithm with cycle detection.

---

## Smart Model Routing

| Complexity | Model                  | When Used                                      |
| ---------- | ---------------------- | ---------------------------------------------- |
| **Heavy**  | Claude Opus / GPT-4o   | Architecture, deep debugging, complex planning |
| **Medium** | Default provider model | General coding, analysis                       |
| **Light**  | GPT-4o-mini / Ollama   | Simple edits, test generation, refactoring     |

**Classification rules:**

- **Agent-based:** PlannerAgent & ArchitectAgent always HEAVY
- **Keyword-based:** Regex patterns for complexity escalation
- **Explicit hints:** Task can specify complexity override

---

## Execution Pipeline

```
User Goal (or --resume / --auto-resume)
  │
  ▼
PlannerAgent  →  JSON task list [{task, agent}, ...]
  │
  ▼
HITL Checkpoint: post_plan (approve plan)
  │
  ▼
DAGScheduler  →  Topological sort → Parallel batches
  │
  ▼
HITL Checkpoint: pre_execute (approve execution)
  │
  ▼
TaskQueue (priority heap + semaphore + rate limiter + dependency wait)
  │
  ▼
Agent Execution Loop:
  1.  STM: Record task start
  2.  Model Router: Select model for task complexity
  3.  Build system prompt (base + skills + tools + LTM + WM + project graph)
  4.  Build user message (memory + semantic search + file selection + task)
  5.  LLM call (2-level cache → retry → streaming)
  6.  Tool-use loop (parse tool blocks, execute — up to 5 rounds)
  7.  Self-reflection loop (critique + improve — up to 3 rounds)
  8.  Enhanced guardrails (snapshots, anti-patterns, loop detection)
  9.  Result verification (4-axis scoring)
  10. Store to memory (all 3 layers + vector embedding)
  11. Telemetry: record cache hits/misses, context savings
  12. STM: Clear ephemeral data
  │
  ▼
Delegation queue processed → artifacts/ + memory updated
```

---

## Agent Reference

| Agent                 | Responsibility                                              |
| --------------------- | ----------------------------------------------------------- |
| **PlannerAgent**      | Breaks goals into structured task plans (JSON)              |
| **ArchitectAgent**    | System architecture, folder structure, tech stack           |
| **BackendAgent**      | Backend code (FastAPI / Node.js)                            |
| **FrontendAgent**     | Frontend code (React / Next.js)                             |
| **OpsAgent**          | IaC (Bicep/Terraform), CI/CD YAML, Dockerfiles              |
| **TestAgent**         | E2E tests (Playwright), integration tests (pytest)          |
| **SecurityAgent**     | Threat modelling (STRIDE), static analysis, dependency scan |
| **RefactorAgent**     | Performance, readability, UX improvements                   |
| **ConsolidatorAgent** | User-facing session summary with run commands               |

---

## Agent Delegation Protocol

Agents can delegate sub-tasks to other agents during execution:

```python
# Inside any agent's run:
result = await self.delegate(
    "SecurityAgent",
    "Review this code for vulnerabilities",
    context={"code": code}
)
```

Supports **blocking** (wait for result) and **async** (fire-and-forget) modes. Max delegation chain depth is configurable (`MAX_DELEGATION_DEPTH`).

---

## Configuration Reference

### Environment Variable Precedence

1. **Session (runtime) variables** — highest priority
2. **Global environment variables** (`os.environ`)
3. **.env file** — lowest (CWD → `~/.interro-claw/.env`)

### Core Settings

| Variable                    | Default | Description                               |
| --------------------------- | ------- | ----------------------------------------- |
| `LLM_PROVIDER`              | —       | `claude`, `openai`, `ollama`, or `nvidia` |
| `ANTHROPIC_API_KEY`         | —       | API key for Claude                        |
| `OPENAI_API_KEY`            | —       | API key for OpenAI                        |
| `MAX_CONCURRENT_AGENTS`     | 4       | Parallel agent execution limit            |
| `RATE_LIMIT_RPM`            | 30      | Token-bucket rate limit                   |
| `ENABLE_RESPONSE_CACHE`     | 1       | Skip duplicate LLM calls                  |
| `CACHE_TTL_SECONDS`         | 3600    | Cache expiry time                         |
| `ENABLE_STREAMING`          | 0       | Stream LLM responses                      |
| `MAX_REFLECTION_DEPTH`      | 3       | Max self-reflection iterations            |
| `ENABLE_REFLECTION`         | 1       | Enable self-reflection loop               |
| `MAX_TOKENS_PER_CALL`       | 4096    | Token budget per LLM call                 |
| `MAX_CONTEXT_CHARS`         | 50000   | Context window budget                     |
| `MAX_LLM_CALLS_PER_SESSION` | 200     | Session-wide LLM call limit               |
| `MAX_OUTPUT_CHARS`          | 50000   | Max output size per agent                 |
| `DEFAULT_PROJECT_ID`        | default | Memory scoping project ID                 |

### ADS Settings

| Variable                | Default                | Description                                  |
| ----------------------- | ---------------------- | -------------------------------------------- |
| `ENABLE_MODEL_ROUTING`  | 1                      | Smart model routing by complexity            |
| `CLAUDE_MODEL_HEAVY`    | claude-opus-4-20250514 | Model for heavy tasks                        |
| `OPENAI_MODEL_LIGHT`    | gpt-4o-mini            | Model for light tasks                        |
| `ENABLE_DELEGATION`     | 1                      | Agent-to-agent delegation                    |
| `MAX_DELEGATION_DEPTH`  | 3                      | Max delegation chain depth                   |
| `ENABLE_DAG_SCHEDULING` | 1                      | DAG-based parallel scheduling                |
| `HITL_MODE`             | auto                   | `auto` / `confirm_high_risk` / `confirm_all` |
| `ENABLE_INDEXER`        | 1                      | File indexing at startup                     |
| `ENABLE_SNAPSHOTS`      | 1                      | Snapshot rollback for artifacts              |
| `SANDBOX_TIMEOUT`       | 30                     | Sandbox execution timeout (seconds)          |
| `SANDBOX_MAX_OUTPUT`    | 100000                 | Max sandbox output chars                     |

### LLM Providers

| Provider   | Variable              | Default Model               |
| ---------- | --------------------- | --------------------------- |
| Claude     | `LLM_PROVIDER=claude` | `claude-sonnet-4-20250514`  |
| OpenAI     | `LLM_PROVIDER=openai` | `gpt-4o`                    |
| Ollama     | `LLM_PROVIDER=ollama` | `llama3`                    |
| NVIDIA NIM | `LLM_PROVIDER=nvidia` | (configured per deployment) |

---

## Enhanced Guardrails v2

- **Snapshot rollback**: Automatic backup before writes; full rollback on validation failure
- **Anti-pattern detection**: 17 patterns (eval, exec, hardcoded secrets, bare except, SQL injection, etc.)
- **Infinite loop detection**: Hashing of recent outputs; flags identical output repeated 3+ times
- **Pre-change justification**: Risk scoring (0.0–1.0) with syntax/pattern/size validation
- **Post-change validation**: Syntax check, lint, unit test execution

### Human-in-the-Loop (HITL)

Three modes:

| Mode                | Behavior                                   |
| ------------------- | ------------------------------------------ |
| `auto`              | All checkpoints auto-approved (default)    |
| `confirm_high_risk` | Only risk_score ≥ 0.7 prompts for approval |
| `confirm_all`       | Every checkpoint requires human approval   |

### Sandbox Execution

Isolated subprocess execution for Python, Node.js, and shell commands:

- Process isolation (no `eval/exec`)
- Configurable timeout (default 30s)
- stdout/stderr capture (max 100k chars)
- Exit code + elapsed_ms tracking

---

## Quick Start

### 1. Install

```bash
pip install -e .                  # Core install
pip install -e ".[mcp]"          # With MCP server support
pip install -e ".[dev]"          # With dev tools (pytest, ruff)
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env — set your API key and preferred provider
```

### 3. Run

```bash
# Basic run
interro-claw "Build a web application hosted in Azure"

# With streaming
interro-claw --stream "Build a REST API with FastAPI"

# With project scoping
interro-claw --project myapp "Add user authentication"

# Resume a previous session
interro-claw --resume abc123 "Continue building"

# Auto-resume last incomplete session
interro-claw --auto-resume "Continue where we left off"

# Persistent interactive session
interro-claw --matrix-mode

# Pure chat (no agents)
interro-claw --chat

# Run as MCP server
interro-claw --mcp
```

### 4. Inspect Memory

```bash
python memory_cli.py stats
python memory_cli.py recall ArchitectAgent
python memory_cli.py knowledge --topic backend
python memory_cli.py sessions
python memory_cli.py clear-cache
```

---

## CLI Reference

| Flag               | Description                                |
| ------------------ | ------------------------------------------ |
| `"<goal>"`         | Single-shot agent orchestration            |
| `--project <id>`   | Scope to a named project                   |
| `--resume <id>`    | Resume a previous session                  |
| `--auto-resume`    | Auto-resume last incomplete session        |
| `--chat`           | Pure LLM conversation (no agents)          |
| `--matrix-mode`    | Persistent interactive session with agents |
| `--stream`         | Enable token streaming                     |
| `--verbose` / `-v` | Show detailed execution logs + telemetry   |
| `--mcp`            | Run as MCP server (stdio transport)        |
| `--get-session`    | List recent session IDs                    |
| `--create-project` | Create a new project interactively         |
| `--list-projects`  | List all registered projects               |
| `--version`        | Show version                               |
