"""
Performance Profiling Layer

Provides profiling tool integration for agents to analyze code performance.

Python: cProfile, Scalene, PyInstrument
Node.js: node --prof, clinic.js, Lighthouse

Agents can invoke profiling tools and get structured results.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ProfileResult:
    tool: str
    target: str
    success: bool
    output: str
    metrics: dict[str, Any] = field(default_factory=dict)
    report_path: str = ""


class Profiler:
    """Runs profiling tools and returns structured results."""

    def __init__(self, artifacts_dir: str | None = None) -> None:
        import interro_claw.config as config
        self._artifacts = artifacts_dir or os.path.join(config.ARTIFACTS_DIR, "logs")
        os.makedirs(self._artifacts, exist_ok=True)

    # -- Python profiling ---------------------------------------------------

    def profile_python_cprofile(self, script: str, args: list[str] | None = None) -> ProfileResult:
        """Run cProfile on a Python script."""
        report = os.path.join(self._artifacts, "cprofile_report.txt")
        cmd = ["python", "-m", "cProfile", "-s", "cumulative", script] + (args or [])
        return self._run_tool("cProfile", script, cmd, report)

    def profile_python_pyinstrument(self, script: str, args: list[str] | None = None) -> ProfileResult:
        """Run PyInstrument on a Python script."""
        report = os.path.join(self._artifacts, "pyinstrument_report.html")
        cmd = ["python", "-m", "pyinstrument", "-r", "html", "-o", report, script] + (args or [])
        return self._run_tool("PyInstrument", script, cmd, report)

    def profile_python_scalene(self, script: str, args: list[str] | None = None) -> ProfileResult:
        """Run Scalene on a Python script."""
        report = os.path.join(self._artifacts, "scalene_report.json")
        cmd = ["python", "-m", "scalene", "--json", "--outfile", report, script] + (args or [])
        return self._run_tool("Scalene", script, cmd, report)

    # -- Node.js profiling --------------------------------------------------

    def profile_node(self, script: str, args: list[str] | None = None) -> ProfileResult:
        """Run Node.js with --prof flag."""
        cmd = ["node", "--prof", script] + (args or [])
        return self._run_tool("node-prof", script, cmd, "")

    def profile_lighthouse(self, url: str) -> ProfileResult:
        """Run Lighthouse CLI on a URL for frontend performance."""
        report = os.path.join(self._artifacts, "lighthouse_report.json")
        cmd = ["npx", "lighthouse", url, "--output=json", f"--output-path={report}", "--chrome-flags=--headless"]
        return self._run_tool("Lighthouse", url, cmd, report)

    # -- generic runner -----------------------------------------------------

    def _run_tool(
        self, tool: str, target: str, cmd: list[str], report_path: str
    ) -> ProfileResult:
        logger.info("Running %s on %s", tool, target)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=os.path.dirname(target) if os.path.exists(target) else None,
            )
            output = result.stdout + result.stderr
            success = result.returncode == 0
            metrics = self._parse_metrics(tool, output, report_path)
            return ProfileResult(
                tool=tool,
                target=target,
                success=success,
                output=output[:5000],
                metrics=metrics,
                report_path=report_path if os.path.exists(report_path) else "",
            )
        except FileNotFoundError:
            return ProfileResult(
                tool=tool, target=target, success=False,
                output=f"{tool} not found. Install it first.",
            )
        except subprocess.TimeoutExpired:
            return ProfileResult(
                tool=tool, target=target, success=False,
                output=f"{tool} timed out after 120s",
            )
        except Exception as exc:
            return ProfileResult(
                tool=tool, target=target, success=False,
                output=f"Error: {exc}",
            )

    def _parse_metrics(self, tool: str, output: str, report_path: str) -> dict[str, Any]:
        """Extract key metrics from profiling output."""
        metrics: dict[str, Any] = {}
        if tool == "Scalene" and report_path and os.path.exists(report_path):
            try:
                with open(report_path) as f:
                    data = json.load(f)
                metrics["scalene"] = {
                    "cpu_percent": data.get("cpu_percent_python", 0),
                    "memory_mb": data.get("max_memory_mb", 0),
                }
            except Exception:
                pass
        elif tool == "Lighthouse" and report_path and os.path.exists(report_path):
            try:
                with open(report_path) as f:
                    data = json.load(f)
                cats = data.get("categories", {})
                metrics["lighthouse"] = {
                    cat: info.get("score", 0) * 100
                    for cat, info in cats.items()
                }
            except Exception:
                pass
        return metrics

    def get_available_tools(self) -> dict[str, bool]:
        """Check which profiling tools are installed."""
        tools = {
            "cProfile": True,  # stdlib
            "pyinstrument": self._check_cmd(["python", "-m", "pyinstrument", "--version"]),
            "scalene": self._check_cmd(["python", "-m", "scalene", "--version"]),
            "node": self._check_cmd(["node", "--version"]),
            "lighthouse": self._check_cmd(["npx", "lighthouse", "--version"]),
        }
        return tools

    @staticmethod
    def _check_cmd(cmd: list[str]) -> bool:
        try:
            subprocess.run(cmd, capture_output=True, timeout=10)
            return True
        except Exception:
            return False
