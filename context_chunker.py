"""
Context Chunker

Intelligently chunks large files for LLM context windows:
1. Splits by logical boundaries (functions, classes, sections)
2. Preserves semantic coherence (never breaks mid-function)
3. Adds surrounding context (imports, class headers) to each chunk
4. Scores chunks by relevance to the current task

Agents use this instead of feeding entire large files to the LLM.
"""

from __future__ import annotations

import ast
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Default chunk size (characters)
_DEFAULT_CHUNK_SIZE = 4000
_MIN_CHUNK_SIZE = 500
_MAX_CHUNK_SIZE = 12000


@dataclass
class Chunk:
    """A logical chunk of a file."""
    file_path: str
    start_line: int
    end_line: int
    content: str
    chunk_type: str  # "imports", "class", "function", "section", "block"
    name: str = ""   # class/function name if applicable
    relevance: float = 0.0

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1


@dataclass
class ChunkedFile:
    """A file split into intelligent chunks."""
    path: str
    total_lines: int
    chunks: list[Chunk] = field(default_factory=list)
    header: str = ""  # imports + top-level declarations (always included)

    def get_relevant_chunks(
        self,
        task: str,
        max_chunks: int = 5,
        max_chars: int = 15000,
    ) -> list[Chunk]:
        """Return the most relevant chunks for a task, within budget."""
        _score_chunks(self.chunks, task)
        sorted_chunks = sorted(self.chunks, key=lambda c: c.relevance, reverse=True)
        selected: list[Chunk] = []
        total = 0
        for chunk in sorted_chunks[:max_chunks]:
            if total + len(chunk.content) > max_chars:
                break
            selected.append(chunk)
            total += len(chunk.content)
        # Return in file order
        selected.sort(key=lambda c: c.start_line)
        return selected

    def to_prompt_section(self, task: str = "", max_chars: int = 15000) -> str:
        """Format relevant chunks as a prompt section."""
        if not self.chunks:
            return ""
        parts = [f"## File: {self.path} ({self.total_lines} lines)\n"]
        if self.header:
            parts.append(f"### Header (imports & declarations)\n```\n{self.header}\n```\n")

        relevant = self.get_relevant_chunks(task, max_chars=max_chars)
        for chunk in relevant:
            label = f"{chunk.chunk_type}"
            if chunk.name:
                label += f": {chunk.name}"
            parts.append(
                f"### Lines {chunk.start_line}-{chunk.end_line} ({label})"
                f"\n```\n{chunk.content}\n```\n"
            )
        return "\n".join(parts)


