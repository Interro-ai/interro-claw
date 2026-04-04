"""
Long-Term Memory — cross-project global memory.

Stores reusable patterns, coding style preferences, optimization strategies,
and lessons learned. Persists in memory/global/longterm.sqlite.

All agents share this store. Entries are tagged by domain and scored
by usefulness so the most valuable knowledge surfaces first.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Generator

logger = logging.getLogger(__name__)

_GLOBAL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory", "global")
_DB_PATH = os.path.join(_GLOBAL_DIR, "longterm.sqlite")


@dataclass
class LTMEntry:
    id: int
    domain: str
    pattern_type: str
    content: str
    source_agent: str
    usefulness: float
    metadata: dict[str, Any]
    created_at: float
    last_used_at: float


class LongTermMemory:
    """Cross-project global memory backed by SQLite."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _DB_PATH
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
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
                CREATE TABLE IF NOT EXISTS patterns (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain       TEXT NOT NULL,
                    pattern_type TEXT NOT NULL,
                    content      TEXT NOT NULL,
                    source_agent TEXT NOT NULL DEFAULT '',
                    usefulness   REAL NOT NULL DEFAULT 0.5,
                    metadata     TEXT NOT NULL DEFAULT '{}',
                    created_at   REAL NOT NULL,
                    last_used_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_p_domain ON patterns(domain);
                CREATE INDEX IF NOT EXISTS idx_p_type ON patterns(pattern_type);
                CREATE INDEX IF NOT EXISTS idx_p_useful ON patterns(usefulness DESC);

                CREATE TABLE IF NOT EXISTS coding_style (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    language    TEXT NOT NULL,
                    rule        TEXT NOT NULL,
                    example     TEXT NOT NULL DEFAULT '',
                    confidence  REAL NOT NULL DEFAULT 0.5,
                    created_at  REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_cs_lang ON coding_style(language);

                CREATE TABLE IF NOT EXISTS optimization_strategies (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    category    TEXT NOT NULL,
                    strategy    TEXT NOT NULL,
                    impact      TEXT NOT NULL DEFAULT 'medium',
                    source_agent TEXT NOT NULL DEFAULT '',
                    usefulness  REAL NOT NULL DEFAULT 0.5,
                    created_at  REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_os_cat ON optimization_strategies(category);
            """)

    # -- Patterns ------------------------------------------------------------

    def store_pattern(
        self,
        domain: str,
        pattern_type: str,
        content: str,
        source_agent: str = "",
        usefulness: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO patterns (domain, pattern_type, content, source_agent,
                   usefulness, metadata, created_at, last_used_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (domain, pattern_type, content, source_agent,
                 usefulness, json.dumps(metadata or {}), now, now),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def recall_patterns(
        self,
        domain: str | None = None,
        pattern_type: str | None = None,
        min_usefulness: float = 0.0,
        limit: int = 20,
    ) -> list[LTMEntry]:
        with self._connect() as conn:
            clauses = ["usefulness >= ?"]
            params: list[Any] = [min_usefulness]
            if domain:
                clauses.append("domain = ?")
                params.append(domain)
            if pattern_type:
                clauses.append("pattern_type = ?")
                params.append(pattern_type)
            where = " AND ".join(clauses)
            params.append(limit)
            rows = conn.execute(
                f"SELECT * FROM patterns WHERE {where} ORDER BY usefulness DESC, last_used_at DESC LIMIT ?",
                params,
            ).fetchall()
            return [self._row_to_entry(r) for r in rows]

    def boost_usefulness(self, entry_id: int, delta: float = 0.1) -> None:
        """Increase usefulness score when a pattern is used successfully."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE patterns SET usefulness = MIN(1.0, usefulness + ?), last_used_at = ? WHERE id = ?",
                (delta, time.time(), entry_id),
            )

    def decay_unused(self, older_than_days: int = 90, decay: float = 0.05) -> int:
        """Reduce usefulness of patterns not used recently."""
        cutoff = time.time() - (older_than_days * 86400)
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE patterns SET usefulness = MAX(0.0, usefulness - ?) WHERE last_used_at < ?",
                (decay, cutoff),
            )
            return cur.rowcount

    # -- Coding Style --------------------------------------------------------

    def store_style_rule(
        self,
        language: str,
        rule: str,
        example: str = "",
        confidence: float = 0.5,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO coding_style (language, rule, example, confidence, created_at) VALUES (?,?,?,?,?)",
                (language, rule, example, confidence, time.time()),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def get_style_rules(self, language: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if language:
                rows = conn.execute(
                    "SELECT * FROM coding_style WHERE language = ? ORDER BY confidence DESC LIMIT ?",
                    (language, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM coding_style ORDER BY confidence DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    # -- Optimization Strategies ---------------------------------------------

    def store_strategy(
        self,
        category: str,
        strategy: str,
        impact: str = "medium",
        source_agent: str = "",
        usefulness: float = 0.5,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO optimization_strategies
                   (category, strategy, impact, source_agent, usefulness, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (category, strategy, impact, source_agent, usefulness, time.time()),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def get_strategies(self, category: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM optimization_strategies WHERE category = ? ORDER BY usefulness DESC LIMIT ?",
                    (category, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM optimization_strategies ORDER BY usefulness DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    # -- Prompt helpers ------------------------------------------------------

    def to_prompt_section(self, agent_name: str = "", domain: str = "") -> str:
        """Format LTM as a prompt section for injection."""
        parts: list[str] = []
        patterns = self.recall_patterns(domain=domain or None, min_usefulness=0.3, limit=8)
        if patterns:
            parts.append("## Long-Term Memory (cross-project knowledge)")
            for p in patterns:
                parts.append(f"- [{p.domain}/{p.pattern_type}] (useful={p.usefulness:.2f}) {p.content[:300]}")
        return "\n".join(parts)

    def get_stats(self) -> dict[str, int]:
        with self._connect() as conn:
            patterns = conn.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]
            styles = conn.execute("SELECT COUNT(*) FROM coding_style").fetchone()[0]
            strategies = conn.execute("SELECT COUNT(*) FROM optimization_strategies").fetchone()[0]
            return {"patterns": patterns, "style_rules": styles, "strategies": strategies}

    @staticmethod
    def _row_to_entry(r: sqlite3.Row) -> LTMEntry:
        return LTMEntry(
            id=r["id"], domain=r["domain"], pattern_type=r["pattern_type"],
            content=r["content"], source_agent=r["source_agent"],
            usefulness=r["usefulness"], metadata=json.loads(r["metadata"]),
            created_at=r["created_at"], last_used_at=r["last_used_at"],
        )


# -- Singleton ---------------------------------------------------------------

_instance: LongTermMemory | None = None


def get_long_term_memory() -> LongTermMemory:
    global _instance
    if _instance is None:
        _instance = LongTermMemory()
    return _instance
