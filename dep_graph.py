"""
Project Graph Engine

A queryable knowledge graph of the entire codebase, covering:
- Module/file import relationships (file → file edges)
- Service layer detection (presentation, business logic, data access, infra)
- API flow mapping (route → handler → service → repo/db)
- Component connections (who calls whom, event flows)
- Code pattern detection (repeated patterns)
- Bottleneck identification (high fan-in nodes)
- Mutation tracking (frequently changed files)

Agents **query** this graph instead of scanning whole file trees.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ServiceLayer(str, Enum):
    PRESENTATION = "presentation"      # routes, views, controllers, pages
    BUSINESS = "business"              # services, use-cases, managers
    DATA = "data"                      # repos, models, DAOs, ORM
    INFRASTRUCTURE = "infrastructure"  # config, utils, middleware, adapters
    TEST = "test"                      # test files
    UNKNOWN = "unknown"


@dataclass
class DependencyNode:
    """A file/module in the dependency graph."""
    path: str
    imports: list[str] = field(default_factory=list)
    imported_by: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    lines: int = 0
    complexity_score: float = 0.0
    layer: ServiceLayer = ServiceLayer.UNKNOWN
    exports: list[str] = field(default_factory=list)  # publicly exposed names


@dataclass
class APIRoute:
    """An HTTP or event-based route in the project."""
    method: str       # GET, POST, etc. or "EVENT"
    path: str         # /api/users, etc.
    handler: str      # function name
    file: str         # file where defined
    calls: list[str] = field(default_factory=list)  # downstream service calls


@dataclass
class ComponentConnection:
    """A caller → callee relationship between named components."""
    caller_file: str
    caller_name: str
    callee_file: str
    callee_name: str
    kind: str = "call"  # "call", "import", "event", "inherit"


@dataclass
class DependencyGraph:
    """Full project dependency analysis — queryable by agents."""
    project_id: str
    nodes: dict[str, DependencyNode] = field(default_factory=dict)
    edges: list[tuple[str, str]] = field(default_factory=list)  # (from, to)
    hot_files: list[str] = field(default_factory=list)  # highest fan-in
    bottlenecks: list[str] = field(default_factory=list)
    patterns: dict[str, int] = field(default_factory=dict)  # pattern -> count
    api_routes: list[APIRoute] = field(default_factory=list)
    connections: list[ComponentConnection] = field(default_factory=list)

    # -- Query interface: agents call these instead of scanning trees --------

    def get_affected_files(self, changed_file: str) -> list[str]:
        """Given a changed file, return all files that depend on it (2-level transitive)."""
        node = self.nodes.get(changed_file)
        if not node:
            return []
        affected = set(node.imported_by)
        for dep in list(affected):
            dep_node = self.nodes.get(dep)
            if dep_node:
                affected.update(dep_node.imported_by)
        return sorted(affected)

    def get_blast_radius(
        self,
        changed_files: list[str],
        max_depth: int = 4,
    ) -> dict[str, int]:
        """Compute the full blast radius for a set of changed files.

        Uses BFS to find all transitively affected files up to max_depth.
        Returns {file_path: depth} where depth is how many edges away the
        file is from the nearest change. Depth 0 = the changed file itself.

        Inspired by code-review-graph's blast-radius analysis: only files
        in the blast radius need to be sent to the LLM for review/context.
        """
        affected: dict[str, int] = {}
        queue: list[tuple[str, int]] = []

        for f in changed_files:
            if f in self.nodes:
                affected[f] = 0
                queue.append((f, 0))

        while queue:
            current, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            node = self.nodes.get(current)
            if not node:
                continue
            for dependent in node.imported_by:
                if dependent not in affected:
                    affected[dependent] = depth + 1
                    queue.append((dependent, depth + 1))

        # Also include test files for direct changes
        for f in changed_files:
            for test_file in self.get_test_files_for(f):
                if test_file not in affected:
                    affected[test_file] = 1

        return affected

    def get_test_files_for(self, changed_file: str) -> list[str]:
        """Suggest test files that should be run for a changed file."""
        stem = Path(changed_file).stem
        candidates = []
        for path in self.nodes:
            if f"test_{stem}" in path or f"{stem}_test" in path or f"test/{stem}" in path:
                candidates.append(path)
        return candidates

    def query_layer(self, layer: ServiceLayer) -> list[str]:
        """Return all files that belong to a service layer."""
        return [p for p, n in self.nodes.items() if n.layer == layer]

    def query_imports_of(self, file_path: str) -> list[str]:
        """What does this file import?"""
        node = self.nodes.get(file_path)
        return list(node.imports) if node else []

    def query_importers_of(self, file_path: str) -> list[str]:
        """Who imports this file?"""
        node = self.nodes.get(file_path)
        return list(node.imported_by) if node else []

    def query_routes(self, method: str | None = None, path_contains: str = "") -> list[APIRoute]:
        """Find API routes matching method and/or path substring."""
        results: list[APIRoute] = []
        for r in self.api_routes:
            if method and r.method.upper() != method.upper():
                continue
            if path_contains and path_contains not in r.path:
                continue
            results.append(r)
        return results

    def query_connections(
        self,
        file_path: str | None = None,
        name: str | None = None,
        kind: str | None = None,
    ) -> list[ComponentConnection]:
        """Find component connections involving a file/name/kind."""
        results: list[ComponentConnection] = []
        for c in self.connections:
            if file_path and file_path not in (c.caller_file, c.callee_file):
                continue
            if name and name not in (c.caller_name, c.callee_name):
                continue
            if kind and c.kind != kind:
                continue
            results.append(c)
        return results

    def query_fan_in_top(self, n: int = 10) -> list[tuple[str, int]]:
        """Top n files by number of dependents."""
        ranked = sorted(
            self.nodes.items(),
            key=lambda kv: len(kv[1].imported_by),
            reverse=True,
        )
        return [(path, len(node.imported_by)) for path, node in ranked[:n] if node.imported_by]

    def query_files_by_pattern(self, pattern: str) -> list[str]:
        """Return files matching a glob-like pattern or containing a substring."""
        results: list[str] = []
        for path in self.nodes:
            if pattern in path:
                results.append(path)
        return results

    def to_json(self) -> str:
        return json.dumps({
            "project_id": self.project_id,
            "total_files": len(self.nodes),
            "total_edges": len(self.edges),
            "hot_files": self.hot_files[:10],
            "bottlenecks": self.bottlenecks[:10],
            "api_routes": [
                {"method": r.method, "path": r.path, "handler": r.handler, "file": r.file}
                for r in self.api_routes
            ],
            "layers": {
                layer.value: len(self.query_layer(layer))
                for layer in ServiceLayer
                if self.query_layer(layer)
            },
            "patterns": dict(sorted(self.patterns.items(), key=lambda x: -x[1])[:20]),
            "nodes": {
                k: {
                    "imports": v.imports,
                    "imported_by": v.imported_by,
                    "functions": v.functions,
                    "classes": v.classes,
                    "lines": v.lines,
                    "complexity": v.complexity_score,
                    "layer": v.layer.value,
                }
                for k, v in self.nodes.items()
            },
        }, indent=2)

    def to_prompt_section(self) -> str:
        """Compact summary for agent injection."""
        parts = ["## Project Graph Summary\n"]
        parts.append(f"**Files**: {len(self.nodes)} | **Edges**: {len(self.edges)}")

        # Service layers
        layer_counts = {
            layer.value: len(self.query_layer(layer))
            for layer in ServiceLayer
            if self.query_layer(layer)
        }
        if layer_counts:
            parts.append("**Layers**: " + ", ".join(f"{k}={v}" for k, v in layer_counts.items()))

        if self.hot_files:
            parts.append(f"**Hot files** (most dependents): {', '.join(self.hot_files[:5])}")
        if self.bottlenecks:
            parts.append(f"**Bottlenecks**: {', '.join(self.bottlenecks[:5])}")

        # API routes summary
        if self.api_routes:
            parts.append(f"**API Routes**: {len(self.api_routes)}")
            for r in self.api_routes[:8]:
                parts.append(f"  {r.method:6s} {r.path} -> {r.handler} ({r.file})")

        if self.patterns:
            top_patterns = sorted(self.patterns.items(), key=lambda x: -x[1])[:5]
            parts.append(f"**Patterns**: {', '.join(f'{p}({c})' for p, c in top_patterns)}")
        return "\n".join(parts)


class DependencyGraphEngine:
    """Builds dependency graphs by statically analyzing source code."""

    def __init__(self) -> None:
        self._cache: dict[str, DependencyGraph] = {}

    def analyze(self, root_path: str, project_id: str | None = None) -> DependencyGraph:
        pid = project_id or os.path.basename(root_path)
        if pid in self._cache:
            return self._cache[pid]

        logger.info("Building project graph for: %s", root_path)
        graph = DependencyGraph(project_id=pid)

        self._scan_python(graph, root_path)
        self._scan_js_ts(graph, root_path)
        self._compute_reverse_edges(graph)
        self._classify_layers(graph)
        self._detect_api_routes(graph, root_path)
        self._detect_component_connections(graph, root_path)
        self._find_hot_files(graph)
        self._detect_patterns(graph, root_path)

        self._cache[pid] = graph
        logger.info(
            "Project graph ready: %d nodes, %d edges, %d routes, %d connections",
            len(graph.nodes), len(graph.edges),
            len(graph.api_routes), len(graph.connections),
        )
        return graph

    def invalidate(self, project_id: str) -> None:
        self._cache.pop(project_id, None)

    def query(self, root_path: str, project_id: str | None = None) -> DependencyGraph:
        """Convenience alias — agents call this to get the graph."""
        return self.analyze(root_path, project_id)

    # -- Python analysis ----------------------------------------------------

    def _scan_python(self, graph: DependencyGraph, root: str) -> None:
        skip = {".git", "node_modules", "__pycache__", ".venv", "venv"}
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip]
            for fname in filenames:
                if not fname.endswith(".py"):
                    continue
                full = os.path.join(dirpath, fname)
                rel = os.path.relpath(full, root).replace("\\", "/")
                node = DependencyNode(path=rel)
                try:
                    source = self._read(full)
                    node.lines = source.count("\n") + 1
                    tree = ast.parse(source, filename=rel)
                    for item in ast.walk(tree):
                        if isinstance(item, ast.Import):
                            for alias in item.names:
                                node.imports.append(alias.name)
                                graph.edges.append((rel, alias.name))
                        elif isinstance(item, ast.ImportFrom):
                            if item.module:
                                node.imports.append(item.module)
                                graph.edges.append((rel, item.module))
                        elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            node.functions.append(item.name)
                        elif isinstance(item, ast.ClassDef):
                            node.classes.append(item.name)
                    node.complexity_score = len(node.functions) + len(node.classes) * 2
                except Exception:
                    pass
                graph.nodes[rel] = node

    # -- JS/TS analysis -----------------------------------------------------

    def _scan_js_ts(self, graph: DependencyGraph, root: str) -> None:
        skip = {".git", "node_modules", "__pycache__", ".venv", "dist", "build"}
        import_re = re.compile(
            r"""(?:import\s+.*?\s+from\s+['"](.+?)['"]|require\s*\(\s*['"](.+?)['"]\s*\))"""
        )
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip]
            for fname in filenames:
                if not fname.endswith((".js", ".ts", ".jsx", ".tsx")):
                    continue
                full = os.path.join(dirpath, fname)
                rel = os.path.relpath(full, root).replace("\\", "/")
                if rel in graph.nodes:
                    continue
                node = DependencyNode(path=rel)
                try:
                    source = self._read(full)
                    node.lines = source.count("\n") + 1
                    for m in import_re.finditer(source):
                        imp = m.group(1) or m.group(2)
                        node.imports.append(imp)
                        graph.edges.append((rel, imp))
                    # Count function definitions
                    node.functions = re.findall(
                        r"(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\()",
                        source,
                    )
                    node.complexity_score = len(node.functions)
                except Exception:
                    pass
                graph.nodes[rel] = node

    # -- reverse edges + analysis -------------------------------------------

    def _compute_reverse_edges(self, graph: DependencyGraph) -> None:
        """For each edge A->B, record B.imported_by += A."""
        module_to_file: dict[str, str] = {}
        for path in graph.nodes:
            module = path.replace("/", ".").removesuffix(".py")
            module_to_file[module] = path
            module_to_file[os.path.basename(path).removesuffix(".py")] = path

        for src, target in graph.edges:
            target_file = module_to_file.get(target, target)
            target_node = graph.nodes.get(target_file)
            if target_node and src not in target_node.imported_by:
                target_node.imported_by.append(src)

    # -- service layer classification ---------------------------------------

    _LAYER_PATTERNS: dict[ServiceLayer, list[str]] = {
        ServiceLayer.PRESENTATION: [
            "route", "view", "controller", "handler", "endpoint", "page",
            "api/", "routes/", "views/", "controllers/", "pages/",
        ],
        ServiceLayer.BUSINESS: [
            "service", "manager", "usecase", "use_case", "domain", "logic",
            "services/", "domain/", "usecases/",
        ],
        ServiceLayer.DATA: [
            "model", "repo", "repository", "dao", "schema", "migration",
            "models/", "repositories/", "schemas/", "migrations/",
        ],
        ServiceLayer.INFRASTRUCTURE: [
            "config", "util", "helper", "middleware", "adapter", "plugin",
            "utils/", "helpers/", "middleware/", "adapters/", "infra/",
        ],
        ServiceLayer.TEST: [
            "test_", "_test.", "spec.", ".test.", ".spec.",
            "tests/", "__tests__/",
        ],
    }

    def _classify_layers(self, graph: DependencyGraph) -> None:
        """Assign a service layer to each node based on path/name heuristics."""
        for path, node in graph.nodes.items():
            path_lower = path.lower()
            best_layer = ServiceLayer.UNKNOWN
            best_score = 0
            for layer, patterns in self._LAYER_PATTERNS.items():
                score = sum(1 for p in patterns if p in path_lower)
                if score > best_score:
                    best_score = score
                    best_layer = layer
            node.layer = best_layer

    # -- API route detection ------------------------------------------------

    def _detect_api_routes(self, graph: DependencyGraph, root: str) -> None:
        """Detect HTTP routes from FastAPI, Flask, Express, etc."""
        py_route_re = re.compile(
            r"""@(?:app|router|bp|blueprint)\."""
            r"""(get|post|put|patch|delete|route)\s*\(\s*['"](.+?)['"]""",
            re.IGNORECASE,
        )
        js_route_re = re.compile(
            r"""(?:app|router)\."""
            r"""(get|post|put|patch|delete)\s*\(\s*['"](.+?)['"]""",
            re.IGNORECASE,
        )
        handler_re = re.compile(
            r"""(?:async\s+)?def\s+(\w+)|(?:async\s+)?function\s+(\w+)"""
        )

        for path, node in graph.nodes.items():
            try:
                source = self._read(os.path.join(root, path))
            except Exception:
                continue

            route_re = py_route_re if path.endswith(".py") else js_route_re
            for m in route_re.finditer(source):
                method = m.group(1).upper()
                route_path = m.group(2)
                # Find handler name (next function after the decorator)
                after = source[m.end():]
                h_match = handler_re.search(after[:200])
                handler = (h_match.group(1) or h_match.group(2)) if h_match else "unknown"
                graph.api_routes.append(APIRoute(
                    method=method,
                    path=route_path,
                    handler=handler,
                    file=path,
                ))

    # -- component connection detection -------------------------------------

    def _detect_component_connections(self, graph: DependencyGraph, root: str) -> None:
        """Detect direct function/class references between files."""
        # Build a map of exported names -> file
        name_to_file: dict[str, str] = {}
        for path, node in graph.nodes.items():
            for cls in node.classes:
                name_to_file[cls] = path
            for fn in node.functions:
                if not fn.startswith("_"):
                    name_to_file[fn] = path
            node.exports = list(node.classes) + [f for f in node.functions if not f.startswith("_")]

        # For each file, look for references to exported names from other files
        for path, node in graph.nodes.items():
            try:
                source = self._read(os.path.join(root, path))
            except Exception:
                continue
            for name, target_file in name_to_file.items():
                if target_file == path:
                    continue  # skip self-references
                # Only check if the file actually imports the target
                if target_file.removesuffix(".py").replace("/", ".") not in " ".join(node.imports):
                    basename = os.path.basename(target_file).removesuffix(".py")
                    if basename not in " ".join(node.imports):
                        continue
                # Check if the name appears in source (as a call or reference)
                if re.search(rf"\b{re.escape(name)}\s*\(", source):
                    graph.connections.append(ComponentConnection(
                        caller_file=path,
                        caller_name=path,
                        callee_file=target_file,
                        callee_name=name,
                        kind="call",
                    ))
                elif re.search(rf"\({re.escape(name)}\)|:\s*{re.escape(name)}\b", source):
                    graph.connections.append(ComponentConnection(
                        caller_file=path,
                        caller_name=path,
                        callee_file=target_file,
                        callee_name=name,
                        kind="inherit",
                    ))

    def _find_hot_files(self, graph: DependencyGraph) -> None:
        """Find files with the most dependents (high fan-in)."""
        by_fan_in = sorted(
            graph.nodes.values(),
            key=lambda n: len(n.imported_by),
            reverse=True,
        )
        graph.hot_files = [n.path for n in by_fan_in[:10] if n.imported_by]
        graph.bottlenecks = [
            n.path for n in by_fan_in[:5]
            if len(n.imported_by) > 3 and n.complexity_score > 5
        ]

    def _detect_patterns(self, graph: DependencyGraph, root: str) -> None:
        """Detect repeated code patterns across the project."""
        pattern_counter: Counter[str] = Counter()
        for node in graph.nodes.values():
            if not node.path.endswith(".py"):
                continue
            try:
                source = self._read(os.path.join(root, node.path))
                # Detect common patterns
                if "async def " in source:
                    pattern_counter["async-functions"] += 1
                if "class " in source and "(BaseModel)" in source:
                    pattern_counter["pydantic-models"] += 1
                if "@app." in source or "@router." in source:
                    pattern_counter["fastapi-routes"] += 1
                if "try:" in source and "except" in source:
                    pattern_counter["try-except-blocks"] += source.count("try:")
                if "logging.getLogger" in source:
                    pattern_counter["logger-usage"] += 1
                if "async with" in source:
                    pattern_counter["async-context-managers"] += 1
            except Exception:
                pass
        graph.patterns = dict(pattern_counter)

    @staticmethod
    def _read(path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return ""


# -- Singleton ---------------------------------------------------------------

_instance: DependencyGraphEngine | None = None


def get_dep_graph_engine() -> DependencyGraphEngine:
    global _instance
    if _instance is None:
        _instance = DependencyGraphEngine()
    return _instance
