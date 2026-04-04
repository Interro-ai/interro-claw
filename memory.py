"""
SQLite-backed persistent memory with:
  1. AgentMemory    – per-agent reasoning, decisions, and learnings
  2. SharedKnowledge – cross-agent facts any agent can publish/query
  3. SessionHistory  – full task->response log for context continuity
  4. ResponseCache   – content-addressable LLM response cache
  5. TaskMemory      – per-task step/diff/reasoning logs
  6. VectorStore     – embedding-based semantic similarity search

Multi-session continuity: sessions track completion state and can be resumed.
Per-project scoping: all tables have optional project_id for isolation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import sqlite3
import struct
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generator

import interro_claw.config as config

logger = logging.getLogger(__name__)

_DEFAULT_DB = os.path.join(os.path.dirname(__file__), "memory.db")


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class MemoryEntry:
    id: int
    agent_name: str
    category: str
    content: str
    metadata: dict[str, Any]
    project_id: str
    created_at: float


@dataclass
class KnowledgeFact:
    id: int
    publisher: str
    topic: str
    fact: str
    confidence: float
    metadata: dict[str, Any]
    project_id: str
    created_at: float


@dataclass
class SessionEntry:
    id: int
    session_id: str
    task_id: str
    agent_name: str
    task_description: str
    response: str
    status: str
    elapsed_ms: int
    project_id: str
    created_at: float


@dataclass
class TaskMemoryEntry:
    id: int
    session_id: str
    task_id: str
    step: int
    agent_name: str
    action: str  # "reasoning" | "diff" | "reflection" | "tool_call"
    content: str
    metadata: dict[str, Any]
    project_id: str
    created_at: float


@dataclass
class ProjectRecord:
    id: str
    name: str
    description: str
    created_at: float
    last_accessed_at: float


@dataclass
class VectorEntry:
    id: int
    source_table: str
    source_id: int
    content_hash: str
    embedding: list[float]
    created_at: float


@dataclass
class SimilarityResult:
    source_table: str
    source_id: int
    content: str
    score: float


# ── Vector math (no numpy required, pure Python) ─────────────────────────────

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _pack_embedding(vec: list[float]) -> bytes:
    """Pack a float list into compact binary (little-endian float32)."""
    return struct.pack(f"<{len(vec)}f", *vec)


def _unpack_embedding(data: bytes) -> list[float]:
    """Unpack binary back to float list."""
    n = len(data) // 4
    return list(struct.unpack(f"<{n}f", data))


# ── Simple text embedding (TF-IDF-like hash vectors) ─────────────────────────

_EMBED_DIM = 128


def _text_to_embedding(text: str) -> list[float]:
    """
    Generate a simple deterministic embedding from text.
    Uses character n-gram hashing for a lightweight, dependency-free approach.
    For production, replace with a real embedding model call.
    """
    vec = [0.0] * _EMBED_DIM
    text_lower = text.lower()
    # Character trigram hashing
    for i in range(len(text_lower) - 2):
        trigram = text_lower[i:i + 3]
        h = hash(trigram) % _EMBED_DIM
        vec[h] += 1.0
    # Normalize
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


# ── Thread-safe connection pool ───────────────────────────────────────────────

class MemoryStore:
    """
    SQLite memory store with vector search, per-project scoping,
    task memory, and multi-session continuity.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _DEFAULT_DB
        self._local = threading.local()
        with self._connect() as conn:
            self._init_schema(conn)

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS agent_memory (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name  TEXT    NOT NULL,
                category    TEXT    NOT NULL DEFAULT 'reasoning',
                content     TEXT    NOT NULL,
                metadata    TEXT    NOT NULL DEFAULT '{}',
                project_id  TEXT    NOT NULL DEFAULT 'default',
                created_at  REAL   NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_am_agent ON agent_memory(agent_name);
            CREATE INDEX IF NOT EXISTS idx_am_category ON agent_memory(category);
            CREATE INDEX IF NOT EXISTS idx_am_project ON agent_memory(project_id);

            CREATE TABLE IF NOT EXISTS shared_knowledge (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                publisher   TEXT    NOT NULL,
                topic       TEXT    NOT NULL,
                fact        TEXT    NOT NULL,
                confidence  REAL   NOT NULL DEFAULT 1.0,
                metadata    TEXT    NOT NULL DEFAULT '{}',
                project_id  TEXT    NOT NULL DEFAULT 'default',
                created_at  REAL   NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sk_topic ON shared_knowledge(topic);
            CREATE INDEX IF NOT EXISTS idx_sk_publisher ON shared_knowledge(publisher);
            CREATE INDEX IF NOT EXISTS idx_sk_project ON shared_knowledge(project_id);

            CREATE TABLE IF NOT EXISTS session_history (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id       TEXT    NOT NULL,
                task_id          TEXT    NOT NULL,
                agent_name       TEXT    NOT NULL,
                task_description TEXT    NOT NULL,
                response         TEXT    NOT NULL DEFAULT '',
                status           TEXT    NOT NULL DEFAULT 'pending',
                elapsed_ms       INTEGER NOT NULL DEFAULT 0,
                project_id       TEXT    NOT NULL DEFAULT 'default',
                goal             TEXT    NOT NULL DEFAULT '',
                created_at       REAL    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sh_session ON session_history(session_id);
            CREATE INDEX IF NOT EXISTS idx_sh_agent ON session_history(agent_name);
            CREATE INDEX IF NOT EXISTS idx_sh_project ON session_history(project_id);
            CREATE INDEX IF NOT EXISTS idx_sh_status ON session_history(status);

            CREATE TABLE IF NOT EXISTS response_cache (
                cache_key   TEXT PRIMARY KEY,
                response    TEXT    NOT NULL,
                hit_count   INTEGER NOT NULL DEFAULT 0,
                created_at  REAL    NOT NULL,
                expires_at  REAL    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_memory (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT    NOT NULL,
                task_id     TEXT    NOT NULL,
                step        INTEGER NOT NULL DEFAULT 0,
                agent_name  TEXT    NOT NULL,
                action      TEXT    NOT NULL DEFAULT 'reasoning',
                content     TEXT    NOT NULL,
                metadata    TEXT    NOT NULL DEFAULT '{}',
                project_id  TEXT    NOT NULL DEFAULT 'default',
                created_at  REAL    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tm_session ON task_memory(session_id);
            CREATE INDEX IF NOT EXISTS idx_tm_task ON task_memory(task_id);

            CREATE TABLE IF NOT EXISTS vector_store (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                source_table TEXT    NOT NULL,
                source_id    INTEGER NOT NULL,
                content_hash TEXT    NOT NULL,
                embedding    BLOB    NOT NULL,
                created_at   REAL    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_vs_source ON vector_store(source_table, source_id);
            CREATE INDEX IF NOT EXISTS idx_vs_hash ON vector_store(content_hash);

            CREATE TABLE IF NOT EXISTS projects (
                id               TEXT PRIMARY KEY,
                name             TEXT NOT NULL UNIQUE,
                description      TEXT NOT NULL DEFAULT '',
                created_at       REAL NOT NULL,
                last_accessed_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_proj_name ON projects(name);
        """)

    # ── Agent Memory ──────────────────────────────────────────────────────

    def store_agent_memory(
        self,
        agent_name: str,
        content: str,
        category: str = "reasoning",
        metadata: dict[str, Any] | None = None,
        project_id: str = "default",
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO agent_memory (agent_name, category, content, metadata, project_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (agent_name, category, content, json.dumps(metadata or {}), project_id, time.time()),
            )
            row_id = cur.lastrowid
            # Store vector embedding
            self._store_vector(conn, "agent_memory", row_id, content)
            return row_id  # type: ignore[return-value]

    def recall_agent_memory(
        self,
        agent_name: str,
        category: str | None = None,
        limit: int = 20,
        project_id: str = "default",
    ) -> list[MemoryEntry]:
        with self._connect() as conn:
            clauses = ["agent_name = ?", "project_id = ?"]
            params: list[Any] = [agent_name, project_id]
            if category:
                clauses.append("category = ?")
                params.append(category)
            where = " AND ".join(clauses)
            params.append(limit)
            rows = conn.execute(
                f"SELECT * FROM agent_memory WHERE {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
            return [
                MemoryEntry(
                    id=r["id"], agent_name=r["agent_name"], category=r["category"],
                    content=r["content"], metadata=json.loads(r["metadata"]),
                    project_id=r["project_id"], created_at=r["created_at"],
                )
                for r in rows
            ]

    # ── Shared Knowledge ──────────────────────────────────────────────────

    def publish_knowledge(
        self,
        publisher: str,
        topic: str,
        fact: str,
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
        project_id: str = "default",
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO shared_knowledge (publisher, topic, fact, confidence, metadata, project_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (publisher, topic, fact, confidence, json.dumps(metadata or {}), project_id, time.time()),
            )
            row_id = cur.lastrowid
            self._store_vector(conn, "shared_knowledge", row_id, fact)
            return row_id  # type: ignore[return-value]

    def query_knowledge(
        self,
        topic: str | None = None,
        publisher: str | None = None,
        min_confidence: float = 0.0,
        limit: int = 20,
        project_id: str = "default",
    ) -> list[KnowledgeFact]:
        with self._connect() as conn:
            clauses = ["confidence >= ?", "project_id = ?"]
            params: list[Any] = [min_confidence, project_id]
            if topic:
                clauses.append("topic LIKE ?")
                params.append(f"%{topic}%")
            if publisher:
                clauses.append("publisher = ?")
                params.append(publisher)
            where = " AND ".join(clauses)
            params.append(limit)
            rows = conn.execute(
                f"""SELECT * FROM shared_knowledge
                    WHERE {where}
                    ORDER BY confidence DESC, created_at DESC LIMIT ?""",
                params,
            ).fetchall()
            return [
                KnowledgeFact(
                    id=r["id"], publisher=r["publisher"], topic=r["topic"],
                    fact=r["fact"], confidence=r["confidence"],
                    metadata=json.loads(r["metadata"]),
                    project_id=r["project_id"], created_at=r["created_at"],
                )
                for r in rows
            ]

    # ── Session History ───────────────────────────────────────────────────

    def log_session(
        self,
        session_id: str,
        task_id: str,
        agent_name: str,
        task_description: str,
        response: str = "",
        status: str = "pending",
        elapsed_ms: int = 0,
        project_id: str = "default",
        goal: str = "",
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO session_history
                   (session_id, task_id, agent_name, task_description, response, status, elapsed_ms, project_id, goal, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, task_id, agent_name, task_description, response, status, elapsed_ms, project_id, goal, time.time()),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def update_session_entry(
        self,
        entry_id: int,
        response: str,
        status: str,
        elapsed_ms: int,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE session_history SET response = ?, status = ?, elapsed_ms = ? WHERE id = ?",
                (response, status, elapsed_ms, entry_id),
            )

    def get_session_history(
        self,
        session_id: str,
        agent_name: str | None = None,
        limit: int = 50,
    ) -> list[SessionEntry]:
        with self._connect() as conn:
            clauses = ["session_id = ?"]
            params: list[Any] = [session_id]
            if agent_name:
                clauses.append("agent_name = ?")
                params.append(agent_name)
            where = " AND ".join(clauses)
            params.append(limit)
            rows = conn.execute(
                f"SELECT * FROM session_history WHERE {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
            return [
                SessionEntry(
                    id=r["id"], session_id=r["session_id"], task_id=r["task_id"],
                    agent_name=r["agent_name"], task_description=r["task_description"],
                    response=r["response"], status=r["status"], elapsed_ms=r["elapsed_ms"],
                    project_id=r["project_id"], created_at=r["created_at"],
                )
                for r in rows
            ]

    def get_recent_sessions(self, limit: int = 50) -> list[SessionEntry]:
        """Get recent session entries across all sessions."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM session_history ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                SessionEntry(
                    id=r["id"], session_id=r["session_id"], task_id=r["task_id"],
                    agent_name=r["agent_name"], task_description=r["task_description"],
                    response=r["response"], status=r["status"], elapsed_ms=r["elapsed_ms"],
                    project_id=r["project_id"], created_at=r["created_at"],
                )
                for r in rows
            ]

    # ── Multi-session continuity ──────────────────────────────────────────

    def find_incomplete_session(self, project_id: str = "default") -> str | None:
        """Find the most recent session that has pending/running tasks."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT session_id FROM session_history
                   WHERE project_id = ? AND status IN ('pending', 'running')
                   ORDER BY created_at DESC LIMIT 1""",
                (project_id,),
            ).fetchone()
            return row["session_id"] if row else None

    def get_session_pending_tasks(self, session_id: str) -> list[SessionEntry]:
        """Get tasks from a session that haven't completed yet."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM session_history
                   WHERE session_id = ? AND status IN ('pending', 'running')
                   ORDER BY created_at ASC""",
                (session_id,),
            ).fetchall()
            return [
                SessionEntry(
                    id=r["id"], session_id=r["session_id"], task_id=r["task_id"],
                    agent_name=r["agent_name"], task_description=r["task_description"],
                    response=r["response"], status=r["status"], elapsed_ms=r["elapsed_ms"],
                    project_id=r["project_id"], created_at=r["created_at"],
                )
                for r in rows
            ]

    def get_session_goal(self, session_id: str) -> str:
        """Retrieve the original goal of a session."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT goal FROM session_history WHERE session_id = ? AND goal != '' LIMIT 1",
                (session_id,),
            ).fetchone()
            return row["goal"] if row else ""

    # ── Task Memory ───────────────────────────────────────────────────────

    def store_task_memory(
        self,
        session_id: str,
        task_id: str,
        agent_name: str,
        action: str,
        content: str,
        step: int = 0,
        metadata: dict[str, Any] | None = None,
        project_id: str = "default",
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO task_memory
                   (session_id, task_id, step, agent_name, action, content, metadata, project_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, task_id, step, agent_name, action, content,
                 json.dumps(metadata or {}), project_id, time.time()),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def recall_task_memory(
        self,
        task_id: str,
        session_id: str | None = None,
        action: str | None = None,
        limit: int = 50,
    ) -> list[TaskMemoryEntry]:
        with self._connect() as conn:
            clauses = ["task_id = ?"]
            params: list[Any] = [task_id]
            if session_id:
                clauses.append("session_id = ?")
                params.append(session_id)
            if action:
                clauses.append("action = ?")
                params.append(action)
            where = " AND ".join(clauses)
            params.append(limit)
            rows = conn.execute(
                f"SELECT * FROM task_memory WHERE {where} ORDER BY step ASC, created_at ASC LIMIT ?",
                params,
            ).fetchall()
            return [
                TaskMemoryEntry(
                    id=r["id"], session_id=r["session_id"], task_id=r["task_id"],
                    step=r["step"], agent_name=r["agent_name"], action=r["action"],
                    content=r["content"], metadata=json.loads(r["metadata"]),
                    project_id=r["project_id"], created_at=r["created_at"],
                )
                for r in rows
            ]

    # ── Vector Store (semantic search) ────────────────────────────────────

    def _store_vector(
        self,
        conn: sqlite3.Connection,
        source_table: str,
        source_id: int,
        content: str,
    ) -> None:
        """Store an embedding for a row. Skips duplicates."""
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]
        existing = conn.execute(
            "SELECT id FROM vector_store WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        if existing:
            return
        embedding = _text_to_embedding(content)
        conn.execute(
            """INSERT INTO vector_store (source_table, source_id, content_hash, embedding, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (source_table, source_id, content_hash, _pack_embedding(embedding), time.time()),
        )

    def semantic_search(
        self,
        query: str,
        source_table: str | None = None,
        limit: int = 10,
        min_score: float = 0.1,
    ) -> list[SimilarityResult]:
        """
        Find semantically similar entries using cosine similarity.
        Returns matches sorted by similarity score descending.
        """
        query_vec = _text_to_embedding(query)
        with self._connect() as conn:
            clause = "WHERE source_table = ?" if source_table else ""
            params: tuple = (source_table,) if source_table else ()
            rows = conn.execute(
                f"SELECT * FROM vector_store {clause}",
                params,
            ).fetchall()

        results: list[SimilarityResult] = []
        for row in rows:
            stored_vec = _unpack_embedding(row["embedding"])
            score = _cosine_similarity(query_vec, stored_vec)
            if score >= min_score:
                # Fetch the source content
                content = self._get_source_content(row["source_table"], row["source_id"])
                if content:
                    results.append(SimilarityResult(
                        source_table=row["source_table"],
                        source_id=row["source_id"],
                        content=content,
                        score=score,
                    ))
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def _get_source_content(self, table: str, row_id: int) -> str:
        """Retrieve the text content of a source row."""
        col_map = {
            "agent_memory": "content",
            "shared_knowledge": "fact",
            "task_memory": "content",
        }
        col = col_map.get(table)
        if not col:
            return ""
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {col} FROM {table} WHERE id = ?",
                (row_id,),
            ).fetchone()
            return row[col] if row else ""

    # ── Response Cache ────────────────────────────────────────────────────

    def cache_get(self, system_prompt: str, user_message: str) -> str | None:
        key = self._cache_key(system_prompt, user_message)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT response, expires_at FROM response_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return None
            if row["expires_at"] < time.time():
                conn.execute("DELETE FROM response_cache WHERE cache_key = ?", (key,))
                return None
            conn.execute(
                "UPDATE response_cache SET hit_count = hit_count + 1 WHERE cache_key = ?",
                (key,),
            )
            return row["response"]

    def cache_get_normalized(self, task_fingerprint: str) -> str | None:
        """Look up cache by a task-only fingerprint (ignores volatile context).

        This catches cases where the same task is asked with slightly different
        surrounding context (different memory, different file content), reducing
        redundant LLM calls significantly.
        """
        key = f"tfp:{task_fingerprint}"
        with self._connect() as conn:
            row = conn.execute(
                "SELECT response, expires_at FROM response_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return None
            if row["expires_at"] < time.time():
                conn.execute("DELETE FROM response_cache WHERE cache_key = ?", (key,))
                return None
            conn.execute(
                "UPDATE response_cache SET hit_count = hit_count + 1 WHERE cache_key = ?",
                (key,),
            )
            logger.info("Normalized cache HIT for fingerprint %s", task_fingerprint[:16])
            return row["response"]

    def cache_put(
        self,
        system_prompt: str,
        user_message: str,
        response: str,
        ttl_seconds: int = 3600,
    ) -> None:
        key = self._cache_key(system_prompt, user_message)
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO response_cache (cache_key, response, hit_count, created_at, expires_at)
                   VALUES (?, ?, 0, ?, ?)""",
                (key, response, now, now + ttl_seconds),
            )

    def cache_put_normalized(
        self,
        task_fingerprint: str,
        response: str,
        ttl_seconds: int = 7200,
    ) -> None:
        """Store a response keyed by task fingerprint only.

        Uses a longer TTL (2h default) since task-level answers are more stable
        than context-sensitive ones.
        """
        key = f"tfp:{task_fingerprint}"
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO response_cache (cache_key, response, hit_count, created_at, expires_at)
                   VALUES (?, ?, 0, ?, ?)""",
                (key, response, now, now + ttl_seconds),
            )

    def cache_invalidate_for_project(self, project_id: str) -> int:
        """Invalidate all cached responses related to a project.

        Called when the project graph changes significantly (new files, major
        refactors) to prevent stale cached responses.
        """
        with self._connect() as conn:
            # Delete expired entries first
            conn.execute("DELETE FROM response_cache WHERE expires_at < ?", (time.time(),))
            # Count remaining for reporting
            row = conn.execute("SELECT COUNT(*) as cnt FROM response_cache").fetchone()
            before = row["cnt"]
            # Invalidate all — we can't map cache keys to projects cheaply,
            # but this is the safe approach when the graph changes.
            conn.execute("DELETE FROM response_cache")
            logger.info("Cache invalidated: %d entries cleared for project %s", before, project_id)
            return before

    @staticmethod
    def _cache_key(system_prompt: str, user_message: str) -> str:
        raw = f"{system_prompt}||{user_message}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def task_fingerprint(task: str) -> str:
        """Compute a normalized fingerprint for a task string.

        Strips whitespace, lowercases, removes filler words, and hashes.
        Two semantically identical task descriptions will produce the same
        fingerprint even if worded slightly differently.
        """
        import re
        # Normalize: lowercase, strip, collapse whitespace
        t = re.sub(r'\s+', ' ', task.lower().strip())
        # Remove common filler words that don't change task intent
        for filler in ('please', 'can you', 'could you', 'i want to',
                       'i need to', 'help me', 'the', 'a ', 'an '):
            t = t.replace(filler, '')
        t = re.sub(r'\s+', ' ', t).strip()
        return hashlib.sha256(t.encode()).hexdigest()[:24]

    # ── Stats ─────────────────────────────────────────────────────────────

    # ── Project Registry ──────────────────────────────────────────────────

    def create_project(
        self,
        name: str,
        description: str = "",
        project_id: str | None = None,
    ) -> ProjectRecord:
        """Create a new project. Generates a unique ID from the name."""
        import re
        import uuid
        # Sanitize name → slug + short UUID for uniqueness
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        pid = project_id or f"{slug}_{uuid.uuid4().hex[:6]}"
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO projects (id, name, description, created_at, last_accessed_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (pid, name, description, now, now),
            )
        return ProjectRecord(id=pid, name=name, description=description,
                             created_at=now, last_accessed_at=now)

    def get_project(self, project_id: str) -> ProjectRecord | None:
        """Look up a project by ID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if not row:
                return None
            return ProjectRecord(
                id=row["id"], name=row["name"], description=row["description"],
                created_at=row["created_at"], last_accessed_at=row["last_accessed_at"],
            )

    def get_project_by_name(self, name: str) -> ProjectRecord | None:
        """Look up a project by name."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE name = ?", (name,)
            ).fetchone()
            if not row:
                return None
            return ProjectRecord(
                id=row["id"], name=row["name"], description=row["description"],
                created_at=row["created_at"], last_accessed_at=row["last_accessed_at"],
            )

    def list_projects(self) -> list[ProjectRecord]:
        """List all registered projects, most recently accessed first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM projects ORDER BY last_accessed_at DESC"
            ).fetchall()
            return [
                ProjectRecord(
                    id=r["id"], name=r["name"], description=r["description"],
                    created_at=r["created_at"], last_accessed_at=r["last_accessed_at"],
                )
                for r in rows
            ]

    def touch_project(self, project_id: str) -> None:
        """Update last_accessed_at timestamp for a project."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE projects SET last_accessed_at = ? WHERE id = ?",
                (time.time(), project_id),
            )

    def resolve_project(self, name_or_id: str) -> ProjectRecord | None:
        """Find a project by ID or name (tries ID first)."""
        proj = self.get_project(name_or_id)
        if proj:
            return proj
        return self.get_project_by_name(name_or_id)

    def get_stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            counts: dict[str, int] = {}
            for table in ("agent_memory", "shared_knowledge", "session_history",
                          "response_cache", "task_memory", "vector_store", "projects"):
                row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
                counts[table] = row["cnt"]
            return counts


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: MemoryStore | None = None


def get_memory_store(db_path: str | None = None) -> MemoryStore:
    global _instance
    if _instance is None:
        _instance = MemoryStore(db_path or config.MEMORY_DB_PATH)
    return _instance
