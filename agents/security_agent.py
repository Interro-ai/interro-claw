"""
SecurityAgent – performs static analysis prompts and dependency scanning guidance.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from interro_claw.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

SECURITY_SYSTEM_PROMPT = """\
You are a senior application security engineer.

Given a task description (and optionally code to review), produce:
1. A threat model summary (STRIDE or similar).
2. Static analysis findings with severity (Critical / High / Medium / Low).
3. Dependency-scanning recommendations.
4. Remediation guidance for each finding.

Return your output as a JSON object with keys:
  "threat_model", "findings", "dependency_scan", "remediations"

If you also generate helper scripts (e.g. a bandit config), include them as file
blocks using:

### FILE: <relative/path/filename>
```
<file content>
```
"""


class SecurityAgent(BaseAgent):
    name = "SecurityAgent"
    system_prompt = SECURITY_SYSTEM_PROMPT
    output_subdir = "security"

    async def _post_process(self, task: str, response: str) -> None:
        # Save the full security report
        self.write_artifact("security_report.json", response)
        # Also extract any helper script files
        files = self._extract_files(response)
        for rel_path, content in files.items():
            self.write_artifact(rel_path, content)

    @staticmethod
    def _extract_files(text: str) -> dict[str, str]:
        pattern = r"###\s*FILE:\s*(.+?)\s*\n```[^\n]*\n(.*?)```"
        matches = re.findall(pattern, text, re.DOTALL)
        return {name.strip(): content for name, content in matches}
