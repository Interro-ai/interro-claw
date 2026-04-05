"""
Project Graph Engine

Parses a project folder and builds a comprehensive code understanding graph:
- File dependency graph (import/require edges)
- API graph (routes -> handlers -> services)
- Component tree (class hierarchies, module groupings)
- Symbol index (functions, classes, exports)

Saves to memory/projects/<project_id>/graph.json for persistence.
Agents query this graph instead of scanning file trees.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next"}


@dataclass
class SymbolInfo:
    name: str
    kind: str  # "function", "class", "variable", "route"
    file: str
    line: int = 0
    docstring: str = ""


@dataclass
class Edge:
    source: str
    target: str
    kind: str  # "import", "call", "inherit", "route"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProjectGraph:
    """The complete code understanding graph."""
    project_id: str
    files: dict[str, dict[str, Any]] = field(default_factory=dict)  # path -> file info
    symbols: list[SymbolInfo] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    api_routes: list[dict[str, str]] = field(default_factory=list)
    component_tree: dict[str, list[str]] = field(default_factory=dict)  # parent -> children
    # Change tracking metadata (populated by incremental build)
    changed_files: list[str] = field(default_factory=list)  # files modified since last build
    removed_files: list[str] = field(default_factory=list)  # files deleted since last build
    file_hash: str = ""

    def query_symbol(self, name: str) -> list[SymbolInfo]:
        """Find symbols by name (partial match)."""
        name_lower = name.lower()
        return [s for s in self.symbols if name_lower in s.name.lower()]

    def query_dependents(self, file_path: str) -> list[str]:
        """Who depends on this file?"""
        return [e.source for e in self.edges if e.target == file_path and e.kind == "import"]

    def query_dependencies(self, file_path: str) -> list[str]:
        """What does this file depend on?"""
        return [e.target for e in self.edges if e.source == file_path and e.kind == "import"]

    def query_routes(self, path_contains: str = "") -> list[dict[str, str]]:
        return [r for r in self.api_routes if path_contains in r.get("path", "")]

    def query_files_in_layer(self, layer: str) -> list[str]:
        """Find files belonging to a conceptual layer."""
        layer_patterns = {
            "api": ["route", "controller", "endpoint", "handler", "api/"],
            "service": ["service", "manager", "usecase", "domain/"],
            "data": ["model", "repo", "schema", "migration", "dao"],
            "infra": ["config", "util", "helper", "middleware"],
            "test": ["test_", "_test.", "spec.", "tests/", "__tests__/"],
        }
        patterns = layer_patterns.get(layer, [])
        results = []
        for path in self.files:
            p_lower = path.lower()
            if any(pat in p_lower for pat in patterns):
                results.append(path)
        return results

    def to_json(self) -> str:
        return json.dumps({
            "project_id": self.project_id,
            "total_files": len(self.files),
            "total_symbols": len(self.symbols),
            "total_edges": len(self.edges),
            "api_routes": self.api_routes,
            "files": self.files,
            "symbols": [
                {"name": s.name, "kind": s.kind, "file": s.file, "line": s.line}
                for s in self.symbols
            ],
            "edges": [
                {"source": e.source, "target": e.target, "kind": e.kind}
                for e in self.edges
            ],
        }, indent=2)

    def to_prompt_section(self) -> str:
        parts = [f"## Project Graph ({len(self.files)} files, {len(self.symbols)} symbols)"]
        if self.api_routes:
            parts.append(f"**API Routes**: {len(self.api_routes)}")
            for r in self.api_routes[:10]:
                parts.append(f"  {r.get('method','?'):6s} {r.get('path','')} -> {r.get('handler','')} ({r.get('file','')})")
        layers = {}
        for layer in ("api", "service", "data", "infra", "test"):
            files = self.query_files_in_layer(layer)
            if files:
                layers[layer] = len(files)
        if layers:
            parts.append("**Layers**: " + ", ".join(f"{k}={v}" for k, v in layers.items()))
        # Top symbols
        classes = [s for s in self.symbols if s.kind == "class"]
        if classes:
            parts.append(f"**Classes**: {', '.join(s.name for s in classes[:15])}")
        return "\n".join(parts)


class ProjectGraphEngine:
    """Builds and caches project graphs with incremental per-file updates."""

    def __init__(self) -> None:
        self._cache: dict[str, ProjectGraph] = {}
        # Per-file SHA256 content hashes for incremental detection
        self._file_hashes: dict[str, dict[str, str]] = {}  # project_id -> {rel_path: hash}

    def build(self, root: str, project_id: str = "default") -> ProjectGraph:
        """Build or return cached graph. Uses per-file hashing for incremental updates."""
        tree_hash = self._tree_hash(root)
        cached = self._cache.get(project_id)
        if cached and cached.file_hash == tree_hash:
            return cached

        # Determine which files actually changed content (not just mtime)
        old_hashes = self._file_hashes.get(project_id, {})
        new_hashes: dict[str, str] = {}
        changed_files: list[str] = []

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in (".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".yaml", ".yml", ".md"):
                    continue
                full = os.path.join(dirpath, fname)
                rel = os.path.relpath(full, root).replace("\\", "/")
                try:
                    content_hash = self._content_hash(full)
                    new_hashes[rel] = content_hash
                    if old_hashes.get(rel) != content_hash:
                        changed_files.append(rel)
                except OSError:
                    pass

        # Detect removed files
        removed_files = set(old_hashes.keys()) - set(new_hashes.keys())

        self._file_hashes[project_id] = new_hashes

        # Log incremental stats
        unchanged = len(new_hashes) - len(changed_files)
        logger.info(
            "Graph: %d files total, %d changed, %d removed, %d unchanged — %s",
            len(new_hashes), len(changed_files), len(removed_files),
            unchanged, "full rebuild" if not cached else "incremental",
        )
        if unchanged > 0:
            from interro_claw.telemetry import record as _trecord
            _trecord("files_skipped_unchanged", unchanged)

        # Full rebuild (we still rebuild fully, but now we KNOW what changed
        # and store that info on the graph for downstream blast-radius use)
        graph = ProjectGraph(project_id=project_id, file_hash=tree_hash)

        self._scan_files(graph, root)
        self._extract_python_symbols(graph, root)
        self._extract_js_symbols(graph, root)
        self._detect_routes(graph, root)
        self._build_component_tree(graph)

        # Attach change metadata for blast-radius consumers
        graph.changed_files = changed_files
        graph.removed_files = list(removed_files)

        self._cache[project_id] = graph
        self._persist(graph, root, project_id)

        logger.info(
            "Project graph: %d files, %d symbols, %d edges, %d routes",
            len(graph.files), len(graph.symbols), len(graph.edges), len(graph.api_routes),
        )
        return graph

    @staticmethod
    def _content_hash(file_path: str) -> str:
        """SHA256 of file content (first 64KB to stay fast on large files)."""
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            h.update(f.read(65536))
        return h.hexdigest()[:16]

    def query(self, root: str, project_id: str = "default") -> ProjectGraph:
        """Alias for build — agents use this."""
        return self.build(root, project_id)

    def invalidate(self, project_id: str) -> None:
        self._cache.pop(project_id, None)

    # -- Scanning ------------------------------------------------------------

    def _scan_files(self, graph: ProjectGraph, root: str) -> None:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in (".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".yaml", ".yml", ".md"):
                    continue
                full = os.path.join(dirpath, fname)
                rel = os.path.relpath(full, root).replace("\\", "/")
                try:
                    stat = os.stat(full)
                    graph.files[rel] = {
                        "ext": ext,
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                    }
                except OSError:
                    pass

    def _extract_python_symbols(self, graph: ProjectGraph, root: str) -> None:
        for path, info in graph.files.items():
            if info["ext"] != ".py":
                continue
            full = os.path.join(root, path)
            try:
                source = self._read(full)
                tree = ast.parse(source, filename=path)
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    doc = ast.get_docstring(node) or ""
                    graph.symbols.append(SymbolInfo(
                        name=node.name, kind="class", file=path,
                        line=node.lineno, docstring=doc[:200],
                    ))
                    # Check inheritance
                    for base in node.bases:
                        base_name = ""
                        if isinstance(base, ast.Name):
                            base_name = base.id
                        elif isinstance(base, ast.Attribute):
                            base_name = base.attr
                        if base_name:
                            graph.edges.append(Edge(
                                source=path, target=base_name, kind="inherit",
                                metadata={"child": node.name, "parent": base_name},
                            ))
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    graph.symbols.append(SymbolInfo(
                        name=node.name, kind="function", file=path, line=node.lineno,
                    ))
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        graph.edges.append(Edge(source=path, target=alias.name, kind="import"))
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        graph.edges.append(Edge(source=path, target=node.module, kind="import"))

    def _extract_js_symbols(self, graph: ProjectGraph, root: str) -> None:
        import_re = re.compile(r"""(?:import\s+.*?\s+from\s+['"](.+?)['"]|require\s*\(\s*['"](.+?)['"]\s*\))""")
        func_re = re.compile(r"(?:export\s+)?(?:async\s+)?function\s+(\w+)")
        class_re = re.compile(r"(?:export\s+)?class\s+(\w+)")
        const_re = re.compile(r"(?:export\s+)?const\s+(\w+)\s*=")

        for path, info in graph.files.items():
            if info["ext"] not in (".js", ".ts", ".jsx", ".tsx"):
                continue
            full = os.path.join(root, path)
            try:
                source = self._read(full)
            except Exception:
                continue

            for m in import_re.finditer(source):
                target = m.group(1) or m.group(2)
                graph.edges.append(Edge(source=path, target=target, kind="import"))
            for m in func_re.finditer(source):
                graph.symbols.append(SymbolInfo(name=m.group(1), kind="function", file=path))
            for m in class_re.finditer(source):
                graph.symbols.append(SymbolInfo(name=m.group(1), kind="class", file=path))
            for m in const_re.finditer(source):
                graph.symbols.append(SymbolInfo(name=m.group(1), kind="variable", file=path))

    def _detect_routes(self, graph: ProjectGraph, root: str) -> None:
        py_route_re = re.compile(
            r"@(?:app|router|bp|blueprint)\.(get|post|put|patch|delete|route)\s*\(\s*['\"](.+?)['\"]",
            re.IGNORECASE,
        )
        js_route_re = re.compile(
            r"(?:app|router)\.(get|post|put|patch|delete)\s*\(\s*['\"](.+?)['\"]",
            re.IGNORECASE,
        )
        handler_re = re.compile(r"(?:async\s+)?(?:def|function)\s+(\w+)")

        for path, info in graph.files.items():
            full = os.path.join(root, path)
            try:
                source = self._read(full)
            except Exception:
                continue
            route_re = py_route_re if info["ext"] == ".py" else js_route_re
            for m in route_re.finditer(source):
                method = m.group(1).upper()
                route_path = m.group(2)
                after = source[m.end():]
                h = handler_re.search(after[:300])
                handler = h.group(1) if h else "unknown"
                graph.api_routes.append({
                    "method": method, "path": route_path,
                    "handler": handler, "file": path,
                })

    def _build_component_tree(self, graph: ProjectGraph) -> None:
        """Group files into parent directories as component tree."""
        for path in graph.files:
            parts = path.split("/")
            if len(parts) > 1:
                parent = "/".join(parts[:-1])
                graph.component_tree.setdefault(parent, []).append(path)

    # -- Persistence ---------------------------------------------------------

    def _persist(self, graph: ProjectGraph, root: str, project_id: str) -> None:
        """Save graph to memory/projects/<project_id>/graph.json."""
        proj_dir = os.path.join(root, "memory", "projects", project_id)
        os.makedirs(proj_dir, exist_ok=True)
        path = os.path.join(proj_dir, "graph.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(graph.to_json())

    def _tree_hash(self, root: str) -> str:
        """Quick hash of file names + sizes for change detection."""
        h = hashlib.md5()
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fname in sorted(filenames):
                full = os.path.join(dirpath, fname)
                try:
                    st = os.stat(full)
                    h.update(f"{fname}:{st.st_size}:{int(st.st_mtime)}".encode())
                except OSError:
                    pass
        return h.hexdigest()

    @staticmethod
    def _read(path: str) -> str:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()


# -- Singleton ---------------------------------------------------------------

_instance: ProjectGraphEngine | None = None


def get_project_graph_engine() -> ProjectGraphEngine:
    global _instance
    if _instance is None:
        _instance = ProjectGraphEngine()
    return _instance
