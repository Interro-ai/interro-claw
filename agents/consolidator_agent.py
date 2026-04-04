"""
ConsolidatorAgent – the user-facing agent that runs after all tasks complete.

Responsibilities:
- Reads all generated artifacts and task results
- Produces a clear, human-friendly summary of what was built
- Tells the user exactly how to run / test / use the output
- Suggests next steps and asks what the user wants to do next
- Acts as the interactive bridge between the orchestrator and the human
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import interro_claw.config as config
from interro_claw.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

CONSOLIDATOR_SYSTEM_PROMPT = """\
You are the Consolidator Agent — the user-facing presenter for a multi-agent \
software engineering team. Your job is to communicate results clearly and \
interactively.

When given a session report (task results + generated files + original goal), \
you MUST produce a response with these sections:

## What Was Built
Summarize what the team created, grouped by component (backend, frontend, \
infrastructure, tests, security, etc.). Be specific about files and their \
purpose — don't just list filenames, explain what each does in plain language.

## How to Run It
Give the user exact, copy-paste commands to:
- Install dependencies
- Start the application locally
- Run tests (if test files were generated)
Be specific to the tech stack that was actually used (read from the artifacts).

## Issues & Warnings
If any tasks failed or were skipped, explain what went wrong and what the \
impact is. Be honest — don't hide failures.

## Suggested Next Steps
Offer 3-5 numbered options the user can choose from, such as:
1. Run the application locally
2. Add more features (describe what could be added)
3. Fix failed tasks
4. Deploy to production
5. Improve UI/UX

Keep your tone helpful and conversational. Use plain language, not jargon. \
Format for terminal readability (no long lines, use bullet points).
"""


class ConsolidatorAgent(BaseAgent):
    name = "ConsolidatorAgent"
    system_prompt = CONSOLIDATOR_SYSTEM_PROMPT
    output_subdir = "logs"

    async def consolidate(
        self,
        goal: str,
        tasks: list[Any],
        elapsed: float,
    ) -> str:
        """
        Build a context-rich prompt from all task results and artifacts,
        then ask the LLM to produce a human-friendly summary.
        """
        context = self._build_consolidation_context(goal, tasks, elapsed)
        # Run with reflection disabled — we want fast, direct output
        response = await super().run(
            task=context,
            enable_reflection=False,
            enable_tools=False,
        )
        self.write_artifact("session_report.md", response)
        return response

    def _build_consolidation_context(
        self,
        goal: str,
        tasks: list[Any],
        elapsed: float,
    ) -> str:
        """Assemble all information the consolidator needs."""
        parts: list[str] = []

        # Original goal
        parts.append(f"## Original User Goal\n{goal}\n")

        # Task results
        parts.append(f"## Task Results ({len(tasks)} tasks, {elapsed:.1f}s total)")
        for t in tasks:
            status = t.status.value if hasattr(t.status, "value") else str(t.status)
            time_str = f"{t.elapsed_ms / 1000:.1f}s" if t.elapsed_ms else "N/A"
            parts.append(f"- **{t.agent_name}** [{status}] ({time_str}): {t.description[:200]}")
            if t.error:
                parts.append(f"  ERROR: {t.error}")
            if t.result:
                # Include a snippet of the result so the LLM knows what was produced
                parts.append(f"  Output snippet: {t.result[:500]}")
        parts.append("")

        # Generated files with content previews
        artifacts_dir = config.ARTIFACTS_DIR
        if os.path.isdir(artifacts_dir):
            file_list: list[str] = []
            for dirpath, _, filenames in os.walk(artifacts_dir):
                for fn in filenames:
                    full = os.path.join(dirpath, fn)
                    rel = os.path.relpath(full, config.USER_APP_DIR)
                    try:
                        size = os.path.getsize(full)
                        # Read first 300 chars of small text files for context
                        preview = ""
                        if size < 50000 and not fn.endswith((".png", ".jpg", ".gif", ".zip")):
                            with open(full, "r", encoding="utf-8", errors="ignore") as f:
                                preview = f.read(300)
                        file_list.append(f"- {rel} ({size} bytes)")
                        if preview:
                            file_list.append(f"  Preview: {preview[:200]}...")
                    except OSError:
                        file_list.append(f"- {rel} (unreadable)")

            if file_list:
                parts.append(f"## Generated Files ({len([l for l in file_list if l.startswith('-')])})")
                parts.extend(file_list)
                parts.append("")

        parts.append(
            "## Your Task\n"
            "Based on the above, produce a clear summary for the user following "
            "your system instructions. Be specific about the actual files and "
            "technologies used — read from the artifacts, don't guess."
        )

        return "\n".join(parts)
