"""
Short-Term Memory — ephemeral per-task memory stored as JSON files.

Each agent gets a directory: memory/runtime/<agent_name>/
Each task within it: <task_id>.json

Cleared automatically after each task completes (or on explicit flush).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_RUNTIME_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory", "runtime")


@dataclass
class STMEntry:
    """A single short-term memory entry."""
    key: str
    value: Any
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "value": self.value, "timestamp": self.timestamp}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> STMEntry:
        return cls(key=d["key"], value=d["value"], timestamp=d.get("timestamp", 0.0))


class ShortTermMemory:
    """Per-task ephemeral memory backed by JSON files in memory/runtime/."""

    def __init__(self, base_dir: str | None = None) -> None:
        self._base = base_dir or _RUNTIME_DIR
        os.makedirs(self._base, exist_ok=True)

    def _task_path(self, agent_name: str, task_id: str) -> str:
        agent_dir = os.path.join(self._base, agent_name)
        os.makedirs(agent_dir, exist_ok=True)
        return os.path.join(agent_dir, f"{task_id}.json")

    def _load(self, agent_name: str, task_id: str) -> dict[str, Any]:
        path = self._task_path(agent_name, task_id)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"entries": [], "meta": {}}

    def _save(self, agent_name: str, task_id: str, data: dict[str, Any]) -> None:
        path = self._task_path(agent_name, task_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    # -- Public API ---------------------------------------------------------

    def store(self, agent_name: str, task_id: str, key: str, value: Any) -> None:
        """Store a key-value pair in short-term memory for a task."""
        data = self._load(agent_name, task_id)
        entry = STMEntry(key=key, value=value, timestamp=time.time())
        # Upsert by key
        entries = [e for e in data["entries"] if e.get("key") != key]
        entries.append(entry.to_dict())
        data["entries"] = entries
        self._save(agent_name, task_id, data)

    def recall(self, agent_name: str, task_id: str, key: str | None = None) -> list[STMEntry]:
        """Recall entries. If key is None, return all."""
        data = self._load(agent_name, task_id)
        entries = [STMEntry.from_dict(e) for e in data.get("entries", [])]
        if key:
            entries = [e for e in entries if e.key == key]
        return entries

    def recall_all(self, agent_name: str, task_id: str) -> dict[str, Any]:
        """Return all entries as a flat dict."""
        entries = self.recall(agent_name, task_id)
        return {e.key: e.value for e in entries}

    def set_meta(self, agent_name: str, task_id: str, meta: dict[str, Any]) -> None:
        """Store task-level metadata (e.g., task description, start time)."""
        data = self._load(agent_name, task_id)
        data["meta"] = meta
        self._save(agent_name, task_id, data)

    def get_meta(self, agent_name: str, task_id: str) -> dict[str, Any]:
        data = self._load(agent_name, task_id)
        return data.get("meta", {})

    def clear(self, agent_name: str, task_id: str) -> None:
        """Clear short-term memory for a specific task."""
        path = self._task_path(agent_name, task_id)
        if os.path.exists(path):
            os.remove(path)
            logger.debug("STM cleared: %s/%s", agent_name, task_id)

    def clear_agent(self, agent_name: str) -> None:
        """Clear all short-term memory for an agent."""
        agent_dir = os.path.join(self._base, agent_name)
        if os.path.isdir(agent_dir):
            for f in os.listdir(agent_dir):
                os.remove(os.path.join(agent_dir, f))
            logger.debug("STM cleared all for agent: %s", agent_name)

    def to_prompt_section(self, agent_name: str, task_id: str) -> str:
        """Format STM as a prompt section for injection."""
        entries = self.recall(agent_name, task_id)
        if not entries:
            return ""
        parts = ["## Short-Term Memory (this task)"]
        for e in entries:
            val = str(e.value)[:500]
            parts.append(f"- **{e.key}**: {val}")
        return "\n".join(parts)


# -- Singleton ---------------------------------------------------------------

_instance: ShortTermMemory | None = None


def get_short_term_memory() -> ShortTermMemory:
    global _instance
    if _instance is None:
        _instance = ShortTermMemory()
    return _instance
