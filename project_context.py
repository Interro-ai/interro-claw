"""
Unified Project Context Engine

Computes and caches a comprehensive snapshot of the project under analysis.
Shared across all agents so they never lose context.

Captures:
- Project structure (file tree)
- Language / framework detection
- Coding guidelines (if present)
- Environment variables / .env dependencies
- Package dependencies (requirements.txt, package.json, etc.)
- Configuration files (Azure, Docker, CI/CD)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Known config / guideline filenames
_GUIDELINE_FILES = {
    ".editorconfig", ".prettierrc", ".eslintrc.json", ".eslintrc.js",
    "pyproject.toml", "setup.cfg", ".flake8", ".pylintrc",
    "tsconfig.json", "biome.json",
}

_DEPENDENCY_FILES = {
    "requirements.txt", "Pipfile", "pyproject.toml", "setup.py",
    "package.json", "yarn.lock", "pnpm-lock.yaml",
    "go.mod", "Cargo.toml", "Gemfile",
}

_CONFIG_FILES = {
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    ".github/workflows/*.yml", ".azure-pipelines.yml",
    "azure-pipelines.yml", "bicep/*.bicep", "*.tf",
    "host.json", "local.settings.json",
}

_LANG_EXTENSIONS: dict[str, str] = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
    ".jsx": "React JSX", ".tsx": "React TSX", ".go": "Go",
    ".rs": "Rust", ".java": "Java", ".cs": "C#", ".rb": "Ruby",
    ".cpp": "C++", ".c": "C", ".swift": "Swift", ".kt": "Kotlin",
}


@dataclass
class ProjectContext:
    """Immutable snapshot of a project's context."""
    project_id: str
    root_path: str
    file_tree: list[str] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)  # lang -> file count
    frameworks: list[str] = field(default_factory=list)
    dependencies: dict[str, str] = field(default_factory=dict)  # filename -> content
    guidelines: dict[str, str] = field(default_factory=dict)
    config_files: dict[str, str] = field(default_factory=dict)
    env_vars: list[str] = field(default_factory=list)  # var names from .env*
    summary: str = ""

    def to_prompt_section(self) -> str:
        """Format as a prompt section for agent injection."""
        parts = ["## Project Context\n"]
        parts.append(f"**Root**: `{self.root_path}`")
        parts.append(f"**Languages**: {', '.join(f'{k} ({v})' for k, v in sorted(self.languages.items(), key=lambda x: -x[1])[:5])}")
        if self.frameworks:
            parts.append(f"**Frameworks**: {', '.join(self.frameworks)}")
        if self.env_vars:
            parts.append(f"**Env vars**: {', '.join(self.env_vars[:20])}")

        # Truncated file tree
        if self.file_tree:
            parts.append(f"\n**File tree** ({len(self.file_tree)} files, showing first 50):")
            for f in self.file_tree[:50]:
                parts.append(f"  {f}")
            if len(self.file_tree) > 50:
                parts.append(f"  ... and {len(self.file_tree) - 50} more")

        # Guidelines
        for name, content in self.guidelines.items():
            parts.append(f"\n**{name}** (guidelines):\n```\n{content[:500]}\n```")

        return "\n".join(parts)


