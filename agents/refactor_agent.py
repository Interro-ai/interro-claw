"""
RefactorAgent – improves code for performance, readability, and UX.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from interro_claw.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

REFACTOR_SYSTEM_PROMPT = """\
You are a senior software engineer specialising in code quality.

Given a task description (and optionally existing code), produce refactored
versions that improve:
- Performance (algorithmic efficiency, caching, async patterns)
- Readability (naming, structure, comments where non-obvious)
- UX (better error messages, loading states, accessibility)

Rules:
- Preserve existing functionality — do NOT change behaviour unless explicitly asked.
- Explain each change briefly in a comment.
- Return your output as file blocks using this format:

### FILE: <relative/path/filename>
```
<file content>
```

Do NOT include any commentary outside the file blocks.
"""


class RefactorAgent(BaseAgent):
    name = "RefactorAgent"
    system_prompt = REFACTOR_SYSTEM_PROMPT
    output_subdir = "backend"  # refactored code goes alongside originals

    async def _post_process(self, task: str, response: str) -> None:
        files = self._extract_files(response)
        if files:
            for rel_path, content in files.items():
                self.write_artifact(rel_path, content)
        else:
            self.write_artifact("refactor_output.txt", response)

    @staticmethod
    def _extract_files(text: str) -> dict[str, str]:
        pattern = r"###\s*FILE:\s*(.+?)\s*\n```[^\n]*\n(.*?)```"
        matches = re.findall(pattern, text, re.DOTALL)
        return {name.strip(): content for name, content in matches}
