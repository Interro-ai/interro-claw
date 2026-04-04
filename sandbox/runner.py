"""
Execution Sandbox

Safe code runner with:
- Subprocess isolation (no eval/exec)
- Timeout enforcement
- stdout/stderr capture
- Support for Python, Node.js, shell commands
- Working directory isolation
- Resource limits (output size)
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30  # seconds
_MAX_OUTPUT_SIZE = 100_000  # characters


class Language(str, Enum):
    PYTHON = "python"
    NODEJS = "node"
    SHELL = "shell"


@dataclass
class SandboxResult:
    """Result of a sandboxed execution."""
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    elapsed_ms: int
    timed_out: bool = False
    language: str = ""

    @property
    def output(self) -> str:
        return self.stdout if self.success else self.stderr or self.stdout


class SandboxRunner:
    """Runs code in isolated subprocesses with timeout and output capture."""

    def __init__(
        self,
        timeout: int = _DEFAULT_TIMEOUT,
        max_output: int = _MAX_OUTPUT_SIZE,
        work_dir: str | None = None,
    ) -> None:
        self._timeout = timeout
        self._max_output = max_output
        if work_dir is None:
            import interro_claw.config as _cfg
            work_dir = os.path.join(_cfg.USER_APP_DIR, "sandbox")
        self._work_dir = work_dir
        os.makedirs(self._work_dir, exist_ok=True)

    async def run_python(self, code: str, timeout: int | None = None) -> SandboxResult:
        """Execute Python code in a subprocess."""
        # Write code to temporary file for safety (never eval/exec)
        tmp = os.path.join(self._work_dir, f"_run_{int(time.time()*1000)}.py")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(code)
        try:
            return await self._execute(["python", tmp], Language.PYTHON, timeout)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    async def run_node(self, code: str, timeout: int | None = None) -> SandboxResult:
        """Execute Node.js code in a subprocess."""
        tmp = os.path.join(self._work_dir, f"_run_{int(time.time()*1000)}.js")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(code)
        try:
            return await self._execute(["node", tmp], Language.NODEJS, timeout)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    async def run_shell(self, command: str, timeout: int | None = None) -> SandboxResult:
        """Execute a shell command."""
        return await self._execute(command, Language.SHELL, timeout, shell=True)

    async def run_file(
        self,
        file_path: str,
        language: Language | None = None,
        timeout: int | None = None,
    ) -> SandboxResult:
        """Execute an existing file."""
        if not os.path.exists(file_path):
            return SandboxResult(
                success=False, stdout="", stderr=f"File not found: {file_path}",
                exit_code=1, elapsed_ms=0, language=str(language or ""),
            )

        if language is None:
            ext = os.path.splitext(file_path)[1].lower()
            language = {
                ".py": Language.PYTHON,
                ".js": Language.NODEJS,
                ".ts": Language.NODEJS,
            }.get(ext, Language.SHELL)

        if language == Language.PYTHON:
            cmd = ["python", file_path]
        elif language == Language.NODEJS:
            cmd = ["node", file_path]
        else:
            cmd = [file_path]

        return await self._execute(cmd, language, timeout)

    async def _execute(
        self,
        cmd: list[str] | str,
        language: Language,
        timeout: int | None = None,
        shell: bool = False,
    ) -> SandboxResult:
        """Core execution with timeout and output capture."""
        t = timeout or self._timeout
        start = time.monotonic()

        try:
            if shell:
                proc = await asyncio.create_subprocess_shell(
                    cmd if isinstance(cmd, str) else " ".join(cmd),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self._work_dir,
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self._work_dir,
                )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=t
                )
                timed_out = False
            except asyncio.TimeoutError:
                proc.kill()
                stdout_bytes, stderr_bytes = await proc.communicate()
                timed_out = True

            elapsed = int((time.monotonic() - start) * 1000)
            stdout = (stdout_bytes or b"").decode("utf-8", errors="replace")[:self._max_output]
            stderr = (stderr_bytes or b"").decode("utf-8", errors="replace")[:self._max_output]
            exit_code = proc.returncode or 0

            return SandboxResult(
                success=exit_code == 0 and not timed_out,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                elapsed_ms=elapsed,
                timed_out=timed_out,
                language=language.value,
            )

        except FileNotFoundError:
            return SandboxResult(
                success=False,
                stdout="",
                stderr=f"Command not found: {cmd}",
                exit_code=127,
                elapsed_ms=int((time.monotonic() - start) * 1000),
                language=language.value,
            )
        except Exception as e:
            return SandboxResult(
                success=False,
                stdout="",
                stderr=str(e),
                exit_code=1,
                elapsed_ms=int((time.monotonic() - start) * 1000),
                language=language.value,
            )

    @property
    def work_dir(self) -> str:
        return self._work_dir


# -- Singleton ---------------------------------------------------------------

_instance: SandboxRunner | None = None


def get_sandbox() -> SandboxRunner:
    global _instance
    if _instance is None:
        _instance = SandboxRunner()
    return _instance