class ContextChunker:
    """Splits files into semantic chunks based on language-aware boundaries."""

    def chunk_file(
        self,
        file_path: str,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
    ) -> ChunkedFile:
        """Chunk a file into logical pieces."""
        content = self._read(file_path)
        if not content:
            return ChunkedFile(path=file_path, total_lines=0)

        lines = content.splitlines(keepends=True)
        total_lines = len(lines)
        rel_path = os.path.basename(file_path)

        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".py":
            return self._chunk_python(file_path, content, lines, total_lines)
        elif ext in (".js", ".ts", ".jsx", ".tsx"):
            return self._chunk_js_ts(file_path, content, lines, total_lines, chunk_size)
        elif ext in (".md", ".rst", ".txt"):
            return self._chunk_markdown(file_path, content, lines, total_lines)
        else:
            return self._chunk_generic(file_path, content, lines, total_lines, chunk_size)

    def chunk_multiple(
        self,
        file_paths: list[str],
        task: str = "",
        max_total_chars: int = 50000,
    ) -> list[ChunkedFile]:
        """Chunk multiple files and return within a total char budget."""
        chunked: list[ChunkedFile] = []
        total = 0
        for path in file_paths:
            cf = self.chunk_file(path)
            file_size = sum(len(c.content) for c in cf.chunks) + len(cf.header)
            if total + file_size > max_total_chars:
                # Include only relevant chunks
                relevant = cf.get_relevant_chunks(task, max_chars=max_total_chars - total)
                cf.chunks = relevant
                chunked.append(cf)
                break
            chunked.append(cf)
            total += file_size
        return chunked

    # -- Python chunking (AST-based) ----------------------------------------

    def _chunk_python(
        self,
        path: str,
        content: str,
        lines: list[str],
        total: int,
    ) -> ChunkedFile:
        result = ChunkedFile(path=path, total_lines=total)
        try:
            tree = ast.parse(content, filename=path)
        except SyntaxError:
            return self._chunk_generic(path, content, lines, total, _DEFAULT_CHUNK_SIZE)

        # Extract header (imports and module-level assignments)
        header_end = 0
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign)):
                header_end = max(header_end, getattr(node, "end_lineno", node.lineno))
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                # Module docstring
                header_end = max(header_end, getattr(node, "end_lineno", node.lineno))
            else:
                break

        if header_end > 0:
            result.header = "".join(lines[:header_end])

        # Chunk by top-level classes and functions
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                start = node.lineno
                end = getattr(node, "end_lineno", start + 10)
                result.chunks.append(Chunk(
                    file_path=path,
                    start_line=start,
                    end_line=end,
                    content="".join(lines[start - 1:end]),
                    chunk_type="class",
                    name=node.name,
                ))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = node.lineno
                end = getattr(node, "end_lineno", start + 10)
                result.chunks.append(Chunk(
                    file_path=path,
                    start_line=start,
                    end_line=end,
                    content="".join(lines[start - 1:end]),
                    chunk_type="function",
                    name=node.name,
                ))

        # If no chunks extracted (flat script), use generic chunking
        if not result.chunks:
            return self._chunk_generic(path, content, lines, total, _DEFAULT_CHUNK_SIZE)

        return result

    # -- JS/TS chunking (regex-based) ----------------------------------------

    def _chunk_js_ts(
        self,
        path: str,
        content: str,
        lines: list[str],
        total: int,
        chunk_size: int,
    ) -> ChunkedFile:
        result = ChunkedFile(path=path, total_lines=total)

        # Extract header (imports)
        header_lines: list[str] = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(("import ", "const ", "require(")) or not stripped or stripped.startswith("//"):
                header_lines.append(line)
            else:
                break
        result.header = "".join(header_lines)

        # Split by function/class/component boundaries
        boundary_re = re.compile(
            r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|class|const\s+\w+\s*=)\s",
            re.MULTILINE,
        )
        boundaries = [m.start() for m in boundary_re.finditer(content)]
        if not boundaries:
            return self._chunk_generic(path, content, lines, total, chunk_size)

        boundaries.append(len(content))
        for i in range(len(boundaries) - 1):
            chunk_content = content[boundaries[i]:boundaries[i + 1]].rstrip()
            if not chunk_content.strip():
                continue
            start_line = content[:boundaries[i]].count("\n") + 1
            end_line = start_line + chunk_content.count("\n")

            # Try to extract name
            name_match = re.match(
                r"(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|class)\s+(\w+)",
                chunk_content,
            )
            if not name_match:
                name_match = re.match(r"(?:export\s+)?const\s+(\w+)", chunk_content)

            result.chunks.append(Chunk(
                file_path=path,
                start_line=start_line,
                end_line=end_line,
                content=chunk_content,
                chunk_type="function" if "function" in chunk_content[:50] else "block",
                name=name_match.group(1) if name_match else "",
            ))
        return result

    # -- Markdown chunking (by headers) -------------------------------------

    def _chunk_markdown(
        self,
        path: str,
        content: str,
        lines: list[str],
        total: int,
    ) -> ChunkedFile:
        result = ChunkedFile(path=path, total_lines=total)
        sections: list[tuple[int, str, list[str]]] = []
        current_title = "intro"
        current_lines: list[str] = []
        current_start = 1

        for i, line in enumerate(lines):
            if line.startswith("#"):
                if current_lines:
                    sections.append((current_start, current_title, current_lines))
                current_title = line.strip().lstrip("#").strip()
                current_lines = [line]
                current_start = i + 1
            else:
                current_lines.append(line)

        if current_lines:
            sections.append((current_start, current_title, current_lines))

        for start, title, section_lines in sections:
            text = "".join(section_lines)
            if not text.strip():
                continue
            result.chunks.append(Chunk(
                file_path=path,
                start_line=start,
                end_line=start + len(section_lines) - 1,
                content=text,
                chunk_type="section",
                name=title,
            ))
        return result

    # -- Generic chunking (line-based with smart breaks) ---------------------

    def _chunk_generic(
        self,
        path: str,
        content: str,
        lines: list[str],
        total: int,
        chunk_size: int,
    ) -> ChunkedFile:
        result = ChunkedFile(path=path, total_lines=total)
        current_chunk: list[str] = []
        current_start = 1
        current_size = 0

        for i, line in enumerate(lines):
            current_chunk.append(line)
            current_size += len(line)

            # Split at blank lines or when size exceeds limit
            is_boundary = (
                not line.strip()
                or current_size >= chunk_size
            )
            if is_boundary and current_size >= _MIN_CHUNK_SIZE:
                text = "".join(current_chunk)
                if text.strip():
                    result.chunks.append(Chunk(
                        file_path=path,
                        start_line=current_start,
                        end_line=i + 1,
                        content=text,
                        chunk_type="block",
                    ))
                current_chunk = []
                current_start = i + 2
                current_size = 0

        # Remaining content
        if current_chunk:
            text = "".join(current_chunk)
            if text.strip():
                result.chunks.append(Chunk(
                    file_path=path,
                    start_line=current_start,
                    end_line=total,
                    content=text,
                    chunk_type="block",
                ))
        return result

    @staticmethod
    def _read(path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return ""


# -- Chunk relevance scoring ------------------------------------------------

def _score_chunks(chunks: list[Chunk], task: str) -> None:
    """Score chunks by relevance to the task."""
    if not task:
        for c in chunks:
            c.relevance = 0.5
        return

    keywords = set(re.findall(r"\b[a-z][a-z0-9_]+\b", task.lower()))
    stop = {"the", "a", "an", "is", "are", "and", "or", "for", "to", "in", "of", "with", "by"}
    keywords -= stop

    for chunk in chunks:
        score = 0.0
        content_lower = chunk.content.lower()

        # Keyword hits in content
        hits = sum(1 for kw in keywords if kw in content_lower)
        score += 0.4 * min(hits / max(len(keywords), 1), 1.0)

        # Keyword hits in name
        if chunk.name:
            name_lower = chunk.name.lower()
            name_hits = sum(1 for kw in keywords if kw in name_lower)
            score += 0.3 * min(name_hits, 1.0)

        # Boost classes and functions over generic blocks
        if chunk.chunk_type in ("class", "function"):
            score += 0.1
        elif chunk.chunk_type == "section":
            score += 0.05

        # Boost smaller chunks (more focused)
        if chunk.line_count < 50:
            score += 0.1
        elif chunk.line_count > 200:
            score -= 0.1

        chunk.relevance = max(0.0, min(1.0, score))


# -- Singleton ---------------------------------------------------------------

_instance: ContextChunker | None = None


def get_context_chunker() -> ContextChunker:
    global _instance
    if _instance is None:
        _instance = ContextChunker()
    return _instance
