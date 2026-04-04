"""
Guardrails v2 — enhanced safety, rollback, and bad-pattern detection.

Extends the original guardrails with:
- Snapshot-based rollback mechanism
- Bad pattern detector (anti-patterns, code smells)
- Infinite loop protection
- Max recursion depth enforcement
- Enhanced forbidden file protection
"""

from interro_claw.guardrails_v2.enhanced import EnhancedGuardrails, get_enhanced_guardrails
from interro_claw.guardrails_v2.snapshots import SnapshotManager, get_snapshot_manager

__all__ = [
    "EnhancedGuardrails",
    "get_enhanced_guardrails",
    "SnapshotManager",
    "get_snapshot_manager",
]
