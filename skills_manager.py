"""
Skills system — auto-loads .md skill files and injects them into agent prompts.

Skill files are stored in the `skills/` directory. Each .md file is a skill.
Users can add custom skills by placing .md files there. Skills are loaded
at startup and made available to agents automatically.

Skills are organized by topic and injected into agent system prompts
when the skill's `applies_to` pattern matches the agent name or task.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")


@dataclass
class Skill:
    """A loaded skill with metadata parsed from YAML-like frontmatter."""
    name: str
    file_path: str
    content: str
    description: str = ""
    applies_to: list[str] = field(default_factory=lambda: ["*"])  # agent/task glob patterns
    priority: int = 0  # higher = injected first


class SkillsManager:
    """
    Loads all .md files from the skills/ directory, parses optional
    frontmatter (---…---), and provides skill lookup by agent/task match.
    """

    def __init__(self, skills_dir: str | None = None) -> None:
        self._dir = skills_dir or _SKILLS_DIR
        self._skills: dict[str, Skill] = {}
        os.makedirs(self._dir, exist_ok=True)
        self._load_all()

    # -- loading ------------------------------------------------------------

    def _load_all(self) -> None:
        for fname in sorted(os.listdir(self._dir)):
            if not fname.endswith(".md"):
                continue
            path = os.path.join(self._dir, fname)
            try:
                raw = self._read_file(path)
                meta, body = self._parse_frontmatter(raw)
                skill = Skill(
                    name=meta.get("name", fname.removesuffix(".md")),
                    file_path=path,
                    content=body.strip(),
                    description=meta.get("description", ""),
                    applies_to=self._parse_list(meta.get("applies_to", "*")),
                    priority=int(meta.get("priority", 0)),
                )
                self._skills[skill.name] = skill
                logger.info("Loaded skill: %s (%s)", skill.name, path)
            except Exception as exc:
                logger.warning("Failed to load skill %s: %s", fname, exc)

    @staticmethod
    def _read_file(path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
        """Parse --- delimited YAML-like frontmatter at the top of a .md file."""
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
        if not match:
            return {}, text
        meta_raw, body = match.group(1), match.group(2)
        meta: dict[str, str] = {}
        for line in meta_raw.splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                meta[key.strip()] = val.strip().strip("'\"")
        return meta, body

    @staticmethod
    def _parse_list(val: str) -> list[str]:
        if "," in val:
            return [v.strip() for v in val.split(",")]
        return [val.strip()]

    # -- querying -----------------------------------------------------------

    def get_skills_for(self, agent_name: str, task: str = "") -> list[Skill]:
        """Return skills matching this agent or task, sorted by priority desc."""
        matched: list[Skill] = []
        check = f"{agent_name}|{task}".lower()
        for skill in self._skills.values():
            for pattern in skill.applies_to:
                if pattern == "*" or fnmatch.fnmatch(check, f"*{pattern.lower()}*"):
                    matched.append(skill)
                    break
        matched.sort(key=lambda s: s.priority, reverse=True)
        return matched

    def get_skill(self, name: str) -> Skill | None:
        return self._skills.get(name)

    @property
    def all_skills(self) -> list[Skill]:
        return list(self._skills.values())

    def format_skills_prompt(self, agent_name: str, task: str = "") -> str:
        """Return formatted skills text ready to prepend to a system prompt."""
        skills = self.get_skills_for(agent_name, task)
        if not skills:
            return ""
        parts = ["## Loaded Skills\n"]
        for s in skills:
            parts.append(f"### {s.name}")
            if s.description:
                parts.append(f"_{s.description}_\n")
            parts.append(s.content)
            parts.append("")
        return "\n".join(parts)

    def reload(self) -> None:
        """Reload all skills from disk."""
        self._skills.clear()
        self._load_all()


# -- Singleton ---------------------------------------------------------------

_instance: SkillsManager | None = None


def get_skills_manager(skills_dir: str | None = None) -> SkillsManager:
    global _instance
    if _instance is None:
        _instance = SkillsManager(skills_dir)
    return _instance
