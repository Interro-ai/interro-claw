"""
PlannerAgent – breaks a user goal into a structured JSON task list.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from interro_claw.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

PLANNER_SYSTEM_PROMPT = """\
You are a senior software project planner. Given a high-level user goal,
decompose it into an ordered list of concrete tasks and assign each task
to the most appropriate specialist agent.

Available agents:
  - ArchitectAgent   : system architecture, folder layout, tech-stack decisions
  - BackendAgent     : backend code generation (FastAPI / Node.js)
  - FrontendAgent    : frontend code generation (React / Next.js)
  - OpsAgent         : infrastructure-as-code (Terraform / Bicep), CI/CD pipelines
  - TestAgent        : end-to-end and integration tests (Playwright / Cypress)
  - SecurityAgent    : static analysis, dependency scanning, threat modelling
  - RefactorAgent    : performance, readability, UX improvements

Respond ONLY with a JSON array (no markdown fences). Each element must have:
  { "task": "<description>", "agent": "<AgentName>" }

Order tasks so dependencies are satisfied (architecture first, tests last, etc.).
"""


class PlannerAgent(BaseAgent):
    name = "PlannerAgent"
    system_prompt = PLANNER_SYSTEM_PROMPT
    output_subdir = "logs"

    async def run(self, task: str, context: dict[str, Any] | None = None) -> list[dict[str, str]]:
        """Return the structured plan as a Python list of dicts."""
        # Disable reflection for PlannerAgent — reflection replaces valid JSON
        # with critique text, corrupting the structured output.
        raw = await super().run(task, context, enable_reflection=False)
        plan = self._parse_plan(raw)
        # persist the plan for auditing
        self.write_artifact("plan.json", json.dumps(plan, indent=2))
        return plan

    # ── internals ──────────────────────────────────────────────────────────

    @staticmethod
    def _parse_plan(text: str) -> list[dict[str, str]]:
        """Extract the JSON array from the LLM response, tolerating markdown fences."""
        import re as _re

        cleaned = text.strip()
        # strip optional ```json … ``` wrapper
        if cleaned.startswith("```"):
            first_newline = cleaned.index("\n")
            cleaned = cleaned[first_newline + 1 :]
            if cleaned.endswith("```"):
                cleaned = cleaned[: -3]

        # Try direct parse first
        try:
            plan = json.loads(cleaned)
            if isinstance(plan, list) and plan:
                return plan
        except json.JSONDecodeError:
            pass

        # Try extracting JSON array from within markdown fences embedded in text
        match = _re.search(r"```(?:json)?\s*\n(\[.*?\])\s*\n```", text, _re.DOTALL)
        if match:
            try:
                plan = json.loads(match.group(1))
                if isinstance(plan, list) and plan:
                    return plan
            except json.JSONDecodeError:
                pass

        # Try finding any JSON array in the text
        match = _re.search(r"(\[\s*\{.*?\}\s*\])", text, _re.DOTALL)
        if match:
            try:
                plan = json.loads(match.group(1))
                if isinstance(plan, list) and plan:
                    return plan
            except json.JSONDecodeError:
                pass

        logger.error("PlannerAgent returned non-JSON: %s", text[:200])
        return [{"task": text, "agent": "ArchitectAgent"}]
