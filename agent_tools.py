"""
Agent Tools Framework

Provides a registry of tools that agents can invoke during execution:
- Shell command execution (sandboxed)
- HTTP API calls
- File read/write operations
- Sub-agent delegation
- Code analysis (AST parsing)
- Profiling invocation

Each tool has safety checks via the guardrails layer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    tool: str
    success: bool
    output: Any
    error: str = ""


@dataclass
class ToolDefinition:
    name: str
    description: str
    handler: Callable[..., Coroutine[Any, Any, ToolResult]]
    parameters: dict[str, str] = field(default_factory=dict)  # param_name -> description


class ToolRegistry:
    """
    Central registry of tools available to agents.
    Tools are async callables that return ToolResult.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._register_builtins()

    def register(self, defn: ToolDefinition) -> None:
        self._tools[defn.name] = defn
        logger.info("Registered tool: %s", defn.name)

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    @property
    def all_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def describe_tools(self) -> str:
        """Return a prompt-friendly description of all available tools."""
        parts = ["## Available Tools\n"]
        for t in self._tools.values():
            params = ", ".join(f"{k}: {v}" for k, v in t.parameters.items())
            parts.append(f"- **{t.name}**({params}): {t.description}")
        return "\n".join(parts)

    async def invoke(self, tool_name: str, **kwargs: Any) -> ToolResult:
        """Invoke a tool by name with keyword arguments."""
        defn = self._tools.get(tool_name)
        if defn is None:
            return ToolResult(tool=tool_name, success=False, output=None, error=f"Unknown tool: {tool_name}")
        try:
            return await defn.handler(**kwargs)
        except Exception as exc:
            logger.error("Tool %s failed: %s", tool_name, exc)
            return ToolResult(tool=tool_name, success=False, output=None, error=str(exc))

    # -- built-in tools -----------------------------------------------------

    def _register_builtins(self) -> None:
        self.register(ToolDefinition(
            name="read_file",
            description="Read a file from the workspace",
            handler=_tool_read_file,
            parameters={"path": "Relative or absolute file path"},
        ))
        self.register(ToolDefinition(
            name="write_file",
            description="Write content to a file",
            handler=_tool_write_file,
            parameters={"path": "File path", "content": "File content"},
        ))
        self.register(ToolDefinition(
            name="list_dir",
            description="List directory contents",
            handler=_tool_list_dir,
            parameters={"path": "Directory path"},
        ))
        self.register(ToolDefinition(
            name="run_shell",
            description="Execute a shell command (sandboxed, max 60s timeout)",
            handler=_tool_run_shell,
            parameters={"command": "Shell command string"},
        ))
        self.register(ToolDefinition(
            name="http_get",
            description="Make an HTTP GET request",
            handler=_tool_http_get,
            parameters={"url": "URL to fetch"},
        ))
        self.register(ToolDefinition(
            name="search_files",
            description="Search for files matching a pattern",
            handler=_tool_search_files,
            parameters={"root": "Root directory", "pattern": "Glob pattern"},
        ))
        self.register(ToolDefinition(
            name="analyze_python",
            description="Analyze a Python file (functions, classes, imports)",
            handler=_tool_analyze_python,
            parameters={"path": "Path to .py file"},
        ))


# -- Built-in tool implementations -----------------------------------------

async def _tool_read_file(path: str) -> ToolResult:
    import interro_claw.config as _cfg
    from interro_claw.guardrails import get_guardrails
    gr = get_guardrails()
    if gr.is_path_protected(path):
        return ToolResult(tool="read_file", success=False, output=None, error=f"Protected: {path}")
    # Restrict reads to workspace-related paths
    abs_path = os.path.abspath(path)
    allowed_roots = [
        os.path.abspath(_cfg.USER_APP_DIR),
        os.path.abspath(os.getcwd()),
    ]
    if not any(abs_path.startswith(root) for root in allowed_roots):
        return ToolResult(
            tool="read_file", success=False, output=None,
            error=f"File reads restricted to workspace. Rejected: {abs_path}",
        )
    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        return ToolResult(tool="read_file", success=True, output=content[:20000])
    except Exception as exc:
        return ToolResult(tool="read_file", success=False, output=None, error=str(exc))


async def _tool_write_file(path: str, content: str) -> ToolResult:
    import interro_claw.config as _cfg
    from interro_claw.guardrails import get_guardrails
    gr = get_guardrails()
    # Resolve to absolute and enforce that writes land inside USER_APP_DIR
    abs_path = os.path.abspath(path)
    allowed_root = os.path.abspath(_cfg.USER_APP_DIR)
    if not abs_path.startswith(allowed_root + os.sep) and abs_path != allowed_root:
        return ToolResult(
            tool="write_file", success=False, output=None,
            error=f"Writes restricted to {allowed_root}. Rejected: {abs_path}",
        )
    content = gr.validate_output("tool", abs_path, content)
    try:
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        return ToolResult(tool="write_file", success=True, output=f"Wrote {len(content)} chars to {abs_path}")
    except Exception as exc:
        return ToolResult(tool="write_file", success=False, output=None, error=str(exc))


