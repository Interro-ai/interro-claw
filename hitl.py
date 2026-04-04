"""
Human-in-the-Loop Checkpoints

Provides diff previews, summaries, and validation reports
at configurable checkpoints. Auto-approve or ask for human approval.

Modes:
- AUTO: auto-approve everything
- CONFIRM_HIGH_RISK: only prompt for high-risk changes
- CONFIRM_ALL: prompt for every change
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

import interro_claw.config as config

logger = logging.getLogger(__name__)


class ApprovalMode(str, Enum):
    AUTO = "auto"
    CONFIRM_HIGH_RISK = "confirm_high_risk"
    CONFIRM_ALL = "confirm_all"


@dataclass
class Checkpoint:
    """A human-in-the-loop checkpoint."""
    id: str
    stage: str  # "pre_plan", "post_plan", "pre_write", "post_verify"
    agent_name: str
    summary: str
    diff_preview: str = ""
    risk_score: float = 0.0
    approved: bool = False
    auto_approved: bool = False
    feedback: str = ""
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = time.time()


class HumanCheckpoint:
    """Manages human-in-the-loop approval checkpoints."""

    def __init__(
        self,
        mode: ApprovalMode | None = None,
        input_fn: Callable[[str], str] | None = None,
    ) -> None:
        self._mode = mode or ApprovalMode(
            config.HITL_MODE if hasattr(config, "HITL_MODE") else "auto"
        )
        self._input_fn = input_fn or self._default_input
        self._checkpoints: list[Checkpoint] = []

    def checkpoint(
        self,
        stage: str,
        agent_name: str,
        summary: str,
        diff_preview: str = "",
        risk_score: float = 0.0,
    ) -> Checkpoint:
        """Create a checkpoint and optionally ask for approval."""
        cp = Checkpoint(
            id=f"cp-{len(self._checkpoints):04d}",
            stage=stage,
            agent_name=agent_name,
            summary=summary,
            diff_preview=diff_preview,
            risk_score=risk_score,
        )

        if self._mode == ApprovalMode.AUTO:
            cp.approved = True
            cp.auto_approved = True
        elif self._mode == ApprovalMode.CONFIRM_HIGH_RISK and risk_score < 0.7:
            cp.approved = True
            cp.auto_approved = True
        else:
            cp.approved = self._ask_approval(cp)

        self._checkpoints.append(cp)
        return cp

    def _ask_approval(self, cp: Checkpoint) -> bool:
        """Present checkpoint to human and get approval."""
        msg = [
            "=" * 60,
            f"CHECKPOINT [{cp.stage}] — {cp.agent_name}",
            f"Risk: {cp.risk_score:.1f}",
            "",
            cp.summary,
        ]
        if cp.diff_preview:
            msg.append("\n--- Diff Preview ---")
            msg.append(cp.diff_preview[:2000])
        msg.append("\nApprove? [Y/n/feedback]: ")

        response = self._input_fn("\n".join(msg))
        response = response.strip().lower()

        if not response or response in ("y", "yes"):
            logger.info("Checkpoint %s APPROVED by human", cp.id)
            return True
        elif response in ("n", "no"):
            logger.info("Checkpoint %s REJECTED by human", cp.id)
            return False
        else:
            cp.feedback = response
            logger.info("Checkpoint %s — human feedback: %s", cp.id, response)
            return False

    @staticmethod
    def _default_input(prompt: str) -> str:
        try:
            return input(prompt)
        except (EOFError, KeyboardInterrupt):
            return "n"

    def get_history(self) -> list[Checkpoint]:
        return list(self._checkpoints)

    def get_stats(self) -> dict[str, Any]:
        return {
            "total": len(self._checkpoints),
            "approved": sum(1 for c in self._checkpoints if c.approved),
            "auto_approved": sum(1 for c in self._checkpoints if c.auto_approved),
            "rejected": sum(1 for c in self._checkpoints if not c.approved),
            "mode": self._mode.value,
        }

    @property
    def mode(self) -> ApprovalMode:
        return self._mode

    @mode.setter
    def mode(self, value: ApprovalMode) -> None:
        self._mode = value


# -- Singleton ---------------------------------------------------------------

_instance: HumanCheckpoint | None = None


def get_hitl() -> HumanCheckpoint:
    global _instance
    if _instance is None:
        _instance = HumanCheckpoint()
    return _instance
