"""
Smart Model Router v2

Routes LLM calls to the optimal model based on task complexity:
- Opus/expensive models for: architecture reasoning, deep debugging, complex refactors, multi-agent decisions
- Cheaper models (Sonnet, GPT-4o-mini, Ollama) for: simple edits, tests, bundling, static analysis

Task classification is based on agent type + task keywords + explicit hints.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

import interro_claw.config as config

logger = logging.getLogger(__name__)


class TaskComplexity(str, Enum):
    HEAVY = "heavy"    # Requires expensive/capable model
    MEDIUM = "medium"  # Mid-tier model
    LIGHT = "light"    # Cheap/fast model


@dataclass
class ModelRoute:
    """A model assignment for a specific call."""
    provider: str      # "claude", "openai", "ollama"
    model: str         # specific model name
    complexity: TaskComplexity
    reason: str = ""


# -- Classification rules ---------------------------------------------------

# Agents that always get expensive models
_HEAVY_AGENTS = {"ArchitectAgent", "PlannerAgent"}

# Agents that always get cheap models
_LIGHT_AGENTS = {"TestAgent", "RefactorAgent"}

# Keywords that escalate to expensive model
_HEAVY_KEYWORDS = [
    r"architect", r"design.*system", r"refactor.*complex",
    r"debug.*deep", r"multi.?agent", r"critical.*decision",
    r"security.*threat", r"migration.*strategy", r"api.*design",
    r"performance.*bottleneck", r"distributed",
]

# Keywords that indicate simple work
_LIGHT_KEYWORDS = [
    r"simple.*edit", r"fix.*typo", r"add.*test", r"update.*import",
    r"rename", r"format", r"lint", r"bundle", r"static.*analysis",
    r"add.*comment", r"update.*version", r"fix.*indent",
]


class SmartModelRouter:
    """Routes LLM calls to appropriate models based on task complexity."""

    def __init__(self) -> None:
        self._override: ModelRoute | None = None
        self._call_stats: dict[str, int] = {"heavy": 0, "medium": 0, "light": 0}

    def route(
        self,
        agent_name: str,
        task: str,
        hint: TaskComplexity | None = None,
    ) -> ModelRoute:
        """Determine the best model for this task."""
        if self._override:
            return self._override

        if hint:
            complexity = hint
        else:
            complexity = self._classify(agent_name, task)

        route = self._select_model(complexity)
        self._call_stats[complexity.value] += 1

        logger.debug(
            "Model route: %s/%s -> %s/%s (%s)",
            agent_name, task[:50], route.provider, route.model, complexity.value,
        )
        return route

    def set_override(self, route: ModelRoute | None) -> None:
        """Force all calls to a specific model (for testing)."""
        self._override = route

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._call_stats)

    def _classify(self, agent_name: str, task: str) -> TaskComplexity:
        """Classify task complexity."""
        # Agent-based classification
        if agent_name in _HEAVY_AGENTS:
            return TaskComplexity.HEAVY
        if agent_name in _LIGHT_AGENTS:
            return TaskComplexity.LIGHT

        task_lower = task.lower()

        # Keyword-based escalation
        for pattern in _HEAVY_KEYWORDS:
            if re.search(pattern, task_lower):
                return TaskComplexity.HEAVY

        for pattern in _LIGHT_KEYWORDS:
            if re.search(pattern, task_lower):
                return TaskComplexity.LIGHT

        # Default: medium
        return TaskComplexity.MEDIUM

    def _select_model(self, complexity: TaskComplexity) -> ModelRoute:
        """Select the concrete model for a complexity level, respecting the configured provider."""
        provider = config.LLM_PROVIDER

        if complexity == TaskComplexity.HEAVY:
            return ModelRoute(
                provider=provider,
                model=self._get_heavy_model(provider),
                complexity=complexity,
                reason="Complex reasoning task",
            )
        elif complexity == TaskComplexity.LIGHT:
            return ModelRoute(
                provider=provider,
                model=self._get_light_model(provider),
                complexity=complexity,
                reason="Simple task - using lighter model",
            )
        else:  # MEDIUM
            return ModelRoute(
                provider=provider,
                model=self._get_default_model(),
                complexity=complexity,
                reason="Standard complexity",
            )

    @staticmethod
    def _get_default_model() -> str:
        if config.LLM_PROVIDER == "claude":
            return config.CLAUDE_MODEL
        elif config.LLM_PROVIDER == "openai":
            return config.OPENAI_MODEL
        elif config.LLM_PROVIDER == "nvidia":
            return config.NVIDIA_MODEL
        return config.OLLAMA_MODEL

    @staticmethod
    def _get_heavy_model(provider: str) -> str:
        if provider == "claude":
            return config.CLAUDE_MODEL_HEAVY
        elif provider == "openai":
            return config.OPENAI_MODEL
        elif provider == "nvidia":
            return config.NVIDIA_MODEL_HEAVY
        return config.OLLAMA_MODEL

    @staticmethod
    def _get_light_model(provider: str) -> str:
        if provider == "claude":
            return config.CLAUDE_MODEL
        elif provider == "openai":
            return config.OPENAI_MODEL_LIGHT
        elif provider == "nvidia":
            return config.NVIDIA_MODEL_LIGHT
        return config.OLLAMA_MODEL


# -- Singleton ---------------------------------------------------------------

_instance: SmartModelRouter | None = None


def get_model_router() -> SmartModelRouter:
    global _instance
    if _instance is None:
        _instance = SmartModelRouter()
    return _instance
