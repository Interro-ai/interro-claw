"""
Memory subsystem — 3-layer agent memory hierarchy.

Layers:
  1. ShortTermMemory  — per-task ephemeral (memory/runtime/<agent>/<task_id>.json)
  2. WorkingMemory     — per-project persistent (memory/projects/<project_id>/)
  3. LongTermMemory    — cross-project global (memory/global/longterm.sqlite)
"""

from __future__ import annotations

import importlib.util
import os
import sys
from types import ModuleType

from interro_claw.memory.short_term import ShortTermMemory, get_short_term_memory
from interro_claw.memory.working import WorkingMemory, get_working_memory
from interro_claw.memory.long_term import LongTermMemory, get_long_term_memory


def _load_legacy_memory_module() -> ModuleType:
    """Load the legacy memory.py module without conflicting with this package."""
    package_dir = os.path.dirname(__file__)
    legacy_path = os.path.join(os.path.dirname(package_dir), "memory.py")
    spec = importlib.util.spec_from_file_location("_legacy_memory", legacy_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load legacy memory module from {legacy_path}")
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules so @dataclass can resolve cls.__module__
    sys.modules["_legacy_memory"] = module
    spec.loader.exec_module(module)
    return module


_legacy_memory = _load_legacy_memory_module()

MemoryStore = _legacy_memory.MemoryStore
MemoryEntry = _legacy_memory.MemoryEntry
KnowledgeFact = _legacy_memory.KnowledgeFact
SessionEntry = _legacy_memory.SessionEntry
TaskMemoryEntry = _legacy_memory.TaskMemoryEntry
VectorEntry = _legacy_memory.VectorEntry
SimilarityResult = _legacy_memory.SimilarityResult
get_memory_store = _legacy_memory.get_memory_store

__all__ = [
    "MemoryStore",
    "MemoryEntry",
    "KnowledgeFact",
    "SessionEntry",
    "TaskMemoryEntry",
    "VectorEntry",
    "SimilarityResult",
    "get_memory_store",
    "ShortTermMemory",
    "WorkingMemory",
    "LongTermMemory",
    "get_short_term_memory",
    "get_working_memory",
    "get_long_term_memory",
]
