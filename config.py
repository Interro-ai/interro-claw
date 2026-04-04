"""
Interro-Claw — Central Configuration

Env-variable resolution order:
  1. Session env variable  (set in the current shell / process)
  2. Global / system env variable
  3. .env file  (user's home directory: ~/.interro-claw/.env)
  4. Interactive prompt  (asks the user for LLM provider + API key)

The .env file lives OUTSIDE the package — never shipped with the install.
Default location: ~/.interro-claw/.env
Override via INTERRO_CLAW_ENV_FILE env variable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve the .env file path  (outside the package)
# ---------------------------------------------------------------------------
_HOME_DIR = Path.home() / ".interro-claw"
_ENV_FILE = os.getenv(
    "INTERRO_CLAW_ENV_FILE",
    str(_HOME_DIR / ".env"),
)

# Ensure the config directory exists
_HOME_DIR.mkdir(parents=True, exist_ok=True)

# Load .env files with lowest precedence  (won't override existing env vars)
# Precedence: session env > global env > CWD/.env > ~/.interro-claw/.env > interactive
# CWD .env loads FIRST so project-specific config wins over global defaults.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.getcwd(), ".env"),
                override=False)                     # CWD/.env (project-specific)
    load_dotenv(_ENV_FILE, override=False)          # ~/.interro-claw/.env (global fallback)
except ImportError:
    pass  # dotenv is optional — env vars still work


def _strip_quotes(val: str) -> str:
    """Remove surrounding single/double quotes that some .env editors add."""
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        return val[1:-1]
    return val

# ---------------------------------------------------------------------------
# Sentry DSN  (outside the package, saved in ~/.interro-claw/)
# ---------------------------------------------------------------------------
SENTRY_DSN: str = os.getenv("SENTRY_DSN", "")
SENTRY_TRACES_SAMPLE_RATE: float = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "1.0"))
SENTRY_ENVIRONMENT: str = os.getenv("SENTRY_ENVIRONMENT", "development")

# ---------------------------------------------------------------------------
# Data directory  (outside the package, for memory, logs, projects)
# Defaults to ~/.interro-claw/data/
# ---------------------------------------------------------------------------
DATA_DIR: str = os.getenv(
    "INTERRO_CLAW_DATA_DIR",
    str(_HOME_DIR / "data"),
)

# ---------------------------------------------------------------------------
# LLM provider selection  ("openai", "claude", "nvidia", "ollama")
# ---------------------------------------------------------------------------
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "")

# ---------------------------------------------------------------------------
# API keys / endpoints
# ---------------------------------------------------------------------------
CLAUDE_API_KEY: str = _strip_quotes(os.getenv("CLAUDE_API_KEY", ""))
CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
CLAUDE_MODEL_HEAVY: str = os.getenv("CLAUDE_MODEL_HEAVY", "claude-opus-4-20250514")

OPENAI_API_KEY: str = _strip_quotes(os.getenv("OPENAI_API_KEY", ""))
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_MODEL_LIGHT: str = os.getenv("OPENAI_MODEL_LIGHT", "gpt-4o-mini")

OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3")

NVIDIA_API_KEY: str = _strip_quotes(os.getenv("NVIDIA_API_KEY", ""))
NVIDIA_BASE_URL: str = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_MODEL: str = os.getenv("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct")
NVIDIA_MODEL_HEAVY: str = os.getenv("NVIDIA_MODEL_HEAVY", "meta/llama-3.3-70b-instruct")
NVIDIA_MODEL_LIGHT: str = os.getenv("NVIDIA_MODEL_LIGHT", "meta/llama-3.1-8b-instruct")

# ---------------------------------------------------------------------------
# Provider -> key mapping  (for interactive setup validation)
# ---------------------------------------------------------------------------
_PROVIDER_KEY_MAP: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "claude": "CLAUDE_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "ollama": "",  # no key needed
}

# ---------------------------------------------------------------------------
# Orchestrator settings
# ---------------------------------------------------------------------------
MAX_CONCURRENT_AGENTS: int = int(os.getenv("MAX_CONCURRENT_AGENTS", "2"))
RATE_LIMIT_RPM: int = int(os.getenv("RATE_LIMIT_RPM", "20"))

# ---------------------------------------------------------------------------
# Memory / SQLite
# ---------------------------------------------------------------------------
MEMORY_DB_PATH: str = os.getenv(
    "MEMORY_DB_PATH",
    os.path.join(DATA_DIR, "memory.db"),
)

# ---------------------------------------------------------------------------
# LLM response cache
# ---------------------------------------------------------------------------
ENABLE_RESPONSE_CACHE: bool = os.getenv("ENABLE_RESPONSE_CACHE", "1") == "1"
CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "3600"))

# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------
ENABLE_STREAMING: bool = os.getenv("ENABLE_STREAMING", "0") == "1"

# ---------------------------------------------------------------------------
# Self-reflection
# ---------------------------------------------------------------------------
MAX_REFLECTION_DEPTH: int = int(os.getenv("MAX_REFLECTION_DEPTH", "1"))
ENABLE_REFLECTION: bool = os.getenv("ENABLE_REFLECTION", "1") == "1"

# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------
SKILLS_DIR: str = os.getenv(
    "SKILLS_DIR",
    os.path.join(os.path.dirname(__file__), "skills"),
)

# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------
MAX_TOKENS_PER_CALL: int = int(os.getenv("MAX_TOKENS_PER_CALL", "4096"))
MAX_LLM_CALLS_PER_SESSION: int = int(os.getenv("MAX_LLM_CALLS_PER_SESSION", "200"))
MAX_OUTPUT_CHARS: int = int(os.getenv("MAX_OUTPUT_CHARS", "50000"))
MAX_AGENT_RUNTIME_SECONDS: float = float(os.getenv("MAX_AGENT_RUNTIME_SECONDS", "300"))

# ---------------------------------------------------------------------------
# Project context
# ---------------------------------------------------------------------------
DEFAULT_PROJECT_ID: str = os.getenv("DEFAULT_PROJECT_ID", "default")

# ---------------------------------------------------------------------------
# Intelligent file selection
# ---------------------------------------------------------------------------
ENABLE_FILE_SELECTION: bool = os.getenv("ENABLE_FILE_SELECTION", "1") == "1"
MAX_SELECTED_FILES: int = int(os.getenv("MAX_SELECTED_FILES", "10"))
MAX_CONTEXT_CHARS: int = int(os.getenv("MAX_CONTEXT_CHARS", "50000"))
MAX_CHUNK_SIZE: int = int(os.getenv("MAX_CHUNK_SIZE", "6000"))

# ---------------------------------------------------------------------------
# Result verification
# ---------------------------------------------------------------------------
ENABLE_VERIFICATION: bool = os.getenv("ENABLE_VERIFICATION", "1") == "1"
VERIFICATION_PASS_THRESHOLD: float = float(os.getenv("VERIFICATION_PASS_THRESHOLD", "6.0"))
VERIFICATION_MIN_DIMENSION: int = int(os.getenv("VERIFICATION_MIN_DIMENSION", "4"))

# ---------------------------------------------------------------------------
# Model Router v2
# ---------------------------------------------------------------------------
ENABLE_MODEL_ROUTING: bool = os.getenv("ENABLE_MODEL_ROUTING", "1") == "1"

# ---------------------------------------------------------------------------
# Memory hierarchy
# ---------------------------------------------------------------------------
MEMORY_RUNTIME_DIR: str = os.path.join(DATA_DIR, "memory", "runtime")
MEMORY_PROJECTS_DIR: str = os.path.join(DATA_DIR, "memory", "projects")
MEMORY_GLOBAL_DIR: str = os.path.join(DATA_DIR, "memory", "global")

# ---------------------------------------------------------------------------
# Sandbox
# ---------------------------------------------------------------------------
SANDBOX_TIMEOUT: int = int(os.getenv("SANDBOX_TIMEOUT", "30"))
SANDBOX_MAX_OUTPUT: int = int(os.getenv("SANDBOX_MAX_OUTPUT", "100000"))

# ---------------------------------------------------------------------------
# Delegation
# ---------------------------------------------------------------------------
ENABLE_DELEGATION: bool = os.getenv("ENABLE_DELEGATION", "1") == "1"
MAX_DELEGATION_DEPTH: int = int(os.getenv("MAX_DELEGATION_DEPTH", "3"))

# ---------------------------------------------------------------------------
# Human-in-the-Loop
# ---------------------------------------------------------------------------
HITL_MODE: str = os.getenv("HITL_MODE", "auto")  # auto, confirm_high_risk, confirm_all

# ---------------------------------------------------------------------------
# DAG Scheduler
# ---------------------------------------------------------------------------
ENABLE_DAG_SCHEDULING: bool = os.getenv("ENABLE_DAG_SCHEDULING", "1") == "1"

# ---------------------------------------------------------------------------
# File Indexer
# ---------------------------------------------------------------------------
ENABLE_INDEXER: bool = os.getenv("ENABLE_INDEXER", "1") == "1"

# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------
ENABLE_SNAPSHOTS: bool = os.getenv("ENABLE_SNAPSHOTS", "1") == "1"

# ---------------------------------------------------------------------------
# User application directory — where generated project files go.
# Defaults to current working directory + /interro_claw_output/
# ---------------------------------------------------------------------------
USER_APP_DIR: str = os.getenv(
    "USER_APP_DIR",
    os.path.join(os.getcwd(), "interro_claw_output"),
)

# ---------------------------------------------------------------------------
# Artifact output root  (inside USER_APP_DIR)
# ---------------------------------------------------------------------------
ARTIFACTS_DIR: str = os.path.join(USER_APP_DIR, "artifacts")

# ---------------------------------------------------------------------------
# Logging  (inside DATA_DIR — survives across projects)
# ---------------------------------------------------------------------------
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR: str = os.path.join(DATA_DIR, "logs")


# ═══════════════════════════════════════════════════════════════════════════
# Interactive setup — runs when LLM_PROVIDER or API key is missing
# ═══════════════════════════════════════════════════════════════════════════

def _is_interactive() -> bool:
    """True when stdin is a real terminal (not piped / CI)."""
    return hasattr(sys.stdin, "isatty") and sys.stdin.isatty()


def _write_env_file(key: str, value: str) -> None:
    """Append or update a key=value in the user's .env file."""
    env_path = Path(_ENV_FILE)
    lines: list[str] = []
    found = False
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                found = True
                break
    if not found:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_llm_configured() -> None:
    """
    Check that LLM_PROVIDER and its API key are set.
    If not, prompt the user interactively.
    Saves choices to ~/.interro-claw/.env for future runs.
    """
    global LLM_PROVIDER
    global OPENAI_API_KEY, CLAUDE_API_KEY, NVIDIA_API_KEY

    # Already configured — nothing to do
    if LLM_PROVIDER and _has_api_key(LLM_PROVIDER):
        return

    if not _is_interactive():
        if not LLM_PROVIDER:
            raise SystemExit(
                "ERROR: LLM_PROVIDER is not set.\n"
                "Set it via env variable, ~/.interro-claw/.env, or run interactively.\n"
                "  export LLM_PROVIDER=openai\n"
                "  export OPENAI_API_KEY=sk-..."
            )
        key_name = _PROVIDER_KEY_MAP.get(LLM_PROVIDER, "")
        if key_name:
            raise SystemExit(
                f"ERROR: {key_name} is not set for provider '{LLM_PROVIDER}'.\n"
                f"  export {key_name}=your-key-here"
            )

    # Interactive setup
    print("\n" + "=" * 60)
    print("  INTERRO-CLAW  —  First-Time Setup")
    print("=" * 60)

    if not LLM_PROVIDER:
        print("\n  Choose your LLM provider:\n")
        print("    1. openai    — OpenAI GPT-4o  (requires API key)")
        print("    2. claude    — Anthropic Claude  (requires API key)")
        print("    3. nvidia    — NVIDIA NIM free tier  (requires API key)")
        print("    4. ollama    — Local Ollama  (no API key, must be running)")
        print()

        choices = {"1": "openai", "2": "claude", "3": "nvidia", "4": "ollama"}
        while True:
            pick = input("  Enter choice [1-4]: ").strip()
            if pick in choices:
                LLM_PROVIDER = choices[pick]
                break
            if pick.lower() in _PROVIDER_KEY_MAP:
                LLM_PROVIDER = pick.lower()
                break
            print("  Invalid choice. Try again.")

        os.environ["LLM_PROVIDER"] = LLM_PROVIDER
        _write_env_file("LLM_PROVIDER", LLM_PROVIDER)
        print(f"\n  Provider set to: {LLM_PROVIDER}")

    # Ask for API key if needed
    key_env_name = _PROVIDER_KEY_MAP.get(LLM_PROVIDER, "")
    if key_env_name and not _has_api_key(LLM_PROVIDER):
        print(f"\n  Enter your {LLM_PROVIDER.upper()} API key:")
        import getpass
        api_key = getpass.getpass(f"  {key_env_name}= ").strip()
        if not api_key:
            raise SystemExit("  ERROR: API key is required. Exiting.")

        os.environ[key_env_name] = api_key
        _write_env_file(key_env_name, api_key)

        if LLM_PROVIDER == "openai":
            OPENAI_API_KEY = api_key
        elif LLM_PROVIDER == "claude":
            CLAUDE_API_KEY = api_key
        elif LLM_PROVIDER == "nvidia":
            NVIDIA_API_KEY = api_key

        print(f"  API key saved to {_ENV_FILE}")

    print(f"\n  Ready! Using {LLM_PROVIDER} provider.")
    print("=" * 60 + "\n")


def _has_api_key(provider: str) -> bool:
    """Check if the required API key is available for the given provider."""
    if provider == "openai":
        return bool(OPENAI_API_KEY)
    elif provider == "claude":
        return bool(CLAUDE_API_KEY)
    elif provider == "nvidia":
        return bool(NVIDIA_API_KEY)
    elif provider == "ollama":
        return True
    return False
