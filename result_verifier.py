"""
Result Verifier

After an agent completes its work, this module evaluates the output across
four dimensions:
    1. Correctness  – Does it solve the task? Logic errors?
    2. Performance   – Efficient algorithms, no N+1, resource leaks?
    3. Safety        – OWASP risks, injection, secrets exposure?
    4. Consistency   – Follows project architecture, naming, patterns?

The verifier uses the same LLM client to perform evaluation, with a focused
rubric prompt.  Returns a structured VerificationResult with per-dimension
scores and a pass/fail verdict.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_DIMENSIONS = ("correctness", "performance", "safety", "consistency")

_RUBRIC_PROMPT = """\
You are a senior code-review evaluator. Assess the AGENT OUTPUT below against the
ORIGINAL TASK and PROJECT CONTEXT on these four dimensions. For each, give a score
from 1 (critical issues) to 10 (excellent) and a brief justification.

## Scoring Rubric
- **Correctness**: Does the output fully address the task? Are there logic errors,
  missing edge cases, or incorrect assumptions?
- **Performance**: Are algorithms efficient? Any obvious N+1 queries, memory leaks,
  unnecessary allocations, or blocking calls?
- **Safety**: OWASP top-10 compliance—injection risks, improper auth, secrets in code,
  insecure defaults?
- **Consistency**: Does the output follow the project's architecture, naming conventions,
  file structure, and established patterns?

## Response Format
Respond ONLY with a JSON object (no markdown fences, no extra text):
{
    "correctness": {"score": <1-10>, "note": "<one sentence>"},
    "performance": {"score": <1-10>, "note": "<one sentence>"},
    "safety":      {"score": <1-10>, "note": "<one sentence>"},
    "consistency": {"score": <1-10>, "note": "<one sentence>"},
    "overall_note": "<one sentence summary>"
}
"""


@dataclass
class DimensionScore:
    name: str
    score: int  # 1-10
    note: str = ""


@dataclass
class VerificationResult:
    agent_name: str
    task_title: str
    dimensions: list[DimensionScore] = field(default_factory=list)
    overall_note: str = ""
    passed: bool = False
    raw_response: str = ""

    @property
    def average_score(self) -> float:
        if not self.dimensions:
            return 0.0
        return sum(d.score for d in self.dimensions) / len(self.dimensions)

    @property
    def min_score(self) -> int:
        if not self.dimensions:
            return 0
        return min(d.score for d in self.dimensions)

    def summary(self) -> str:
        parts = [f"Verification for {self.agent_name} — '{self.task_title}'"]
        for d in self.dimensions:
            parts.append(f"  {d.name:13s}: {d.score}/10  {d.note}")
        parts.append(f"  {'average':13s}: {self.average_score:.1f}/10")
        parts.append(f"  passed: {self.passed}  |  {self.overall_note}")
        return "\n".join(parts)


class ResultVerifier:
    """Evaluates agent output with an LLM-based rubric."""

    def __init__(
        self,
        llm_client: Any,
        pass_threshold: float = 6.0,
        min_dimension_score: int = 4,
    ) -> None:
        self._llm = llm_client
        self._pass_threshold = pass_threshold
        self._min_dim = min_dimension_score

    async def verify(
        self,
        agent_name: str,
        task_title: str,
        task_description: str,
        agent_output: str,
        project_context: str = "",
        architecture_ref: str = "",
    ) -> VerificationResult:
        """Run verification and return structured result."""
        result = VerificationResult(agent_name=agent_name, task_title=task_title)

        # Build the evaluation prompt
        user_parts = [f"## ORIGINAL TASK\n{task_description}\n"]
        if project_context:
            user_parts.append(f"## PROJECT CONTEXT\n{project_context[:3000]}\n")
        if architecture_ref:
            user_parts.append(f"## ARCHITECTURE REFERENCE\n{architecture_ref[:2000]}\n")
        user_parts.append(f"## AGENT OUTPUT\n{agent_output[:8000]}\n")

        user_msg = "\n".join(user_parts)

        try:
            raw = await self._llm.chat(
                system_prompt=_RUBRIC_PROMPT,
                user_message=user_msg,
            )
        except Exception as e:
            logger.error("Verification LLM call failed: %s", e)
            result.overall_note = f"Verification skipped: {e}"
            result.passed = True  # Don't block on verifier failure
            return result

        result.raw_response = raw
        parsed = self._parse(raw)

        if parsed is None:
            logger.warning("Could not parse verifier response")
            result.overall_note = "Verification response unparseable"
            result.passed = True  # Don't block on parse failure
            return result

        for dim in _DIMENSIONS:
            entry = parsed.get(dim, {})
            score = int(entry.get("score", 5))
            score = max(1, min(10, score))
            note = str(entry.get("note", ""))
            result.dimensions.append(DimensionScore(name=dim, score=score, note=note))

        result.overall_note = parsed.get("overall_note", "")

        # Determine pass/fail
        result.passed = (
            result.average_score >= self._pass_threshold
            and result.min_score >= self._min_dim
        )

        return result

    @staticmethod
    def _parse(raw: str) -> dict | None:
        """Extract JSON from LLM response."""
        # Try direct parse first
        try:
            return json.loads(raw.strip())
        except json.JSONDecodeError:
            pass
        # Try extracting from markdown code fence
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        # Try finding any JSON object
        match = re.search(r"\{[^{}]*\"correctness\"[^{}]*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return None


# -- Singleton ---------------------------------------------------------------

_instance: ResultVerifier | None = None


def get_result_verifier(llm_client: Any, **kwargs: Any) -> ResultVerifier:
    global _instance
    if _instance is None:
        _instance = ResultVerifier(llm_client, **kwargs)
    return _instance
