"""
Intelligent File Selector

Instead of feeding whole file trees to agents, this module:
1. Analyzes git commits to detect recently changed files
2. Uses the project dependency graph to find impacted areas
3. Scores files by relevance to the current task
4. Returns only the most relevant files + their content

This massively reduces token usage and boosts agent speed.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".tox"}
_BINARY_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".eot",
                ".zip", ".tar", ".gz", ".exe", ".dll", ".so", ".pyc", ".pyo", ".db", ".sqlite3"}

# Max chars to include per file (to avoid blowing token budgets)
_MAX_FILE_CHARS = 8000


@dataclass
class SelectedFile:
    """A file selected for agent context."""
    path: str             # relative path
    relevance: float      # 0.0 - 1.0 score
    reason: str           # why this file was selected
    content: str = ""     # file content (truncated)
    lines: int = 0


@dataclass
class FileSelection:
    """Result of intelligent file selection."""
    files: list[SelectedFile] = field(default_factory=list)
    total_chars: int = 0
    skipped_count: int = 0

    def to_prompt_section(self, max_files: int = 10) -> str:
        """Format as a prompt section for agent injection."""
        if not self.files:
            return ""
        parts = [f"## Relevant Files ({len(self.files)} selected)\n"]
        for f in self.files[:max_files]:
            parts.append(f"### {f.path} (relevance: {f.relevance:.2f}, {f.lines} lines)")
            parts.append(f"_Reason: {f.reason}_")
            if f.content:
                parts.append(f"```\n{f.content}\n```")
            parts.append("")
        if len(self.files) > max_files:
            parts.append(f"_(+{len(self.files) - max_files} more files available)_")
        return "\n".join(parts)


class FileSelector:
    """
    Intelligently selects files relevant to a task using:
    - Keyword matching in file names and content
    - Git change detection (recently modified files)
    - Dependency graph awareness (impacted files)
    - File type filtering
    """

    def __init__(self, root_path: str) -> None:
        self._root = root_path

    def select(
        self,
        task: str,
        dep_graph: Any | None = None,
        changed_files: list[str] | None = None,
        max_files: int = 15,
        max_total_chars: int = 50000,
        file_types: list[str] | None = None,
    ) -> FileSelection:
        """
        Select relevant files for a task.

        Args:
            task: The task description to match against
            dep_graph: Optional DependencyGraph for impact analysis
            changed_files: Optional pre-computed list of changed files
            max_files: Maximum number of files to return
            max_total_chars: Total character budget for all file contents
            file_types: Optional filter by extensions (e.g., [".py", ".ts"])
        """
        # Step 1: Get candidate files
        candidates = self._get_all_files(file_types)

        # Step 2: Score each file
        scored: list[SelectedFile] = []
        task_keywords = self._extract_keywords(task)
        git_changed = changed_files or self._get_git_changed_files()

        # Compute blast radius from dep graph for changed files
        blast_radius: dict[str, int] = {}
        if dep_graph and hasattr(dep_graph, "get_blast_radius") and git_changed:
            try:
                blast_radius = dep_graph.get_blast_radius(git_changed, max_depth=4)
                pruned_count = len(candidates) - len(blast_radius)
                logger.info(
                    "Blast radius: %d files affected by %d changes, %d files pruned",
                    len(blast_radius), len(git_changed), max(0, pruned_count),
                )
                if pruned_count > 0:
                    from interro_claw.telemetry import record as _trecord
                    _trecord("files_pruned_by_blast_radius", max(0, pruned_count))
            except Exception as exc:
                logger.debug("Blast radius computation skipped: %s", exc)

        for rel_path in candidates:
            score, reason = self._score_file(
                rel_path, task_keywords, git_changed, dep_graph,
                blast_radius=blast_radius,
            )
            if score > 0.05:
                scored.append(SelectedFile(
                    path=rel_path,
                    relevance=min(score, 1.0),
                    reason=reason,
                ))

        # Step 3: Sort by relevance and take top N
        scored.sort(key=lambda f: f.relevance, reverse=True)
        selected = scored[:max_files]

        # Step 4: Load content within budget
        total_chars = 0
        skipped = 0
        for sf in selected:
            full_path = os.path.join(self._root, sf.path)
            content = self._read_file(full_path)
            sf.lines = content.count("\n") + 1
            if total_chars + len(content) > max_total_chars:
                # Truncate this file to fit
                remaining = max_total_chars - total_chars
                if remaining > 500:
                    sf.content = content[:remaining] + "\n... [truncated]"
                    total_chars += remaining
                else:
                    skipped += 1
                    continue
            else:
                sf.content = content[:_MAX_FILE_CHARS]
                if len(content) > _MAX_FILE_CHARS:
                    sf.content += "\n... [truncated]"
                total_chars += len(sf.content)

        return FileSelection(
            files=[f for f in selected if f.content],
            total_chars=total_chars,
            skipped_count=skipped + len(scored) - len(selected),
        )

    # -- file discovery -----------------------------------------------------

    def _get_all_files(self, file_types: list[str] | None = None) -> list[str]:
        """Get all non-binary files in the project."""
        files: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self._root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fname in filenames:
                ext = Path(fname).suffix.lower()
                if ext in _BINARY_EXTS:
                    continue
                if file_types and ext not in file_types:
                    continue
                rel = os.path.relpath(os.path.join(dirpath, fname), self._root)
                files.append(rel.replace("\\", "/"))
        return files

    # -- scoring ------------------------------------------------------------

    def _score_file(
        self,
        path: str,
        task_keywords: set[str],
        git_changed: list[str],
        dep_graph: Any | None,
        blast_radius: dict[str, int] | None = None,
    ) -> tuple[float, str]:
        """Score a file's relevance to the current task. Returns (score, reason)."""
        score = 0.0
        reasons: list[str] = []

        # 0. Blast-radius boost — files in the impact zone of recent changes
        norm_path = path.replace("\\", "/")
        if blast_radius and norm_path in blast_radius:
            depth = blast_radius[norm_path]
            # Closer to the change = higher boost (depth 0=0.4, 1=0.35, 2=0.25, 3+=0.15)
            boost = max(0.15, 0.40 - depth * 0.05)
            score += boost
            reasons.append(f"in blast radius (depth={depth})")

        # 1. Keyword match in file path
        path_lower = path.lower()
        path_parts = set(re.split(r"[/\\._\-]", path_lower))
        keyword_hits = task_keywords & path_parts
        if keyword_hits:
            score += 0.3 * min(len(keyword_hits) / 3, 1.0)
            reasons.append(f"path matches: {', '.join(keyword_hits)}")

        # 2. Git recently changed
        norm_path = path.replace("\\", "/")
        if norm_path in git_changed:
            score += 0.25
            reasons.append("recently changed in git")

        # 3. Dependency graph: high fan-in = important
        if dep_graph and hasattr(dep_graph, "nodes"):
            node = dep_graph.nodes.get(norm_path)
            if node:
                fan_in = len(node.imported_by)
                if fan_in > 3:
                    score += 0.2
                    reasons.append(f"high fan-in ({fan_in} dependents)")
                elif fan_in > 0:
                    score += 0.1
                    reasons.append(f"has {fan_in} dependent(s)")

        # 4. Dependency graph: hot file
        if dep_graph and hasattr(dep_graph, "hot_files"):
            if norm_path in dep_graph.hot_files:
                score += 0.15
                reasons.append("hot file (many dependents)")

        # 5. File type relevance
        ext = Path(path).suffix.lower()
        if ext in (".py", ".ts", ".tsx", ".js", ".jsx"):
            score += 0.05
            reasons.append("source code")
        elif ext in (".json", ".yaml", ".yml", ".toml"):
            if any(kw in path_lower for kw in ("config", "package", "requirements", "pyproject")):
                score += 0.1
                reasons.append("config file")

        # 6. Keyword match in content (lightweight — check first 2000 chars)
        if task_keywords and score < 0.5:
            try:
                full_path = os.path.join(self._root, path)
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    head = f.read(2000).lower()
                content_hits = sum(1 for kw in task_keywords if kw in head)
                if content_hits > 0:
                    score += 0.15 * min(content_hits / 5, 1.0)
                    reasons.append(f"content matches ({content_hits} keywords)")
            except Exception:
                pass

        reason = "; ".join(reasons) if reasons else "low relevance"
        return score, reason

    # -- git integration ----------------------------------------------------

    def _get_git_changed_files(self, max_commits: int = 20) -> list[str]:
        """Get files changed in recent git commits."""
        try:
            result = subprocess.run(
                ["git", "log", f"--max-count={max_commits}", "--name-only",
                 "--pretty=format:", "--diff-filter=ACMR"],
                cwd=self._root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return []
            files = [
                f.strip().replace("\\", "/")
                for f in result.stdout.splitlines()
                if f.strip()
            ]
            return list(dict.fromkeys(files))  # deduplicate preserving order
        except Exception:
            return []

    # -- keyword extraction -------------------------------------------------

    @staticmethod
    def _extract_keywords(text: str) -> set[str]:
        """Extract meaningful keywords from task description."""
        # Remove common stop words and extract word tokens
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "shall", "can", "need", "must", "ought",
            "and", "but", "or", "nor", "for", "yet", "so", "in", "on", "at",
            "to", "from", "by", "with", "of", "as", "into", "through", "during",
            "before", "after", "above", "below", "between", "this", "that",
            "these", "those", "it", "its", "they", "them", "their", "we", "our",
            "you", "your", "i", "me", "my", "add", "create", "build", "make",
            "implement", "write", "update", "fix", "change", "use", "using",
        }
        words = set(re.findall(r"\b[a-z][a-z0-9]+\b", text.lower()))
        return words - stop_words

    # -- file reading -------------------------------------------------------

    @staticmethod
    def _read_file(path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return ""


# -- Singleton ---------------------------------------------------------------

_instances: dict[str, FileSelector] = {}


def get_file_selector(root_path: str) -> FileSelector:
    if root_path not in _instances:
        _instances[root_path] = FileSelector(root_path)
    return _instances[root_path]
