"""
FrontendAgent – generates frontend application code (React / Next.js).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from interro_claw.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

FRONTEND_SYSTEM_PROMPT = """\
You are an expert frontend engineer. Given a task description, generate
production-quality frontend code.

Rules:
- Default framework: React with TypeScript unless told otherwise.
- Use functional components and hooks.
- Include proper types, accessibility attributes, and responsive design.
- Return your output as one or more file blocks using this format:

### FILE: <relative/path/filename>
```
<file content>
```

Do NOT include any commentary outside the file blocks.
"""


class FrontendAgent(BaseAgent):
    name = "FrontendAgent"
    system_prompt = FRONTEND_SYSTEM_PROMPT
    output_subdir = "frontend"

    async def _post_process(self, task: str, response: str) -> None:
        files = self._extract_files(response)
        if files:
            for rel_path, content in files.items():
                self.write_artifact(rel_path, content)
        else:
            self.write_artifact("frontend_output.txt", response)

    @staticmethod
    def _extract_files(text: str) -> dict[str, str]:
        pattern = r"###\s*FILE:\s*(.+?)\s*\n```[^\n]*\n(.*?)```"
        matches = re.findall(pattern, text, re.DOTALL)
        return {name.strip(): content for name, content in matches}
