"""
Working Memory — per-project persistent memory.

Stores summaries, dependency info, file embeddings, past reasoning for a
specific project. Lives in memory/projects/<project_id>/.

Backed by a SQLite database per project with tables for:
  - summaries (condensed agent reasoning)
  - file_context (file hashes, embeddings, AST info)
  - dependency_info (cached dependency graph data)
  - reasoning_chain (multi-step reasoning across tasks)
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generator

logger = logging.getLogger(__name__)

_PROJECTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory", "projects")


@dataclass
class Summary:
    id: int
    agent_name: str
    category: str
    content: str
    metadata: dict[str, Any]
    created_at: float


@dataclass
class FileContext:
    id: int
    file_path: str
    file_hash: str
    symbols: str
    ast_summary: str
    updated_at: float


@dataclass
class ReasoningStep:
    id: int
    chain_id: str
    step: int
    agent_name: str
    thought: str
    created_at: float


class WorkingMemory:
    """Per-project persistent memory backed by SQLite."""

    def __init__(self, project_id: str, base_dir: str | None = None) -> None:
        self.project_id = project_id
        base = base_dir or _PROJECTS_DIR
        self._project_dir = os.path.join(base, project_id)
        os.makedirs(self._project_dir, exist_ok=True)
        self._db_path = os.path.join(self._project_dir, "working_memory.sqlite")
        self._init_schema()

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS summaries (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_name  TEXT NOT NULL,
                    category    TEXT NOT NULL DEFAULT 'general',
                    content     TEXT NOT NULL,
                    metadata    TEXT NOT NULL DEFAULT '{}',
                    created_at  REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sum_agent ON summaries(agent_name);

                CREATE TABLE IF NOT EXISTS file_context (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path   TEXT NOT NULL UNIQUE,
                    file_hash   TEXT NOT NULL,
                    symbols     TEXT NOT NULL DEFAULT '[]',
                    ast_summary TEXT NOT NULL DEFAULT '',
                    updated_at  REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_fc_path ON file_context(file_path);
                CREATE INDEX IF NOT EXISTS idx_fc_hash ON file_context(file_hash);

                CREATE TABLE IF NOT EXISTS dependency_info (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    key         TEXT NOT NULL UNIQUE,
                    value       TEXT NOT NULL,
                    updated_at  REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reasoning_chain (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    chain_id    TEXT NOT NULL,
                    step        INTEGER NOT NULL,
                    agent_name  TEXT NOT NULL,
                    thought     TEXT NOT NULL,
                    created_at  REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_rc_chain ON reasoning_chain(chain_id);
            """)

    # -- Summaries -----------------------------------------------------------

    def store_summary(
        self,
        agent_name: str,
        content: str,
        category: str = "general",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO summaries (agent_name, category, content, metadata, created_at) VALUES (?,?,?,?,?)",
                (agent_name, category, content, json.dumps(metadata or {}), time.time()),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def recall_summaries(
        self,
        agent_name: str | None = None,
        category: str | None = None,
        limit: int = 20,
    ) -> list[Summary]:
        with self._connect() as conn:
            clauses: list[str] = []
            params: list[Any] = []
            if agent_name:
                clauses.append("agent_name = ?")
                params.append(agent_name)
            if category:
                clauses.append("category = ?")
                params.append(category)
            where = " AND ".join(clauses) if clauses else "1=1"
            params.append(limit)
            rows = conn.execute(
                f"SELECT * FROM summaries WHERE {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
            return [
                Summary(
                    id=r["id"], agent_name=r["agent_name"], category=r["category"],
                    content=r["content"], metadata=json.loads(r["metadata"]),
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    # -- File Context --------------------------------------------------------

    def upsert_file_context(
        self,
        file_path: str,
        file_hash: str,
        symbols: list[str] | None = None,
        ast_summary: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO file_context (file_path, file_hash, symbols, ast_summary, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(file_path) DO UPDATE SET
                       file_hash=excluded.file_hash,
                       symbols=excluded.symbols,
                       ast_summary=excluded.ast_summary,
                       updated_at=excluded.updated_at""",
                (file_path, file_hash, json.dumps(symbols or []), ast_summary, time.time()),
            )

    def get_file_context(self, file_path: str) -> FileContext | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM file_context WHERE file_path = ?", (file_path,)
            ).fetchone()
            if not row:
                return None
            return FileContext(
                id=row["id"], file_path=row["file_path"],
                file_hash=row["file_hash"], symbols=row["symbols"],
                ast_summary=row["ast_summary"], updated_at=row["updated_at"],
            )

    def get_all_file_contexts(self) -> list[FileContext]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM file_context ORDER BY file_path").fetchall()
            return [
                FileContext(
                    id=r["id"], file_path=r["file_path"],
                    file_hash=r["file_hash"], symbols=r["symbols"],
                    ast_summary=r["ast_summary"], updated_at=r["updated_at"],
                )
                for r in rows
            ]

    # -- Dependency Info (key-value store) -----------------------------------

    def set_dep_info(self, key: str, value: Any) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO dependency_info (key, value, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (key, json.dumps(value), time.time()),
            )

    def get_dep_info(self, key: str) -> Any:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM dependency_info WHERE key = ?", (key,)).fetchone()
            return json.loads(row["value"]) if row else None

    # -- Reasoning Chain -----------------------------------------------------

    def add_reasoning_step(
        self,
        chain_id: str,
        step: int,
        agent_name: str,
        thought: str,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO reasoning_chain (chain_id, step, agent_name, thought, created_at) VALUES (?,?,?,?,?)",
                (chain_id, step, agent_name, thought, time.time()),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def get_reasoning_chain(self, chain_id: str) -> list[ReasoningStep]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM reasoning_chain WHERE chain_id = ? ORDER BY step ASC",
                (chain_id,),
            ).fetchall()
            return [
                ReasoningStep(
                    id=r["id"], chain_id=r["chain_id"], step=r["step"],
                    agent_name=r["agent_name"], thought=r["thought"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    # -- Prompt helpers ------------------------------------------------------

    def to_prompt_section(self, agent_name: str | None = None) -> str:
        """Format working memory as a prompt section."""
        parts: list[str] = []
        summaries = self.recall_summaries(agent_name=agent_name, limit=10)
        if summaries:
            parts.append("## Project Memory (Working Memory)")
            for s in summaries:
                parts.append(f"- [{s.agent_name}/{s.category}] {s.content[:400]}")
        files = self.get_all_file_contexts()
        if files:
            parts.append(f"\n**Indexed files**: {len(files)}")
        return "\n".join(parts)

    @property
    def project_dir(self) -> str:
        return self._project_dir


# -- Factory ----------------------------------------------------------------

_instances: dict[str, WorkingMemory] = {}


def get_working_memory(project_id: str = "default") -> WorkingMemory:
    if project_id not in _instances:
        _instances[project_id] = WorkingMemory(project_id)
    return _instances[project_id]
