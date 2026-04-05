"""
Interro-Claw MCP Server — exposes orchestrator capabilities as MCP tools.

Supports stdio transport for VS Code Copilot Agent Mode and Claude Desktop.

Usage:
    interro-claw --mcp
    python -m interro_claw.mcp_server
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy MCP SDK import — graceful degradation if not installed
# ---------------------------------------------------------------------------

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent, Resource

    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False


def _require_mcp() -> None:
    if not _MCP_AVAILABLE:
        print(
            "ERROR: MCP support requires the 'mcp' package.\n"
            "Install it with:  pip install mcp\n"
            "Or:               pip install interro-claw[mcp]",
            file=sys.stderr,
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Tool implementations — thin wrappers around existing interro-claw APIs
# ---------------------------------------------------------------------------

async def _tool_plan(arguments: dict) -> str:
    """Decompose a goal into a structured task plan."""
    from interro_claw.orchestrator import Orchestrator

    goal = arguments.get("goal", "")
    project_id = arguments.get("project_id", "default")
    if not goal:
        return json.dumps({"error": "goal is required"})

    orch = Orchestrator(project_id=project_id)
    plan = await orch.plan_only(goal)
    return json.dumps(plan, indent=2, default=str)


async def _tool_execute(arguments: dict) -> str:
    """Full multi-agent orchestration for a goal."""
    from interro_claw.orchestrator import Orchestrator

    goal = arguments.get("goal", "")
    project_id = arguments.get("project_id", "default")
    if not goal:
        return json.dumps({"error": "goal is required"})

    orch = Orchestrator(
        project_id=project_id,
        enable_streaming=arguments.get("stream", False),
    )
    results = await orch.run(goal)
    report = getattr(orch, "_last_report", None) or ""
    return json.dumps({
        "session_id": orch.session_id,
        "results_count": len(results),
        "report": report,
    }, indent=2, default=str)


async def _tool_chat(arguments: dict) -> str:
    """Direct LLM conversation (no agents)."""
    from interro_claw.llm_client import get_llm_client

    message = arguments.get("message", "")
    system_prompt = arguments.get("system_prompt", "You are a helpful assistant.")
    if not message:
        return json.dumps({"error": "message is required"})

    client = get_llm_client()
    response = await client.chat(system_prompt, message)
    return response


async def _tool_analyze(arguments: dict) -> str:
    """Analyze project structure & dependencies."""
    from interro_claw.project_context import ProjectContext

    project_path = arguments.get("project_path", os.getcwd())
    if not os.path.isdir(project_path):
        return json.dumps({"error": f"Not a directory: {project_path}"})

    ctx = ProjectContext(project_path)
    return json.dumps({
        "languages": dict(ctx.languages),
        "frameworks": ctx.frameworks,
        "dependencies_count": sum(len(v) for v in ctx.dependencies.values()),
        "file_count": sum(ctx.languages.values()),
        "config_files": ctx.config_files,
        "summary": ctx.to_prompt_section()[:2000],
    }, indent=2, default=str)


async def _tool_blast_radius(arguments: dict) -> str:
    """Get blast radius for changed files."""
    from interro_claw.graph_engine.engine import ProjectGraphEngine
    from interro_claw.dep_graph import DependencyGraph

    project_path = arguments.get("project_path", os.getcwd())
    changed_files = arguments.get("changed_files", [])
    if not changed_files:
        return json.dumps({"error": "changed_files list is required"})

    engine = ProjectGraphEngine()
    graph = engine.build(project_path)

    dep = DependencyGraph(project_id="mcp")
    # Populate from graph edges
    for edge in graph.edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        if src and tgt:
            if src not in dep.nodes:
                from interro_claw.dep_graph import DependencyNode, ServiceLayer
                dep.nodes[src] = DependencyNode(
                    path=src, imports=[], imported_by=[], functions=[],
                    classes=[], lines=0, complexity_score=0, layer=ServiceLayer.BUSINESS, exports=[],
                )
            if tgt not in dep.nodes:
                from interro_claw.dep_graph import DependencyNode, ServiceLayer
                dep.nodes[tgt] = DependencyNode(
                    path=tgt, imports=[], imported_by=[], functions=[],
                    classes=[], lines=0, complexity_score=0, layer=ServiceLayer.BUSINESS, exports=[],
                )
            dep.nodes[src].imports.append(tgt)
            dep.nodes[tgt].imported_by.append(src)

    radius = dep.get_blast_radius(changed_files, max_depth=4)
    return json.dumps({
        "changed_files": changed_files,
        "blast_radius": radius,
        "total_affected": len(radius),
    }, indent=2)


async def _tool_memory_recall(arguments: dict) -> str:
    """Search agent memory/knowledge."""
    from interro_claw.memory import get_memory_store

    query = arguments.get("query", "")
    project_id = arguments.get("project_id", "default")
    if not query:
        return json.dumps({"error": "query is required"})

    store = get_memory_store()
    results = store.search_similar(query, top_k=5, project_id=project_id)
    return json.dumps(results, indent=2, default=str)


async def _tool_session_list(arguments: dict) -> str:
    """List recent sessions."""
    from interro_claw.memory import get_memory_store

    project_id = arguments.get("project_id", "default")
    limit = int(arguments.get("limit", 10))

    store = get_memory_store()
    sessions = store.get_recent_sessions(project_id, limit=limit)
    return json.dumps(sessions, indent=2, default=str)


async def _tool_telemetry(arguments: dict) -> str:
    """Get current session telemetry stats."""
    from interro_claw.telemetry import summary
    return json.dumps(summary(), indent=2)


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

_TOOLS = {
    "interro_plan": {
        "description": (
            "[Interro-Claw] Use when the user says 'interro-claw', 'multi-agent', 'plan with agents', "
            "or wants autonomous multi-file code generation. Deploys 9 specialized AI agents "
            "(Planner, Architect, Backend, Frontend, Security, Test, Ops, Refactor, Consolidator) "
            "with DAG-parallel scheduling to decompose a development goal into structured task batches. "
            "Returns a JSON plan with agent assignments, dependencies, and parallel execution groups. "
            "NOT for simple single-file edits — use for complex, multi-step software projects."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "The development goal to decompose into a multi-agent plan"},
                "project_id": {"type": "string", "description": "Project ID for memory scoping (isolates memory per project)", "default": "default"},
            },
            "required": ["goal"],
        },
        "handler": _tool_plan,
    },
    "interro_execute": {
        "description": (
            "[Interro-Claw] Run full autonomous development: 9 specialized AI agents plan, build, test, "
            "secure, and refactor code with blast-radius context pruning, 3-layer memory (STM/WM/LTM), "
            "snapshot rollback, and 4-axis result verification. Use when the user says 'interro-claw', "
            "'build with agents', 'autonomous build', or wants a complete multi-file project generated "
            "end-to-end (e.g., 'build a REST API', 'create a full-stack app', 'scaffold a microservice'). "
            "Outputs files to artifacts/ directory. NOT for single-file edits or quick fixes."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "The development goal to accomplish end-to-end with multi-agent orchestration"},
                "project_id": {"type": "string", "description": "Project ID for memory scoping (isolates memory per project)", "default": "default"},
                "stream": {"type": "boolean", "description": "Enable streaming responses", "default": False},
            },
            "required": ["goal"],
        },
        "handler": _tool_execute,
    },
    "interro_chat": {
        "description": (
            "[Interro-Claw] Send a message to Interro-Claw's configured LLM provider (Claude, OpenAI, "
            "Ollama, or NVIDIA NIM) without agent orchestration. Use when the user explicitly wants "
            "to chat via interro-claw's LLM, compare responses across providers, or use a local Ollama "
            "model. NOT a general chat tool — only invoke when user mentions 'interro-claw chat' or "
            "wants to use a specific LLM provider configured in interro-claw."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "The message to send to Interro-Claw's configured LLM"},
                "system_prompt": {"type": "string", "description": "Optional system prompt override"},
            },
            "required": ["message"],
        },
        "handler": _tool_chat,
    },
    "interro_analyze": {
        "description": (
            "[Interro-Claw] Deep project analysis using AST parsing and dependency graph extraction. "
            "Returns detected languages, frameworks, dependency counts, config files, and a structured "
            "project summary. Use when the user says 'interro-claw analyze', 'analyze with interro-claw', "
            "or wants AST-level dependency analysis beyond simple file listing."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "Absolute path to the project root directory to analyze"},
            },
            "required": ["project_path"],
        },
        "handler": _tool_analyze,
    },
    "interro_blast_radius": {
        "description": (
            "[Interro-Claw] Compute the blast radius of file changes — BFS traversal up to 4 levels deep "
            "through the AST-extracted dependency graph to find every transitively affected file. "
            "Use when the user asks 'what files are affected if I change X?', 'blast radius', "
            "'impact analysis', 'what depends on this file?', or 'dependency impact'. "
            "Returns the complete list of directly and transitively impacted files."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "Absolute path to the project root directory"},
                "changed_files": {
                    "type": "array", "items": {"type": "string"},
                    "description": "List of changed file paths (relative to project root) to compute blast radius for",
                },
            },
            "required": ["project_path", "changed_files"],
        },
        "handler": _tool_blast_radius,
    },
    "interro_memory_recall": {
        "description": (
            "[Interro-Claw] Search Interro-Claw's persistent agent memory and shared knowledge base "
            "using TF-IDF vector similarity. Recalls past agent decisions, learned patterns, coding "
            "conventions, and optimization strategies stored across previous sessions. "
            "Use when the user asks 'what did interro-claw learn?', 'recall memory', "
            "'what patterns were found?', or wants to query interro-claw's knowledge base."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Semantic search query for Interro-Claw's agent memory"},
                "project_id": {"type": "string", "description": "Project ID to scope the memory search", "default": "default"},
            },
            "required": ["query"],
        },
        "handler": _tool_memory_recall,
    },
    "interro_session_list": {
        "description": (
            "[Interro-Claw] List recent Interro-Claw orchestration sessions with session IDs, goals, "
            "project scopes, and completion status. Use when the user asks 'show my interro-claw sessions', "
            "'list sessions', 'what did interro-claw run?', or needs a session ID to resume a previous run."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Filter sessions by project ID", "default": "default"},
                "limit": {"type": "integer", "description": "Maximum number of sessions to return", "default": 10},
            },
        },
        "handler": _tool_session_list,
    },
    "interro_telemetry": {
        "description": (
            "[Interro-Claw] Get Interro-Claw's token reduction telemetry: exact cache hits, fuzzy "
            "fingerprint cache hits, actual LLM calls made, files pruned by blast radius, files "
            "skipped by incremental SHA256 hashing, context chars saved, estimated tokens saved, "
            "and estimated cost savings. Use when the user asks 'how much did interro-claw save?', "
            "'interro-claw telemetry', 'token usage', or 'cache hit rate'."
        ),
        "schema": {"type": "object", "properties": {}},
        "handler": _tool_telemetry,
    },
}


# ---------------------------------------------------------------------------
# MCP Server setup
# ---------------------------------------------------------------------------

def _create_server() -> "Server":
    """Build and configure the MCP server with all tools and resources."""
    _require_mcp()

    server = Server("interro-claw")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        tools = []
        for name, spec in _TOOLS.items():
            tools.append(Tool(
                name=name,
                description=spec["description"],
                inputSchema=spec["schema"],
            ))
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        spec = _TOOLS.get(name)
        if not spec:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

        try:
            result = await spec["handler"](arguments)
            return [TextContent(type="text", text=result)]
        except Exception as exc:
            logger.exception("MCP tool %s failed", name)
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]

    @server.list_resources()
    async def list_resources() -> list[Resource]:
        return [
            Resource(uri="interro://projects", name="Registered Projects", description="List of all registered projects"),
            Resource(uri="interro://telemetry", name="Session Telemetry", description="Current session token reduction stats"),
        ]

    @server.read_resource()
    async def read_resource(uri: str) -> str:
        if str(uri) == "interro://projects":
            from interro_claw.memory import get_memory_store
            store = get_memory_store()
            projects = store.list_projects()
            return json.dumps([p.__dict__ if hasattr(p, "__dict__") else str(p) for p in projects], indent=2, default=str)

        if str(uri) == "interro://telemetry":
            from interro_claw.telemetry import summary
            return json.dumps(summary(), indent=2)

        return json.dumps({"error": f"Unknown resource: {uri}"})

    return server


def run_mcp_server() -> None:
    """Entry point — run MCP server on stdio transport."""
    _require_mcp()

    server = _create_server()

    async def _run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(_run())


# Allow direct execution: python -m interro_claw.mcp_server
if __name__ == "__main__":
    run_mcp_server()
