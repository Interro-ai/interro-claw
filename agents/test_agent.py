"""
TestAgent – generates end-to-end and integration tests (Playwright / Cypress).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from interro_claw.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

TEST_SYSTEM_PROMPT = """\
You are a senior QA / test automation engineer.

Given a task description (and optionally existing code context), generate
comprehensive test suites.

Rules:
- Default framework: Playwright (Python) for E2E; pytest for integration tests.
- Cover happy paths, edge cases, and error scenarios.
- Use descriptive test names and assertions.
- Return your output as file blocks using this format:

### FILE: <relative/path/filename>
```
<file content>
```

Do NOT include any commentary outside the file blocks.
"""


class TestAgent(BaseAgent):
    name = "TestAgent"
    system_prompt = TEST_SYSTEM_PROMPT
    output_subdir = "tests"

    async def _post_process(self, task: str, response: str) -> None:
        files = self._extract_files(response)
        if files:
            for rel_path, content in files.items():
                self.write_artifact(rel_path, content)
        else:
            self.write_artifact("test_output.txt", response)

    @staticmethod
    def _extract_files(text: str) -> dict[str, str]:
        pattern = r"###\s*FILE:\s*(.+?)\s*\n```[^\n]*\n(.*?)```"
        matches = re.findall(pattern, text, re.DOTALL)
        return {name.strip(): content for name, content in matches}
