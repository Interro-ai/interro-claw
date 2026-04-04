"""
High-Speed File Indexer

Fast incremental indexing of project files:
- File metadata (path, size, mtime, hash)
- Symbol extraction (functions, classes, exports)
- AST summaries (structure overview)
- Change detection (only re-index modified files)
- Auto-triggered before major agent operations

Stores index in Working Memory for persistence across sessions.
"""

from __future__ import annotations

import ast
import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next"}
_CODE_EXTS = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".rb", ".cs"}
_ALL_EXTS = _CODE_EXTS | {".json", ".yaml", ".yml", ".toml", ".md", ".txt", ".cfg", ".ini"}


@dataclass
class FileEntry:
    path: str
    ext: str
    size: int
    mtime: float
    content_hash: str
    symbols: list[str] = field(default_factory=list)
    ast_summary: str = ""
    indexed_at: float = 0.0


@dataclass
class IndexStats:
    total_files: int = 0
    indexed_files: int = 0
    skipped_files: int = 0
    elapsed_ms: int = 0


class FileIndexer:
    """Incrementally indexes project files for fast symbol lookup and change detection."""

    def __init__(self, root_path: str | None = None) -> None:
        self._root = root_path or os.path.dirname(os.path.dirname(__file__))
        self._index: dict[str, FileEntry] = {}
        self._last_full_index: float = 0.0

    def index(self, force: bool = False) -> IndexStats:
        """Run incremental index (or full if forced or first run)."""
        start = time.monotonic()
        stats = IndexStats()

        for dirpath, dirnames, filenames in os.walk(self._root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in _ALL_EXTS:
                    continue
                full = os.path.join(dirpath, fname)
                rel = os.path.relpath(full, self._root).replace("\\", "/")
                stats.total_files += 1

                try:
                    st = os.stat(full)
                except OSError:
                    continue

                # Skip if not modified since last index
                existing = self._index.get(rel)
                if existing and not force and existing.mtime >= st.st_mtime:
                    stats.skipped_files += 1
                    continue

                # Index this file
                entry = self._index_file(rel, full, ext, st)
                if entry:
                    self._index[rel] = entry
                    stats.indexed_files += 1

        # Remove deleted files
        current_paths = set()
        for dirpath, dirnames, filenames in os.walk(self._root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fname in filenames:
                full = os.path.join(dirpath, fname)
                rel = os.path.relpath(full, self._root).replace("\\", "/")
                current_paths.add(rel)
        stale = set(self._index.keys()) - current_paths
        for s in stale:
            del self._index[s]

        stats.elapsed_ms = int((time.monotonic() - start) * 1000)
        self._last_full_index = time.time()
        logger.info(
            "Index: %d total, %d indexed, %d skipped (%dms)",
            stats.total_files, stats.indexed_files, stats.skipped_files, stats.elapsed_ms,
        )
        return stats

    def _index_file(self, rel: str, full: str, ext: str, st: os.stat_result) -> FileEntry | None:
        try:
            with open(full, "rb") as f:
                raw = f.read()
            content_hash = hashlib.sha256(raw).hexdigest()[:16]
        except Exception:
            return None

        symbols: list[str] = []
        ast_summary = ""

        if ext == ".py":
            symbols, ast_summary = self._analyze_python(raw, rel)
        elif ext in (".js", ".ts", ".jsx", ".tsx"):
            symbols, ast_summary = self._analyze_js(raw, rel)

        return FileEntry(
            path=rel, ext=ext, size=st.st_size, mtime=st.st_mtime,
            content_hash=content_hash, symbols=symbols,
            ast_summary=ast_summary, indexed_at=time.time(),
        )

    def _analyze_python(self, raw: bytes, path: str) -> tuple[list[str], str]:
        symbols: list[str] = []
        try:
            source = raw.decode("utf-8", errors="ignore")
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            return symbols, "syntax_error"

        classes = []
        functions = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                symbols.append(f"class:{node.name}")
                classes.append(node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(f"func:{node.name}")
                functions.append(node.name)

        summary = ""
        if classes:
            summary += f"classes: {', '.join(classes[:10])}; "
        if functions:
            summary += f"functions: {', '.join(functions[:10])}"
        return symbols, summary.strip("; ")

    def _analyze_js(self, raw: bytes, path: str) -> tuple[list[str], str]:
        symbols: list[str] = []
        source = raw.decode("utf-8", errors="ignore")
        func_re = re.compile(r"(?:export\s+)?(?:async\s+)?function\s+(\w+)")
        class_re = re.compile(r"(?:export\s+)?class\s+(\w+)")
        const_re = re.compile(r"(?:export\s+)?const\s+(\w+)\s*=")

        classes = [m.group(1) for m in class_re.finditer(source)]
        functions = [m.group(1) for m in func_re.finditer(source)]
        consts = [m.group(1) for m in const_re.finditer(source)]

        for c in classes:
            symbols.append(f"class:{c}")
        for f in functions:
            symbols.append(f"func:{f}")
        for c in consts[:10]:
            symbols.append(f"const:{c}")

        parts = []
        if classes:
            parts.append(f"classes: {', '.join(classes[:10])}")
        if functions:
            parts.append(f"functions: {', '.join(functions[:10])}")
        return symbols, "; ".join(parts)

    # -- Query API -----------------------------------------------------------

    def search_symbol(self, name: str) -> list[FileEntry]:
        """Find files containing a symbol matching name."""
        name_lower = name.lower()
        return [e for e in self._index.values() if any(name_lower in s.lower() for s in e.symbols)]

    def get_entry(self, path: str) -> FileEntry | None:
        return self._index.get(path)

    def get_changed_since(self, timestamp: float) -> list[FileEntry]:
        """Files modified since a timestamp."""
        return [e for e in self._index.values() if e.mtime > timestamp]

    def get_all_entries(self) -> list[FileEntry]:
        return list(self._index.values())

    @property
    def file_count(self) -> int:
        return len(self._index)

    def persist_to_working_memory(self, project_id: str = "default") -> None:
        """Save index metadata to working memory for cross-session persistence."""
        try:
            from interro_claw.memory.working import get_working_memory
            wm = get_working_memory(project_id)
            for path, entry in self._index.items():
                wm.upsert_file_context(
                    file_path=path,
                    file_hash=entry.content_hash,
                    symbols=entry.symbols,
                    ast_summary=entry.ast_summary,
                )
        except Exception as e:
            logger.debug("Could not persist index to working memory: %s", e)


# -- Singleton ---------------------------------------------------------------

_instance: FileIndexer | None = None


def get_file_indexer(root_path: str | None = None) -> FileIndexer:
    global _instance
    if _instance is None:
        _instance = FileIndexer(root_path)
    return _instance
