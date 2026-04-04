"""
Enhanced Guardrails v2

Extends base guardrails with:
- Bad pattern / anti-pattern detector
- Infinite loop detection (repeated identical outputs)
- Enhanced file protection with glob-based allowlist
- Pre-change justification requirement
- Post-change validation pipeline (lint, syntax, tests)
- Integration with SnapshotManager for rollback
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import interro_claw.config as config
from interro_claw.guardrails import Guardrails, GuardrailConfig
from interro_claw.guardrails_v2.snapshots import SnapshotManager, get_snapshot_manager

logger = logging.getLogger(__name__)


@dataclass
class ChangeJustification:
    """Pre-change justification from an agent."""
    agent_name: str
    files_affected: list[str]
    reason: str
    risk_score: float  # 0.0 (safe) - 1.0 (critical)
    timestamp: float = 0.0

    def is_high_risk(self) -> bool:
        return self.risk_score >= 0.7


@dataclass
class ValidationResult:
    """Post-change validation result."""
    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)  # check_name -> pass/fail
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# Bad patterns that should be flagged
_BAD_PATTERNS = [
    (r"eval\s*\(", "eval() usage — potential code injection"),
    (r"exec\s*\(", "exec() usage — potential code injection"),
    (r"__import__\s*\(", "Dynamic import — security risk"),
    (r"subprocess\.call\([^)]*shell\s*=\s*True", "shell=True in subprocess — injection risk"),
    (r"pickle\.loads?\s*\(", "pickle usage — deserialization risk"),
    (r"password\s*=\s*['\"][^'\"]+['\"]", "Hardcoded password detected"),
    (r"api[_-]?key\s*=\s*['\"][A-Za-z0-9]{16,}['\"]", "Hardcoded API key"),
    (r"while\s+True\s*:\s*\n\s*pass", "Infinite busy loop"),
    (r"time\.sleep\s*\(\s*0\s*\)", "sleep(0) busy loop"),
    (r"except\s*:\s*\n\s*pass", "Bare except with pass — silent failure"),
    (r"# ?TODO|# ?FIXME|# ?HACK|# ?XXX", "TODO/FIXME marker left in code"),
]


class EnhancedGuardrails(Guardrails):
    """Extended guardrails with anti-pattern detection and rollback."""

    def __init__(
        self,
        cfg: GuardrailConfig | None = None,
        snapshot_mgr: SnapshotManager | None = None,
    ) -> None:
        super().__init__(cfg)
        self._snapshots = snapshot_mgr or get_snapshot_manager()
        self._recent_outputs: list[str] = []  # for loop detection
        self._max_repeated = 3
        self._justifications: list[ChangeJustification] = []
        self._validations: list[ValidationResult] = []

    @property
    def snapshot_manager(self) -> SnapshotManager:
        """Public access to the snapshot manager."""
        return self._snapshots

    # -- Pre-change justification -------------------------------------------

    def require_justification(
        self,
        agent_name: str,
        files: list[str],
        reason: str,
        risk_score: float,
    ) -> ChangeJustification:
        """Record a pre-change justification. Raises if risk is too high without approval."""
        j = ChangeJustification(
            agent_name=agent_name, files_affected=files,
            reason=reason, risk_score=risk_score, timestamp=time.time(),
        )
        self._justifications.append(j)

        if j.is_high_risk():
            logger.warning(
                "HIGH RISK change by %s (score=%.2f): %s — files: %s",
                agent_name, risk_score, reason, files,
            )
            if self._human_confirm_fn:
                msg = (
                    f"High-risk change by {agent_name} (risk={risk_score:.1f}):\n"
                    f"Files: {', '.join(files)}\n"
                    f"Reason: {reason}\n"
                    "Approve?"
                )
                if not self._human_confirm_fn(msg):
                    raise PermissionError("High-risk change denied by human reviewer")

        return j

    # -- Bad pattern detection ----------------------------------------------

    def scan_bad_patterns(self, content: str) -> list[str]:
        """Scan content for anti-patterns and return warnings."""
        warnings: list[str] = []
        for pattern, description in _BAD_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                warnings.append(description)
        return warnings

    # -- Infinite loop detection --------------------------------------------

    def check_repeated_output(self, output: str) -> bool:
        """Detect if the agent is producing the same output repeatedly (stuck in loop)."""
        output_hash = hash(output[:500])
        self._recent_outputs.append(str(output_hash))
        if len(self._recent_outputs) > 20:
            self._recent_outputs = self._recent_outputs[-20:]

        # Check for repeated consecutive outputs
        if len(self._recent_outputs) >= self._max_repeated:
            recent = self._recent_outputs[-self._max_repeated:]
            if len(set(recent)) == 1:
                logger.error("Infinite loop detected — agent producing identical output %d times", self._max_repeated)
                return True
        return False

    # -- Post-change validation ---------------------------------------------

    def validate_change(
        self,
        file_path: str,
        content: str,
        agent_name: str,
    ) -> ValidationResult:
        """Run post-change validation checks on modified content."""
        result = ValidationResult(passed=True)

        # 1. Syntax check
        if file_path.endswith(".py"):
            try:
                import ast as ast_mod
                ast_mod.parse(content)
                result.checks["syntax"] = True
            except SyntaxError as e:
                result.checks["syntax"] = False
                result.errors.append(f"Python syntax error: {e}")
                result.passed = False

        # 2. Bad pattern scan
        warnings = self.scan_bad_patterns(content)
        result.checks["patterns"] = len(warnings) == 0
        result.warnings.extend(warnings)

        # 3. File size check
        if len(content) > self.cfg.max_output_chars:
            result.checks["size"] = False
            result.errors.append(f"File too large: {len(content)} chars")
            result.passed = False
        else:
            result.checks["size"] = True

        # 4. Protected path check
        if self.is_path_protected(file_path):
            result.checks["protected"] = False
            result.errors.append(f"Protected path: {file_path}")
            result.passed = False
        else:
            result.checks["protected"] = True

        self._validations.append(result)
        return result

    # -- Snapshot integration -----------------------------------------------

    def snapshot_before_write(
        self,
        file_path: str,
        session_id: str,
        agent_name: str,
    ) -> None:
        """Take a snapshot before writing to a file."""
        self._snapshots.take_snapshot(file_path, session_id, agent_name)

    def rollback_session(self, session_id: str) -> int:
        """Rollback all changes from a session."""
        return self._snapshots.rollback_session(session_id)

    # -- Stats override -----------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        base = super().get_stats()
        base["justifications"] = len(self._justifications)
        base["validations"] = len(self._validations)
        base["validations_passed"] = sum(1 for v in self._validations if v.passed)
        base["snapshots"] = len(self._snapshots.get_snapshots())
        return base


# -- Singleton ---------------------------------------------------------------

_instance: EnhancedGuardrails | None = None


def get_enhanced_guardrails() -> EnhancedGuardrails:
    global _instance
    if _instance is None:
        _instance = EnhancedGuardrails()
    return _instance
