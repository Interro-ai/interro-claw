"""
Safety & Guardrails Layer

Prevents: infinite loops, runaway agents, file corruption, token budget overruns.

Features:
- Max token limits per agent call
- Max recursive depth for self-reflection loops
- Critical file protection (blocklist of paths agents must not modify)
- Human confirmation hooks for destructive actions
- Agent execution timeout
- Output size limits
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

import interro_claw.config as config

logger = logging.getLogger(__name__)


@dataclass
class GuardrailConfig:
    """All safety thresholds in one place."""
    max_tokens_per_call: int = 0
    max_reflection_depth: int = 0
    max_agent_runtime_seconds: float = 0.0
    max_output_chars: int = 0
    max_total_llm_calls_per_session: int = 0

    # Paths agents must NEVER modify (relative to workspace root)
    protected_paths: list[str] = field(default_factory=lambda: [
        ".git/**",
        ".env",
        "*.pem",
        "*.key",
        "**/*secret*",
        "**/id_rsa*",
    ])

    # Patterns that trigger human confirmation
    destructive_patterns: list[str] = field(default_factory=lambda: [
        r"rm\s+-rf",
        r"DROP\s+TABLE",
        r"DELETE\s+FROM\s+\w+\s*;?\s*$",  # DELETE without WHERE
        r"format\s+[a-z]:",
        r"git\s+push\s+--force",
        r"git\s+reset\s+--hard",
    ])

    def __post_init__(self) -> None:
        # Fill from config.py values (which reads from .env via dotenv)
        if self.max_tokens_per_call == 0:
            self.max_tokens_per_call = config.MAX_TOKENS_PER_CALL
        if self.max_reflection_depth == 0:
            self.max_reflection_depth = config.MAX_REFLECTION_DEPTH
        if self.max_agent_runtime_seconds == 0.0:
            self.max_agent_runtime_seconds = config.MAX_AGENT_RUNTIME_SECONDS
        if self.max_output_chars == 0:
            self.max_output_chars = config.MAX_OUTPUT_CHARS
        if self.max_total_llm_calls_per_session == 0:
            self.max_total_llm_calls_per_session = config.MAX_LLM_CALLS_PER_SESSION


class Guardrails:
    """Enforces safety limits on agent execution."""

    def __init__(self, cfg: GuardrailConfig | None = None) -> None:
        self.cfg = cfg or GuardrailConfig()
        self._llm_call_count = 0
        self._human_confirm_fn: Callable[[str], bool] | None = None

    def set_human_confirm(self, fn: Callable[[str], bool]) -> None:
        """Register a callback for human confirmation prompts."""
        self._human_confirm_fn = fn

    # -- token budget -------------------------------------------------------

    def check_token_budget(self, text: str) -> str:
        """Truncate text if it exceeds the token budget (approx 4 chars/token)."""
        approx_tokens = len(text) // 4
        if approx_tokens > self.cfg.max_tokens_per_call:
            max_chars = self.cfg.max_tokens_per_call * 4
            logger.warning(
                "Output truncated: ~%d tokens > limit %d",
                approx_tokens, self.cfg.max_tokens_per_call,
            )
            return text[:max_chars] + "\n\n[TRUNCATED — exceeded token limit]"
        return text

    # -- output size --------------------------------------------------------

    def check_output_size(self, text: str) -> str:
        if len(text) > self.cfg.max_output_chars:
            logger.warning("Output size %d > limit %d", len(text), self.cfg.max_output_chars)
            return text[:self.cfg.max_output_chars] + "\n\n[TRUNCATED]"
        return text

    # -- LLM call counter ---------------------------------------------------

    def increment_llm_calls(self) -> None:
        self._llm_call_count += 1
        if self._llm_call_count > self.cfg.max_total_llm_calls_per_session:
            raise RuntimeError(
                f"Session LLM call limit exceeded ({self.cfg.max_total_llm_calls_per_session})"
            )

    @property
    def llm_call_count(self) -> int:
        return self._llm_call_count

    # -- reflection depth ---------------------------------------------------

    def check_reflection_depth(self, current_depth: int) -> bool:
        """Return True if another reflection iteration is allowed."""
        if current_depth >= self.cfg.max_reflection_depth:
            logger.warning("Reflection depth limit reached: %d", current_depth)
            return False
        return True

    # -- file protection ----------------------------------------------------

    def is_path_protected(self, path: str) -> bool:
        """Check if a path matches any protected pattern."""
        import fnmatch
        norm = path.replace("\\", "/")
        for pattern in self.cfg.protected_paths:
            if fnmatch.fnmatch(norm, pattern):
                logger.warning("BLOCKED: path '%s' matches protected pattern '%s'", path, pattern)
                return True
        return False

    # -- destructive action detection ---------------------------------------

    def check_destructive(self, content: str) -> bool:
        """
        Return True if content contains destructive commands.
        If a human confirm callback is set, it will be invoked.
        """
        for pattern in self.cfg.destructive_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                logger.warning("Destructive pattern detected: %s", pattern)
                if self._human_confirm_fn:
                    msg = f"Destructive action detected (pattern: {pattern}). Allow?"
                    if not self._human_confirm_fn(msg):
                        raise PermissionError(f"Human denied destructive action: {pattern}")
                return True
        return False

    # -- validate agent output before writing -------------------------------

    def validate_output(self, agent_name: str, filepath: str, content: str) -> str:
        """Run all checks on content before an agent writes a file."""
        if self.is_path_protected(filepath):
            raise PermissionError(f"Agent {agent_name} blocked from writing to {filepath}")
        self.check_destructive(content)
        content = self.check_output_size(content)
        return content

    def get_stats(self) -> dict[str, Any]:
        return {
            "llm_calls": self._llm_call_count,
            "max_llm_calls": self.cfg.max_total_llm_calls_per_session,
            "max_tokens_per_call": self.cfg.max_tokens_per_call,
            "max_reflection_depth": self.cfg.max_reflection_depth,
            "protected_paths": self.cfg.protected_paths,
        }


# -- Singleton ---------------------------------------------------------------

_instance: Guardrails | None = None


def get_guardrails() -> Guardrails:
    global _instance
    if _instance is None:
        _instance = Guardrails()
    return _instance