async def _tool_list_dir(path: str) -> ToolResult:
    import interro_claw.config as _cfg
    # Restrict directory listing to workspace-related paths
    abs_path = os.path.abspath(path)
    allowed_roots = [
        os.path.abspath(_cfg.USER_APP_DIR),
        os.path.abspath(os.getcwd()),
    ]
    if not any(abs_path.startswith(root) for root in allowed_roots):
        return ToolResult(
            tool="list_dir", success=False, output=None,
            error=f"Directory listing restricted to workspace. Rejected: {abs_path}",
        )
    try:
        entries = os.listdir(abs_path)
        return ToolResult(tool="list_dir", success=True, output=entries)
    except Exception as exc:
        return ToolResult(tool="list_dir", success=False, output=None, error=str(exc))


# Shell commands the agents are allowed to run (prefix allowlist)
_SHELL_ALLOWLIST = (
    "python", "pip", "npm", "node", "npx", "pytest", "black", "flake8",
    "mypy", "ruff", "eslint", "tsc", "go", "cargo", "dotnet", "az",
    "ls", "dir", "cat", "type", "echo", "mkdir", "cp", "copy",
    "git status", "git diff", "git log", "git branch",
    "tree", "find", "grep", "head", "tail", "wc",
)


async def _tool_run_shell(command: str) -> ToolResult:
    import interro_claw.config as _cfg
    from interro_claw.guardrails import get_guardrails
    import shlex
    gr = get_guardrails()
    gr.check_destructive(command)

    # Allowlist check: command must start with an approved prefix
    cmd_lower = command.strip().lower()
    if not any(cmd_lower.startswith(prefix) for prefix in _SHELL_ALLOWLIST):
        return ToolResult(
            tool="run_shell", success=False, output=None,
            error=f"Command not in allowlist. Allowed prefixes: {', '.join(_SHELL_ALLOWLIST[:10])}...",
        )

    # Run inside USER_APP_DIR so output stays isolated
    cwd = os.path.abspath(_cfg.USER_APP_DIR)
    os.makedirs(cwd, exist_ok=True)
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=cwd,
        )
        return ToolResult(
            tool="run_shell",
            success=result.returncode == 0,
            output=result.stdout[:10000],
            error=result.stderr[:5000] if result.returncode != 0 else "",
        )
    except subprocess.TimeoutExpired:
        return ToolResult(tool="run_shell", success=False, output=None, error="Timeout (60s)")
    except Exception as exc:
        return ToolResult(tool="run_shell", success=False, output=None, error=str(exc))


# Blocked URL patterns to prevent SSRF
_BLOCKED_HOSTS = (
    "localhost", "127.0.0.1", "0.0.0.0", "[::1]",
    "169.254.169.254",  # cloud metadata
    "metadata.google.internal",
    "10.", "172.16.", "172.17.", "172.18.", "172.19.",
    "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
    "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
    "172.30.", "172.31.", "192.168.",
)


async def _tool_http_get(url: str) -> ToolResult:
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        # SSRF protection: block requests to internal/metadata endpoints
        if any(host.startswith(b) or host == b for b in _BLOCKED_HOSTS):
            return ToolResult(
                tool="http_get", success=False, output=None,
                error=f"Blocked: requests to internal/private addresses are not allowed ({host})",
            )
        if parsed.scheme not in ("http", "https"):
            return ToolResult(
                tool="http_get", success=False, output=None,
                error=f"Only http/https URLs are allowed, got: {parsed.scheme}",
            )
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            return ToolResult(
                tool="http_get",
                success=resp.status_code < 400,
                output=resp.text[:10000],
                error="" if resp.status_code < 400 else f"HTTP {resp.status_code}",
            )
    except Exception as exc:
        return ToolResult(tool="http_get", success=False, output=None, error=str(exc))


async def _tool_search_files(root: str, pattern: str) -> ToolResult:
    import glob
    try:
        matches = glob.glob(os.path.join(root, pattern), recursive=True)
        rel = [os.path.relpath(m, root).replace("\\", "/") for m in matches[:100]]
        return ToolResult(tool="search_files", success=True, output=rel)
    except Exception as exc:
        return ToolResult(tool="search_files", success=False, output=None, error=str(exc))


async def _tool_analyze_python(path: str) -> ToolResult:
    import ast
    try:
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=path)
        analysis = {
            "functions": [],
            "classes": [],
            "imports": [],
            "lines": source.count("\n") + 1,
        }
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                analysis["functions"].append(node.name)
            elif isinstance(node, ast.ClassDef):
                analysis["classes"].append(node.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    analysis["imports"].append(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                analysis["imports"].append(node.module)
        return ToolResult(tool="analyze_python", success=True, output=analysis)
    except Exception as exc:
        return ToolResult(tool="analyze_python", success=False, output=None, error=str(exc))


# -- Singleton ---------------------------------------------------------------

_instance: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    global _instance
    if _instance is None:
        _instance = ToolRegistry()
    return _instance
