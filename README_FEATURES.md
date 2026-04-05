# Interro-Claw — Features, USP & Integration Guide

> This document covers all features in detail, the competitive comparison, telemetry, and MCP integration.
> For architecture, configuration, and technical internals, see [README_ARCHITECTURE.md](README_ARCHITECTURE.md).

---

## Feature Guide — What Every Feature Does For You

> Quick-reference for users evaluating Interro-Claw. Each feature is explained in plain language so you know exactly what you're getting.

### 1. Multi-LLM Provider Support (Claude / OpenAI / Ollama / NVIDIA NIM)

Switch between cloud providers (Anthropic Claude, OpenAI GPT-4o) or run **fully local** with Ollama — zero cloud costs. NVIDIA NIM support lets enterprises use on-premise GPU clusters. You're never locked into a single vendor; change one env variable and your entire agent fleet switches models.

### 2. 9 Specialized Agents with DAG Scheduling

Instead of one generic AI, Interro-Claw deploys **purpose-built agents** — Planner, Architect, Backend, Frontend, Ops, Test, Security, Refactor, and Consolidator — each with domain-specific prompts and skill injections. A DAG scheduler (Kahn's algorithm) runs independent agents **in parallel** while respecting dependencies, so a 6-task plan finishes in 3 batches instead of 6 sequential calls.

### 3. 3-Layer Memory Hierarchy (Short-Term / Working / Long-Term)

**Short-Term Memory** holds per-task scratch data and is cleared when the task finishes. **Working Memory** persists per-project across sessions (file context, reasoning chains, summaries). **Long-Term Memory** stores global patterns, coding style preferences, and optimization strategies across all projects. This mirrors how human experts recall past decisions.

### 4. Blast-Radius Context Pruning

When files change, a BFS traversal through the dependency graph identifies every **transitively affected file** up to 4 levels deep. Only those files are injected into agent context — everything outside the blast radius is pruned. This can cut context tokens by 50–80% on large codebases compared to "send everything" approaches.

### 5. Incremental Graph Hashing (SHA256 Per-File)

The project graph engine computes a SHA256 content hash for every source file. On subsequent builds, only files whose hash changed are flagged — even if `mtime` changed (e.g., after a `git checkout` or file sync). This eliminates false rebuilds and gives downstream systems (blast radius, file selector) a precise `changed_files` list.

### 6. 2-Level LLM Response Cache (Exact + Fuzzy Fingerprint)

**Level 1** caches by exact system+user prompt hash — instant hit for identical requests. **Level 2** normalizes the user message (strips filler words, lowercases, collapses whitespace) into a 24-char fingerprint — catches rephrased questions like "Build a REST API" vs "Create a RESTful API". Combined, these levels can achieve 40–70% cache hit rates in iterative workflows.

### 7. Smart Model Routing (Heavy / Medium / Light)

Complex tasks (architecture, deep debugging) automatically route to powerful models (Claude Opus, GPT-4o). Simple tasks (test generation, formatting) route to cheaper/faster models (GPT-4o-mini, Ollama). This cuts LLM costs by 30–50% without sacrificing quality where it matters.

### 8. AST-Aware Code Chunking

When files are too large for a single context window, Interro-Claw splits them at **semantic boundaries** — function definitions, class declarations, markdown sections — never mid-function. Each chunk preserves its import block and class header so the agent always has complete context.

### 9. Agent Delegation Protocol (Inter-Agent Collaboration)

Any agent can request help from another agent mid-task. A `BackendAgent` building an API can delegate a "review this endpoint for SQL injection" sub-task to `SecurityAgent` and receive structured results — all within the same execution. Supports both blocking (wait for result) and fire-and-forget modes.

### 10. Human-in-the-Loop with Risk Scoring

Every change gets a risk score (0.0–1.0). In `confirm_high_risk` mode, only dangerous operations (file deletions, infrastructure changes, security-sensitive code) prompt you for approval — while safe operations auto-proceed. Includes diff preview so you see exactly what will change before approving.

### 11. Snapshot Rollback on Guardrail Failure

Before any file write, the guardrails system snapshots the affected files. If post-write validation fails (bad syntax, anti-pattern detected, test failure), the system **automatically rolls back** to the pre-write state. No manual `git checkout` needed.

### 12. Multi-Dimension Result Verification (4-Axis Scoring)

Every agent output is scored on **Correctness** (does it solve the task?), **Performance** (efficient algorithms? no N+1 queries?), **Safety** (OWASP compliance? secrets exposed?), and **Consistency** (follows project patterns?). All four must pass — a single weak dimension fails the entire result.

### 13. Vector Search Memory (No External ML Dependencies)

Semantic similarity search using lightweight TF-IDF embeddings stored in SQLite. Find relevant past decisions even with different wording — no OpenAI embeddings API, no Pinecone, no external vector DB. Everything runs locally and deterministically.

### 14. Self-Reflection Loop with Depth Control

After generating output, each agent critiques its own work and re-generates if quality is below threshold. Configurable depth (default 3) prevents infinite loops while allowing iterative improvement. This catches obvious mistakes before human review.

### 15. Reusable Skills System (.md Knowledge Injection)

Domain expertise is packaged as Markdown files in `skills/` with YAML frontmatter (`applies_to: BackendAgent, TestAgent`). Skills are auto-injected into matching agents at runtime. Add a new `kubernetes-patterns.md` and every relevant agent instantly knows K8s best practices — no code changes.

### 16. Project Registry with Multi-Project Isolation

Create named projects (`--create-project`) that isolate memory, sessions, and context. Switch between projects and each maintains its own history, learned patterns, and file context. Perfect for consultants or teams working across multiple codebases.

### 17. Session Resume & Auto-Resume

Every session is persisted with a unique ID. Use `--resume <id>` to continue exactly where you left off, or `--auto-resume` to automatically pick up the last incomplete session. Multi-step goals survive terminal crashes and lunch breaks.

### 18. Matrix Mode (Persistent Interactive Session)

An interactive shell with full agent orchestration, LLM-based intent classification (chat vs. clarify vs. goal), and conversation history. Type goals and get multi-agent execution; ask questions and get direct answers — the system decides the right mode automatically.

### 19. CLI-First (No Browser / IDE Dependency)

Runs entirely from your terminal. No Electron app, no browser tab, no VS Code extension required. Pipe it, script it, run it in CI/CD, SSH into a server and use it — true Unix philosophy.

### 20. Local-First (Ollama Support, Zero Cloud Costs)

Point at a local Ollama instance and everything runs on your hardware. No API keys, no usage billing, no data leaving your network. Ideal for air-gapped environments, sensitive codebases, or cost-conscious developers.

### 21. Context Budget Enforcement

A hard `MAX_CONTEXT_CHARS` limit prevents context overflow and LLM hallucination from too-long prompts. Files are selectively included, truncated, and prioritized by relevance — agents always get the most useful context first within budget.

### 22. Streaming with Post-Stream Caching

Get real-time token-by-token output while the response is simultaneously assembled and cached. The next identical request returns instantly from cache — you get the UX benefit of streaming AND the cost benefit of caching.

### 23. Sandboxed Code Execution

Agents execute code in isolated subprocesses (Python, Node.js, Shell) with configurable timeouts and output capture. No `eval()` or `exec()` — true process isolation. Prevents runaway scripts from affecting your system.

### 24. Enhanced Guardrails (17 Anti-Pattern Detectors)

Detects `eval/exec`, hardcoded secrets, `shell=True`, pickle deserialization, bare `except: pass`, SQL injection patterns, and 11 more anti-patterns in generated code. Catches dangerous code before it reaches your filesystem.

### 25. Token Reduction Telemetry

Built-in telemetry tracks exact cache hits, fingerprint cache hits, actual LLM calls, files pruned by blast radius, files skipped by incremental hashing, and context chars saved. Prints a summary at session end so you see exactly how much you saved.

### 26. MCP Server Integration

Expose all Interro-Claw capabilities as an MCP (Model Context Protocol) server. VS Code Copilot, Claude Desktop, or any MCP client can use `interro_plan`, `interro_execute`, `interro_analyze`, `interro_blast_radius`, and more as tools — turning Interro-Claw into a backend for any AI assistant.

---

## Competitive Advantage — USP Comparison

How Interro-Claw compares against market alternatives across key dimensions:

| #   | Feature                                              |    Interro-Claw     |    Devin     | GitHub Copilot Workspace | Cursor / Windsurf | AutoGen / CrewAI | Aider / SWE-Agent |   MetaGPT    |
| --- | ---------------------------------------------------- | :-----------------: | :----------: | :----------------------: | :---------------: | :--------------: | :---------------: | :----------: |
| 1   | **Multi-LLM Provider** (Claude/OpenAI/Ollama/NVIDIA) |   **4 providers**   |      1       |            1             |        1-2        |       2-3        |        1-2        |      1       |
| 2   | **Specialized Agent Fleet** (9 domain experts)       |    **9 agents**     |  1 general   |        1 general         |     1 general     |  Generic roles   |      1 agent      |  5 generic   |
| 3   | **DAG-Based Parallel Scheduling**                    |       **Yes**       |  Sequential  |        Sequential        |        N/A        |    Sequential    |    Sequential     |  Sequential  |
| 4   | **3-Layer Memory** (STM/WM/LTM)                      |    **3 layers**     | Flat history |           None           |   Session only    |   Shared dict    |     Git-based     | Shared files |
| 5   | **Blast-Radius Context Pruning**                     |   **BFS 4-depth**   |      No      |            No            |        No         |        No        |        No         |      No      |
| 6   | **Incremental Graph Hashing** (SHA256)               |    **Per-file**     |      No      |            No            |        No         |        No        |        No         |      No      |
| 7   | **2-Level Cache** (exact + fingerprint)              |       **Yes**       |      No      |            No            |        No         |        No        |        No         |      No      |
| 8   | **Smart Model Routing** (complexity-based)           |     **3 tiers**     |    Fixed     |          Fixed           |       Fixed       |      Manual      |      Manual       |    Fixed     |
| 9   | **AST-Aware Code Chunking**                          |       **Yes**       |  Line-based  |        Line-based        |    Line-based     |   No chunking    |    Line-based     |      No      |
| 10  | **Agent Delegation** (blocking + async)              |       **Yes**       |     N/A      |           N/A            |        N/A        |      Basic       |        No         |   Limited    |
| 11  | **Human-in-the-Loop** (risk scoring)                 |     **3 modes**     |    Manual    |        PR review         |      Manual       |        No        |        No         |      No      |
| 12  | **Snapshot Rollback** (auto-revert)                  |       **Yes**       |      No      |        Git-based         |       Undo        |        No        |     Git-based     |      No      |
| 13  | **4-Axis Result Verification**                       |       **Yes**       |      No      |            No            |        No         |        No        |        No         |      No      |
| 14  | **Vector Memory** (no external deps)                 |    **Built-in**     |      No      |            No            |        No         |   Needs Chroma   |        No         |      No      |
| 15  | **Self-Reflection Loop**                             |  **Yes (depth 3)**  |      No      |            No            |        No         |     Limited      |        No         |   Limited    |
| 16  | **Skills System** (.md injection)                    |    **11 skills**    |  Hardcoded   |        Hardcoded         |     Hardcoded     |    Hardcoded     |      Config       |   Prompts    |
| 17  | **Multi-Project Isolation**                          |       **Yes**       |   Per repo   |         Per repo         |     Per repo      |        No        |     Per repo      |      No      |
| 18  | **Session Resume / Auto-Resume**                     |       **Yes**       |      No      |            No            |        No         |        No        |        No         |      No      |
| 19  | **Matrix Mode** (interactive + agents)               |       **Yes**       |  Chat only   |        Plan only         |     Chat only     |   Script only    |     Chat only     |    Script    |
| 20  | **CLI-First** (no IDE dependency)                    |       **Yes**       |   Browser    |         VS Code          |     IDE only      |      Python      |        CLI        |     CLI      |
| 21  | **Local-First** (Ollama, zero cloud)                 |       **Yes**       |  Cloud only  |        Cloud only        |    Cloud only     |     Possible     |     Possible      |    Cloud     |
| 22  | **Context Budget Enforcement**                       |       **Yes**       |      No      |         Unknown          |      Partial      |        No        |        No         |      No      |
| 23  | **Streaming + Caching Combined**                     |       **Yes**       |      No      |           N/A            |    Stream only    |        No        |        No         |      No      |
| 24  | **Sandboxed Execution**                              |       **Yes**       |    Docker    |        Codespace         |        No         |     Optional     |      Docker       |      No      |
| 25  | **17 Anti-Pattern Guardrails**                       |       **Yes**       |      No      |            No            |        No         |        No        |        No         |      No      |
| 26  | **Token Reduction Telemetry**                        |       **Yes**       |      No      |            No            |        No         |        No        |        No         |      No      |
| 27  | **MCP Server** (tool provider)                       |       **Yes**       |      No      |            No            |        No         |        No        |        No         |      No      |
| 28  | **Open Source & Model-Agnostic**                     |       **MIT**       |    Closed    |          Closed          |      Closed       |       MIT        |      Apache       |     MIT      |
| 29  | **Cost**                                             | **Free + your LLM** |   $500/mo    |         Included         |     $20-40/mo     |       Free       |       Free        |     Free     |
| 30  | **Pricing Lock-in**                                  |      **None**       |    Vendor    |          Vendor          |      Vendor       |       None       |       None        |     None     |

### What Only Interro-Claw Has (Market Firsts)

These capabilities are **not available in any competing product** as of April 2026:

1. **Blast-Radius Context Pruning** — BFS dependency traversal to inject only impacted files into agent context (50–80% token reduction on large codebases)
2. **2-Level LLM Cache with Fuzzy Fingerprinting** — Catches rephrased identical questions that exact-match caches miss (40–70% hit rate in iterative workflows)
3. **4-Axis Result Verification** — Every output scored on correctness, performance, safety, AND consistency — all must pass
4. **Token Reduction Telemetry** — Built-in metrics showing exactly how many LLM calls, tokens, and dollars you saved per session
5. **9-Agent DAG-Parallel Fleet** — Purpose-built agents running in topologically-sorted parallel batches (not generic sequential chains)
6. **3-Layer Memory Hierarchy** — STM → WM → LTM with per-project isolation and cross-project learning
7. **Snapshot Rollback Guardrails** — Automatic pre/post validation with file-level rollback on failure

---

## Token Reduction Telemetry

Interro-Claw tracks how much the code-review-graph integration saves you **in real-time**. At the end of every session, you see:

```
+==========================================================+
|                 Token Reduction Summary                   |
+==========================================================+
| LLM Calls Saved (exact cache):                        12 |
| LLM Calls Saved (fuzzy fingerprint):                   5 |
| Actual LLM Calls Made:                                 8 |
| Cache Hit Rate:                                    68.0% |
+----------------------------------------------------------+
| Files Pruned by Blast Radius:                         23 |
| Files Skipped (unchanged hash):                       47 |
| Context Chars Saved:                            ~127,000 |
+----------------------------------------------------------+
| Est. Tokens Saved:                               ~51,000 |
| Est. Cost Saved:                                ~$0.1530 |
+==========================================================+
```

Savings compound over sessions as caches warm up. Visible in `--verbose` mode and always-on in matrix mode.

---

## What is MCP? (Model Context Protocol)

> **If you're new to MCP, read this section first.** It explains what MCP is, why it matters, and how Interro-Claw uses it.

### The Problem MCP Solves

Every AI assistant (VS Code Copilot, Claude Desktop, ChatGPT, etc.) needs access to external tools — your codebase, your databases, your APIs, your custom analysis tools. Before MCP, each assistant needed **custom integrations** for each tool. VS Code had its own extension API, Claude Desktop had its own plugin system, and nothing was interoperable.

**MCP (Model Context Protocol)** is an **open standard** (created by Anthropic, adopted by Microsoft/VS Code, JetBrains, and others) that standardizes how AI assistants communicate with tool providers. Think of it like **USB for AI tools** — one universal connector instead of proprietary cables for every device.

### How MCP Works

```
┌─ MCP Clients ─────────────┐       ┌─ MCP Servers (Tools) ────────────┐
│                            │       │                                   │
│  VS Code Copilot           │       │  interro-claw --mcp              │
│  Claude Desktop            │ ◄───► │  GitHub MCP Server               │
│  JetBrains AI              │ stdio │  Database MCP Server             │
│  Any MCP-compatible app    │  or   │  Filesystem MCP Server           │
│                            │ HTTP  │  Any custom MCP server           │
└────────────────────────────┘       └───────────────────────────────────┘
```

**The conversation flow:**

1. **Client** (e.g., VS Code Copilot) starts the MCP server as a subprocess
2. **Server** (e.g., Interro-Claw) responds with a list of available **tools** and **resources**
3. **Client's AI model** sees these tools and decides when to call them
4. When the AI needs to use a tool, it sends a **JSON-RPC call** to the server
5. **Server** executes the tool and returns results
6. **Client** incorporates the results into its response to you

**Key concepts:**

- **Tools** — Functions the AI can call (e.g., `interro_plan`, `interro_blast_radius`)
- **Resources** — Read-only data the AI can access (e.g., `interro://projects`)
- **Transport** — How client and server communicate (`stdio` for local, `HTTP+SSE` for remote)

### Why This Matters for Interro-Claw

Without MCP, Interro-Claw is a standalone CLI tool. **With MCP**, Interro-Claw becomes a **backend brain** that any AI assistant can use:

| Without MCP                                     | With MCP                                                     |
| ----------------------------------------------- | ------------------------------------------------------------ |
| Run `interro-claw` in a separate terminal       | VS Code Copilot calls Interro-Claw tools automatically       |
| Copy-paste results between tools                | Results flow directly into the AI's context                  |
| Only Interro-Claw's agents can use its analysis | Any MCP client gets blast-radius, memory, telemetry          |
| One workflow at a time                          | Multiple AI clients can share the same Interro-Claw instance |

### How Interro-Claw's MCP Server Integrates with VS Code Copilot

**Step-by-step flow:**

```
You type in VS Code Copilot:
  "Plan a REST API with authentication for my project"
         │
         ▼
Copilot's AI sees the interro-claw tools are available
         │
         ▼
AI decides to call: interro_plan(goal="REST API with auth")
         │
         ▼
VS Code sends JSON-RPC call to interro-claw --mcp subprocess
         │
         ▼
Interro-Claw's PlannerAgent decomposes the goal:
  → ArchitectAgent: design API structure
  → BackendAgent: implement endpoints
  → SecurityAgent: add auth middleware
  → TestAgent: write integration tests
         │
         ▼
Structured plan returned to Copilot
         │
         ▼
Copilot presents the plan to you in the chat window
```

**What each MCP tool gives Copilot:**

| When you ask Copilot...                 | Copilot calls...        | What happens behind the scenes                                 |
| --------------------------------------- | ----------------------- | -------------------------------------------------------------- |
| "Plan a REST API with auth"             | `interro_plan`          | PlannerAgent decomposes into task list with agent assignments  |
| "Build this full project"               | `interro_execute`       | Full 9-agent DAG orchestration (plan → build → test → verify)  |
| "What would break if I change auth.py?" | `interro_blast_radius`  | BFS dependency traversal returns all affected files with depth |
| "Analyze this project"                  | `interro_analyze`       | Scans languages, frameworks, dependencies, generates summary   |
| "What did I work on last week?"         | `interro_memory_recall` | Semantic search through agent memory and shared knowledge      |
| "Show my sessions"                      | `interro_session_list`  | Lists recent sessions with IDs, goals, timestamps              |
| "How much did I save on LLM costs?"     | `interro_telemetry`     | Returns cache hits, tokens saved, cost saved                   |
| "Help me debug this error"              | `interro_chat`          | Direct LLM conversation without agent overhead                 |

---

## MCP Server Integration — Setup Guide

### Available MCP Tools (8 tools)

| Tool                    | Description                                       | Required Input                  |
| ----------------------- | ------------------------------------------------- | ------------------------------- |
| `interro_plan`          | Decompose goal into multi-agent task plan         | `goal`                          |
| `interro_execute`       | Full orchestration (plan → build → test → verify) | `goal`                          |
| `interro_chat`          | Direct LLM conversation (no agents)               | `message`                       |
| `interro_analyze`       | Analyze project structure & dependencies          | `project_path`                  |
| `interro_blast_radius`  | BFS blast radius for changed files                | `project_path`, `changed_files` |
| `interro_memory_recall` | Semantic search in agent memory                   | `query`                         |
| `interro_session_list`  | List recent orchestration sessions                | (optional: `project_id`)        |
| `interro_telemetry`     | Current session telemetry stats                   | —                               |

### MCP Resources (2 resources)

| Resource URI          | Description                     |
| --------------------- | ------------------------------- |
| `interro://projects`  | List of all registered projects |
| `interro://telemetry` | Current session telemetry data  |

### Setup: VS Code Copilot

**Prerequisites:** Install the `mcp` Python package:

```bash
pip install interro-claw[mcp]
# or: pip install mcp
```

**Step 1:** Create `.vscode/mcp.json` in your project root:

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

**Step 2:** Open VS Code Copilot chat. You'll see Interro-Claw's tools are available.

**Step 3:** Use naturally:

- _"Plan a REST API with auth"_ → Copilot calls `interro_plan`
- _"What's the blast radius of changing auth.py?"_ → Copilot calls `interro_blast_radius`
- _"Show my recent sessions"_ → Copilot calls `interro_session_list`

### Setup: Claude Desktop

Add to your `claude_desktop_config.json` (typically at `%APPDATA%\Claude\claude_desktop_config.json` on Windows or `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

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

Restart Claude Desktop. The Interro-Claw tools will appear in Claude's tool list.

### Setup: Standalone (Any MCP Client)

```bash
# Run the MCP server on stdio
interro-claw --mcp

# Or directly
python -m interro_claw.mcp_server
```

Any MCP client can connect via stdio transport.

### MCP Architecture

```
┌─────────────────────────┐     stdio       ┌──────────────────────────┐
│  VS Code Copilot /      │ ◄─────────────► │  interro-claw --mcp      │
│  Claude Desktop /       │   JSON-RPC       │  (MCP Server)            │
│  Any MCP Client         │                  │                          │
└─────────────────────────┘                  │  ┌─ PlannerAgent         │
                                             │  ├─ 8 more Agents        │
                                             │  ├─ Memory Store (SQLite)│
                                             │  ├─ Blast Radius (BFS)   │
                                             │  ├─ Telemetry Tracker    │
                                             │  ├─ Graph Engine (AST)   │
                                             │  └─ LLM Client (4 provs)│
                                             └──────────────────────────┘
```

### What MCP is NOT

- **Not a chat protocol** — MCP provides tools, not conversation. The AI model (GPT-4o, Claude, etc.) still does the thinking.
- **Not another API** — You don't call MCP with curl. It's designed for AI-to-tool communication.
- **Not cloud-required** — MCP servers run locally as subprocesses. No hosted service needed.
- **Not proprietary** — Open standard. Any tool can be an MCP server, any AI can be an MCP client.