class ProjectContextEngine:
    """
    Scans a project directory and builds a ProjectContext snapshot.
    Results are cached per project_id.
    """

    def __init__(self) -> None:
        self._cache: dict[str, ProjectContext] = {}

    def analyze(self, root_path: str, project_id: str | None = None) -> ProjectContext:
        """Analyze a project directory. Returns cached result if available."""
        pid = project_id or os.path.basename(root_path)
        if pid in self._cache:
            return self._cache[pid]

        logger.info("Analyzing project context: %s", root_path)
        ctx = ProjectContext(project_id=pid, root_path=root_path)

        self._scan_file_tree(ctx, root_path)
        self._detect_languages(ctx)
        self._detect_frameworks(ctx, root_path)
        self._load_dependencies(ctx, root_path)
        self._load_guidelines(ctx, root_path)
        self._load_configs(ctx, root_path)
        self._load_env_vars(ctx, root_path)
        self._build_summary(ctx)

        self._cache[pid] = ctx
        logger.info(
            "Project context ready: %d files, %d languages, %d frameworks",
            len(ctx.file_tree), len(ctx.languages), len(ctx.frameworks),
        )
        return ctx

    def invalidate(self, project_id: str) -> None:
        self._cache.pop(project_id, None)

    # -- scanning -----------------------------------------------------------

    def _scan_file_tree(self, ctx: ProjectContext, root: str) -> None:
        skip = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", "dist", "build"}
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip]
            for f in filenames:
                rel = os.path.relpath(os.path.join(dirpath, f), root).replace("\\", "/")
                ctx.file_tree.append(rel)

    def _detect_languages(self, ctx: ProjectContext) -> None:
        for f in ctx.file_tree:
            ext = Path(f).suffix.lower()
            lang = _LANG_EXTENSIONS.get(ext)
            if lang:
                ctx.languages[lang] = ctx.languages.get(lang, 0) + 1

    def _detect_frameworks(self, ctx: ProjectContext, root: str) -> None:
        pkg_json = os.path.join(root, "package.json")
        if os.path.exists(pkg_json):
            try:
                data = json.loads(self._read(pkg_json))
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                if "react" in deps:
                    ctx.frameworks.append("React")
                if "next" in deps:
                    ctx.frameworks.append("Next.js")
                if "vue" in deps:
                    ctx.frameworks.append("Vue")
                if "express" in deps:
                    ctx.frameworks.append("Express")
            except Exception:
                pass

        req_txt = os.path.join(root, "requirements.txt")
        if os.path.exists(req_txt):
            content = self._read(req_txt).lower()
            if "fastapi" in content:
                ctx.frameworks.append("FastAPI")
            if "django" in content:
                ctx.frameworks.append("Django")
            if "flask" in content:
                ctx.frameworks.append("Flask")

        if any(f.endswith(".bicep") for f in ctx.file_tree):
            ctx.frameworks.append("Bicep")
        if any(f.endswith(".tf") for f in ctx.file_tree):
            ctx.frameworks.append("Terraform")

    def _load_dependencies(self, ctx: ProjectContext, root: str) -> None:
        for fname in _DEPENDENCY_FILES:
            path = os.path.join(root, fname)
            if os.path.exists(path):
                ctx.dependencies[fname] = self._read(path)[:2000]

    def _load_guidelines(self, ctx: ProjectContext, root: str) -> None:
        for fname in _GUIDELINE_FILES:
            path = os.path.join(root, fname)
            if os.path.exists(path):
                ctx.guidelines[fname] = self._read(path)[:1000]

    def _load_configs(self, ctx: ProjectContext, root: str) -> None:
        for f in ctx.file_tree:
            basename = os.path.basename(f)
            if basename in {"Dockerfile", "docker-compose.yml", "docker-compose.yaml",
                           "host.json", "local.settings.json"}:
                full = os.path.join(root, f)
                ctx.config_files[f] = self._read(full)[:2000]
            elif f.endswith((".bicep", ".tf")) and len(ctx.config_files) < 10:
                full = os.path.join(root, f)
                ctx.config_files[f] = self._read(full)[:2000]

    def _load_env_vars(self, ctx: ProjectContext, root: str) -> None:
        for fname in [".env", ".env.example", ".env.local"]:
            path = os.path.join(root, fname)
            if os.path.exists(path):
                for line in self._read(path).splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        var_name = line.split("=", 1)[0].strip()
                        if var_name not in ctx.env_vars:
                            ctx.env_vars.append(var_name)

    def _build_summary(self, ctx: ProjectContext) -> None:
        top_lang = sorted(ctx.languages.items(), key=lambda x: -x[1])[:3]
        ctx.summary = (
            f"Project '{ctx.project_id}': {len(ctx.file_tree)} files, "
            f"languages: {', '.join(f'{l}({c})' for l, c in top_lang)}, "
            f"frameworks: {', '.join(ctx.frameworks) or 'none detected'}"
        )

    @staticmethod
    def _read(path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return ""


# -- Singleton ---------------------------------------------------------------

_instance: ProjectContextEngine | None = None


def get_project_context_engine() -> ProjectContextEngine:
    global _instance
    if _instance is None:
        _instance = ProjectContextEngine()
    return _instance
