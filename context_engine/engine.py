"""
Unified Context Engine

Determines the *minimal* context needed for each agent, then assembles it:
1. Selective file injection (only relevant files)
2. Summarization of large files (key symbols + structure)
3. Chunking (logical boundaries — functions, classes)
4. File-diff injection (show only changed sections)
5. Token overflow prevention (hard budget per agent call)

Combines file_selector, context_chunker, and graph_engine into a single
interface that agents call via context_engine.build_context(task, agent_name).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import interro_claw.config as config

logger = logging.getLogger(__name__)


@dataclass
class ContextBlock:
    """A single block of context for an agent."""
    source: str       # "file", "summary", "diff", "memory", "graph"
    path: str         # file path or memory key
    content: str
    relevance: float  # 0.0 - 1.0
    char_count: int = 0

    def __post_init__(self) -> None:
        self.char_count = len(self.content)


@dataclass
class AgentContext:
    """Assembled context for a single agent call."""
    agent_name: str
    task: str
    blocks: list[ContextBlock] = field(default_factory=list)
    total_chars: int = 0
    budget: int = 0

    def add(self, block: ContextBlock) -> bool:
        """Add a block if it fits within budget."""
        if self.total_chars + block.char_count > self.budget:
            return False
        self.blocks.append(block)
        self.total_chars += block.char_count
        return True

    def to_prompt(self) -> str:
        """Render all blocks as a prompt string."""
        if not self.blocks:
            return ""
        parts = ["## Context (auto-assembled)\n"]
        for b in self.blocks:
            if b.source == "file":
                parts.append(f"### File: {b.path} (rel={b.relevance:.2f})\n```\n{b.content}\n```\n")
            elif b.source == "summary":
                parts.append(f"### Summary: {b.path}\n{b.content}\n")
            elif b.source == "diff":
                parts.append(f"### Diff: {b.path}\n```diff\n{b.content}\n```\n")
            elif b.source == "memory":
                parts.append(f"### Memory: {b.path}\n{b.content}\n")
            elif b.source == "graph":
                parts.append(f"### Graph\n{b.content}\n")
            else:
                parts.append(f"### {b.source}: {b.path}\n{b.content}\n")
        return "\n".join(parts)


class UnifiedContextEngine:
    """Assembles minimal context for agent calls, preventing token overflow."""

    def __init__(self, root_path: str | None = None) -> None:
        self._root = root_path or os.path.dirname(os.path.dirname(__file__))

    def build_context(
        self,
        task: str,
        agent_name: str,
        project_id: str = "default",
        budget: int | None = None,
        include_graph: bool = True,
        include_files: bool = True,
        include_memory: bool = True,
        diff_base: str | None = None,
    ) -> AgentContext:
        """Build the optimal context for an agent's task."""
        ctx = AgentContext(
            agent_name=agent_name,
            task=task,
            budget=budget or config.MAX_CONTEXT_CHARS,
        )

        # 1. Graph summary (always compact)
        if include_graph:
            self._add_graph_context(ctx, project_id)

        # 2. Memory context
        if include_memory:
            self._add_memory_context(ctx, agent_name, project_id)

        # 3. Relevant files (selective + chunked)
        if include_files:
            self._add_file_context(ctx, task, project_id)

        # 4. Diff injection if base specified
        if diff_base:
            self._add_diff_context(ctx, diff_base)

        logger.debug(
            "Context for %s: %d blocks, %d/%d chars",
            agent_name, len(ctx.blocks), ctx.total_chars, ctx.budget,
        )
        return ctx

    def _add_graph_context(self, ctx: AgentContext, project_id: str) -> None:
        try:
            from graph_engine import get_project_graph_engine
            engine = get_project_graph_engine()
            graph = engine.query(self._root, project_id)
            text = graph.to_prompt_section()
            if text:
                ctx.add(ContextBlock(source="graph", path="project", content=text, relevance=0.9))
        except Exception as e:
            logger.debug("Graph context skipped: %s", e)

    def _add_memory_context(self, ctx: AgentContext, agent_name: str, project_id: str) -> None:
        try:
            from interro_claw.memory.working import get_working_memory
            wm = get_working_memory(project_id)
            text = wm.to_prompt_section(agent_name=agent_name)
            if text:
                ctx.add(ContextBlock(source="memory", path="working", content=text, relevance=0.8))
        except Exception as e:
            logger.debug("Working memory context skipped: %s", e)

        try:
            from interro_claw.memory.long_term import get_long_term_memory
            ltm = get_long_term_memory()
            text = ltm.to_prompt_section(agent_name=agent_name)
            if text:
                ctx.add(ContextBlock(source="memory", path="longterm", content=text, relevance=0.6))
        except Exception as e:
            logger.debug("LTM context skipped: %s", e)

    def _add_file_context(self, ctx: AgentContext, task: str, project_id: str) -> None:
        try:
            from interro_claw.file_selector import get_file_selector
            from interro_claw.context_chunker import get_context_chunker

            selector = get_file_selector(self._root)
            chunker = get_context_chunker()

            # Get dep graph if available
            dep_graph = None
            try:
                from interro_claw.dep_graph import get_dep_graph_engine
                dep_graph = get_dep_graph_engine().analyze(self._root, project_id)
            except Exception:
                pass

            selection = selector.select(
                task=task,
                dep_graph=dep_graph,
                max_files=config.MAX_SELECTED_FILES,
            )

            remaining = ctx.budget - ctx.total_chars
            for sf in selection.files:
                if remaining <= 0:
                    break
                if len(sf.content) > config.MAX_CHUNK_SIZE:
                    # Chunk large files
                    chunked = chunker.chunk_file(sf.path)
                    text = chunked.to_prompt_section(task=task, max_chars=min(remaining, config.MAX_CHUNK_SIZE))
                else:
                    text = sf.content

                if text:
                    added = ctx.add(ContextBlock(
                        source="file", path=sf.path, content=text, relevance=sf.relevance,
                    ))
                    if added:
                        remaining -= len(text)
        except Exception as e:
            logger.debug("File context skipped: %s", e)

    def _add_diff_context(self, ctx: AgentContext, diff_base: str) -> None:
        """Inject git diff from a base ref."""
        import subprocess
        try:
            result = subprocess.run(
                ["git", "diff", diff_base, "--stat", "--no-color"],
                capture_output=True, text=True, cwd=self._root,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                ctx.add(ContextBlock(
                    source="diff", path=f"diff vs {diff_base}",
                    content=result.stdout[:3000], relevance=0.85,
                ))
        except Exception as e:
            logger.debug("Diff context skipped: %s", e)


# -- Singleton ---------------------------------------------------------------

_instance: UnifiedContextEngine | None = None


def get_context_engine(root_path: str | None = None) -> UnifiedContextEngine:
    global _instance
    if _instance is None:
        _instance = UnifiedContextEngine(root_path)
    return _instance
