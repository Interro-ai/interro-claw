"""
BackendAgent – generates backend application code (Python FastAPI or Node.js).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from interro_claw.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

BACKEND_SYSTEM_PROMPT = """\
You are an expert backend engineer. Given a task description, generate
production-quality backend code.

Rules:
- Default framework: Python FastAPI unless told otherwise.
- Include proper error handling, input validation, and logging.
- Use async where appropriate.
- Return your output as one or more file blocks using this format:

### FILE: <relative/path/filename>
```
<file content>
```

Do NOT include any commentary outside the file blocks.
"""


class BackendAgent(BaseAgent):
    name = "BackendAgent"
    system_prompt = BACKEND_SYSTEM_PROMPT
    output_subdir = "backend"

    async def _post_process(self, task: str, response: str) -> None:
        files = self._extract_files(response)
        if files:
            for rel_path, content in files.items():
                self.write_artifact(rel_path, content)
        else:
            self.write_artifact("backend_output.txt", response)

    @staticmethod
    def _extract_files(text: str) -> dict[str, str]:
        """Parse ### FILE: <path> blocks from LLM output."""
        pattern = r"###\s*FILE:\s*(.+?)\s*\n```[^\n]*\n(.*?)```"
        matches = re.findall(pattern, text, re.DOTALL)
        return {name.strip(): content for name, content in matches}
