"""
ArchitectAgent – designs system architecture and folder structures.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from interro_claw.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

ARCHITECT_SYSTEM_PROMPT = """\
You are a senior software architect. Given a task description, produce:

1. A recommended technology stack with brief justification.
2. A folder/file tree for the project.
3. Key design decisions (API style, state management, deployment model, etc.).
4. The **deployment target** — what platform this project should target
   (e.g., web-app, python-app, dotnet-app, android-app, ios-app,
   desktop-windows, desktop-linux, cli-tool, docker, serverless,
   api-service, library). Choose based on the task description;
   do NOT default to Docker/containers unless explicitly required.

Return your answer as a JSON object with keys:
  "tech_stack", "folder_tree", "design_decisions", "deployment_target"

Output ONLY valid JSON (no markdown fences).
"""


class ArchitectAgent(BaseAgent):
    name = "ArchitectAgent"
    system_prompt = ARCHITECT_SYSTEM_PROMPT
    output_subdir = "logs"

    async def _post_process(self, task: str, response: str) -> None:
        self.write_artifact("architecture.json", response)
        # Publish architecture decisions to shared knowledge so other agents can use them
        self.publish(
            topic="architecture",
            fact=response[:500],
            confidence=0.95,
        )
        self.remember(response[:500], category="decision", task=task[:200])
        logger.info("[%s] Architecture plan saved + published to shared knowledge.", self.name)
