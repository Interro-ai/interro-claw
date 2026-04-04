"""
OpsAgent – generates Infrastructure-as-Code (Terraform / Bicep) and CI/CD YAML.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from interro_claw.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

OPS_SYSTEM_PROMPT = """\
You are a senior DevOps / Cloud engineer specialising in Azure.

Given a task description, generate:
- Infrastructure-as-Code files (prefer Bicep; fall back to Terraform if requested).
- CI/CD pipeline YAML (GitHub Actions or Azure DevOps).
- Any required Dockerfiles or Helm charts.

Rules:
- Follow Azure Well-Architected Framework best practices.
- Include parameterised templates, not hard-coded values.
- Return your output as file blocks using this format:

### FILE: <relative/path/filename>
```
<file content>
```

Do NOT include any commentary outside the file blocks.
"""


class OpsAgent(BaseAgent):
    name = "OpsAgent"
    system_prompt = OPS_SYSTEM_PROMPT
    output_subdir = "infra"

    async def _post_process(self, task: str, response: str) -> None:
        files = self._extract_files(response)
        if files:
            for rel_path, content in files.items():
                self.write_artifact(rel_path, content)
        else:
            self.write_artifact("infra_output.txt", response)

    @staticmethod
    def _extract_files(text: str) -> dict[str, str]:
        pattern = r"###\s*FILE:\s*(.+?)\s*\n```[^\n]*\n(.*?)```"
        matches = re.findall(pattern, text, re.DOTALL)
        return {name.strip(): content for name, content in matches}
