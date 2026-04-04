"""
Orchestrator — the central entry point that:
1. Accepts a user goal (or resumes an incomplete session)
2. Sends it to PlannerAgent for task decomposition
3. Builds a DAG-scheduled execution plan from the plan
4. Dispatches each task to the appropriate agent via the TaskQueue
5. Logs every step to SQLite session history (with per-task memory)
6. Collects results, writes a summary (including guardrails + memory stats)

Capabilities:
- Multi-session continuity (--resume flag)
- Skills auto-injection via SkillsManager
- Enhanced Guardrails v2 with snapshot rollback
- DAG-based task scheduling with parallel batches
- Agent delegation protocol
- Human-in-the-loop checkpoints
- File indexing at startup
- Smart model routing
- Priority scheduling
- Streaming mode (--stream flag)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from typing import Any

import interro_claw.config as config
from interro_claw.llm_client import get_llm_client
from interro_claw.memory import get_memory_store, MemoryStore
from interro_claw.task_queue import Task, TaskQueue, TaskStatus
from interro_claw.guardrails import get_guardrails, Guardrails
from interro_claw.skills_manager import get_skills_manager, SkillsManager
from interro_claw.agent_tools import get_tool_registry, ToolRegistry
from interro_claw.project_context import get_project_context_engine, ProjectContextEngine
from interro_claw.file_selector import get_file_selector, FileSelector
from interro_claw.context_chunker import get_context_chunker, ContextChunker
from interro_claw.dep_graph import get_dep_graph_engine, DependencyGraphEngine
from interro_claw.result_verifier import ResultVerifier, get_result_verifier, VerificationResult

# ADS subsystems
from interro_claw.memory.short_term import get_short_term_memory
from interro_claw.memory.working import get_working_memory
from interro_claw.memory.long_term import get_long_term_memory
from interro_claw.context_engine import get_context_engine
from interro_claw.model_router import get_model_router
from interro_claw.guardrails_v2 import get_enhanced_guardrails
from interro_claw.delegation.protocol import DelegationProtocol
from interro_claw.dag_scheduler import get_dag_scheduler
from interro_claw.hitl import HumanCheckpoint, get_hitl
from interro_claw.indexer import get_file_indexer
from interro_claw.graph_engine import get_project_graph_engine

# Agents
from interro_claw.agents.planner_agent import PlannerAgent
from interro_claw.agents.architect_agent import ArchitectAgent
from interro_claw.agents.backend_agent import BackendAgent
from interro_claw.agents.frontend_agent import FrontendAgent
from interro_claw.agents.ops_agent import OpsAgent
from interro_claw.agents.test_agent import TestAgent
from interro_claw.agents.security_agent import SecurityAgent
from interro_claw.agents.refactor_agent import RefactorAgent
from interro_claw.agents.consolidator_agent import ConsolidatorAgent

# -- Logging setup ----------------------------------------------------------

os.makedirs(config.LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.join(config.LOG_DIR, "orchestrator.log"),
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("orchestrator")

# -- Agent registry ---------------------------------------------------------

AGENT_REGISTRY: dict[str, type] = {
    "ArchitectAgent": ArchitectAgent,
    "BackendAgent": BackendAgent,
    "FrontendAgent": FrontendAgent,
    "OpsAgent": OpsAgent,
    "TestAgent": TestAgent,
    "SecurityAgent": SecurityAgent,
    "RefactorAgent": RefactorAgent,
}

_AGENT_TIERS: list[set[str]] = [
    {"ArchitectAgent"},
    {"BackendAgent", "FrontendAgent"},
    {"OpsAgent"},
    {"TestAgent", "SecurityAgent"},
    {"RefactorAgent"},
]

_TIER_INDEX: dict[str, int] = {}
for idx, tier in enumerate(_AGENT_TIERS):
    for name in tier:
        _TIER_INDEX[name] = idx

# Priority mapping: earlier tiers get higher priority
_TIER_PRIORITY: dict[int, int] = {0: 10, 1: 8, 2: 6, 3: 4, 4: 2}


class Orchestrator:
    """
    Central orchestrator with multi-session continuity, skills injection,
    enhanced guardrails, DAG scheduling, delegation, HITL, and streaming.
    """

    def __init__(
        self,
        project_id: str | None = None,
        resume_session: str | None = None,
        enable_streaming: bool = False,
    ) -> None:
        self.llm = get_llm_client()
        self.memory = get_memory_store()
        self.guardrails = get_guardrails()
        self.skills = get_skills_manager(config.SKILLS_DIR)
        self.tools = get_tool_registry()
        self.project_ctx = get_project_context_engine()
        self.project_id = project_id or config.DEFAULT_PROJECT_ID
        self.streaming = enable_streaming or config.ENABLE_STREAMING
        self.queue = TaskQueue()
        self._agent_instances: dict[str, Any] = {}

        root = os.path.dirname(os.path.abspath(__file__))

        # Legacy subsystems
        self.file_selector = get_file_selector(root)
        self.context_chunker = get_context_chunker()
        self.dep_graph_engine = get_dep_graph_engine()
        self.verifier = get_result_verifier(
            self.llm,
            pass_threshold=config.VERIFICATION_PASS_THRESHOLD,
            min_dimension_score=config.VERIFICATION_MIN_DIMENSION,
        )

        # ADS: 3-layer memory
        self.stm = get_short_term_memory()
        self.working_mem = get_working_memory(self.project_id)
        self.ltm = get_long_term_memory()

        # ADS: Intelligence layer
        self.context_engine = get_context_engine(root)
        self.model_router = get_model_router()
        self.graph_engine = get_project_graph_engine()

        # ADS: Enhanced guardrails
        self.enhanced_guardrails = get_enhanced_guardrails()

        # ADS: DAG scheduler
        self.dag_scheduler = get_dag_scheduler()

        # ADS: Delegation protocol
        self.delegation = DelegationProtocol()
        if config.ENABLE_DELEGATION:
            self.delegation.set_dispatch_fn(self._delegation_dispatch)

        # ADS: Human-in-the-loop
        self.hitl = get_hitl()

        # ADS: File indexer
        self.indexer = get_file_indexer(root)
        if config.ENABLE_INDEXER:
            try:
                self.indexer.index()
                self.indexer.persist_to_working_memory(self.working_mem)
                logger.info("File indexer: indexed project files")
            except Exception as exc:
                logger.warning("File indexer failed: %s", exc)

        # Multi-session continuity
        if resume_session:
            self.session_id = resume_session
            logger.info("Resuming session: %s", self.session_id)
        else:
            self.session_id = uuid.uuid4().hex[:12]

        # Analyze project context at startup
        try:
            self.project_ctx.analyze(root, self.project_id)
            logger.info("Project context analyzed for '%s'", self.project_id)
        except Exception as exc:
            logger.warning("Project context analysis failed: %s", exc)

        logger.info(
            "Skills loaded: %d | Guardrails: max_llm=%d, max_reflect=%d | ADS: delegation=%s dag=%s hitl=%s",
            len(self.skills.all_skills),
            self.guardrails.cfg.max_total_llm_calls_per_session,
            self.guardrails.cfg.max_reflection_depth,
            config.ENABLE_DELEGATION,
            config.ENABLE_DAG_SCHEDULING,
            config.HITL_MODE,
        )

    # -- main entry ---------------------------------------------------------

    async def run(self, goal: str) -> list[Task]:
        # Reset asyncio-bound objects so they belong to the current event loop
        self.queue = TaskQueue()
        self.delegation = DelegationProtocol()
        if config.ENABLE_DELEGATION:
            self.delegation.set_dispatch_fn(self._delegation_dispatch)
        # Clear cached agent instances so they pick up the new delegation protocol
        self._agent_instances.clear()

        logger.info("=" * 72)
        logger.info("Session %s | Project %s | Goal: %s", self.session_id, self.project_id, goal)
        logger.info("=" * 72)

        # Default step log (visible without --verbose)
        print(f"  [Session] {self.session_id} | Project: {self.project_id}", flush=True)

        # Check if resuming — get pending tasks from previous session
        pending_entries = self.memory.get_session_pending_tasks(self.session_id)
        if pending_entries:
            logger.info("Found %d pending tasks from previous session", len(pending_entries))
            print(f"  [Resume] Found {len(pending_entries)} pending tasks from previous session", flush=True)
            tasks = self._resume_tasks(pending_entries)
        else:
            # Step 1 — Plan
            print("\n  [Planning] Breaking down your goal into tasks ...", flush=True)
            plan = await self.planner.run(goal)
            logger.info("Plan (%d tasks):\n%s", len(plan), json.dumps(plan, indent=2))

            # Show the plan to the user before execution
            self._print_plan(plan)

            # HITL: post-plan checkpoint
            self.hitl.checkpoint(
                stage="post_plan",
                agent_name="Orchestrator",
                summary=f"Plan generated with {len(plan)} tasks",
                risk_score=0.3,
            )

            # Step 2 — Build dependency graph + enqueue
            if config.ENABLE_DAG_SCHEDULING:
                tasks = self._build_dag_tasks(plan)
            else:
                tasks = self._build_dependency_graph(plan)

        for t in tasks:
            self.queue.add(t)
            self.memory.log_session(
                session_id=self.session_id,
                task_id=t.id,
                agent_name=t.agent_name,
                task_description=t.description,
                status="pending",
                project_id=self.project_id,
                goal=goal,
            )

        # HITL: pre-execute checkpoint
        self.hitl.checkpoint(
            stage="pre_execute",
            agent_name="Orchestrator",
            summary=f"About to execute {len(tasks)} tasks",
            risk_score=0.5,
        )

        # Step 3 — Execute
        logger.info("Phase 2: Executing %d tasks (priority + dependency aware) ...", len(tasks))
        print(f"\n  [Execute] Running {len(tasks)} tasks across agents ...", flush=True)
        start = time.monotonic()
        results = await self.queue.execute_all(self._dispatch)
        elapsed = time.monotonic() - start
        logger.info("All tasks finished in %.1f s", elapsed)

        passed = sum(1 for t in results if t.status.value == "completed")
        failed = sum(1 for t in results if t.status.value == "failed")
        print(f"  [Done] {passed} passed, {failed} failed — {elapsed:.1f}s total", flush=True)

        # Step 4 — Update session history
        for t in results:
            self.memory.log_session(
                session_id=self.session_id,
                task_id=t.id,
                agent_name=t.agent_name,
                task_description=t.description,
                response=(t.result or "")[:500],
                status=t.status.value,
                elapsed_ms=t.elapsed_ms,
                project_id=self.project_id,
                goal=goal,
            )

        # Drain any pending delegation requests (non-blocking)
        if config.ENABLE_DELEGATION:
            pending = self.delegation.get_pending()
            for req in pending:
                try:
                    await self.delegation._execute(req)
                except Exception as exc:
                    logger.warning("Delegation request %s failed: %s", req.id, exc)

        # Step 5 — Summary
        try:
            self._write_summary(results, elapsed)
        except Exception as exc:
            logger.error("Summary write failed: %s", exc, exc_info=True)
            print(f"\n  [Warning] Could not write summary: {exc}", flush=True)

        # Step 6 — Consolidator: produce user-facing summary
        print("\n  [Consolidating] Preparing your report ...", flush=True)
        try:
            report = await self.consolidator.consolidate(goal, results, elapsed)
            self._last_report = report
        except Exception as exc:
            logger.warning("Consolidator failed: %s", exc, exc_info=True)
            self._last_report = None
            # Fall back to a basic text summary so the user always sees something
            self._last_report = self._fallback_report(results, elapsed)

        return results

    def _fallback_report(self, tasks: list[Task], elapsed: float) -> str:
        """Basic text report when the consolidator LLM call fails."""
        lines = [
            "\n" + "=" * 60,
            "  SESSION SUMMARY (consolidator unavailable)",
            "=" * 60,
            f"  Time: {elapsed:.1f}s | Tasks: {len(tasks)}",
        ]
        for t in tasks:
            status = t.status.value if hasattr(t.status, "value") else str(t.status)
            lines.append(f"  - [{status.upper()}] {t.agent_name}: {t.description[:60]}")
            if t.error:
                lines.append(f"    Error: {t.error[:80]}")
        artifacts_dir = config.ARTIFACTS_DIR
        if os.path.isdir(artifacts_dir):
            files = []
            for dp, _, fns in os.walk(artifacts_dir):
                for fn in fns:
                    files.append(os.path.relpath(os.path.join(dp, fn), config.USER_APP_DIR))
            if files:
                lines.append(f"\n  Generated {len(files)} files in: {os.path.abspath(config.USER_APP_DIR)}")
                for f in sorted(files)[:20]:
                    lines.append(f"    {f}")
        lines.append("=" * 60)
        return "\n".join(lines)

    @property
    def consolidator(self) -> ConsolidatorAgent:
        return ConsolidatorAgent(
            llm_client=self.llm,
            memory=self.memory,
            guardrails=self.guardrails,
            skills=self.skills,
            tools=self.tools,
            project_context_engine=self.project_ctx,
            file_selector=self.file_selector,
            context_chunker=self.context_chunker,
            dep_graph_engine=self.dep_graph_engine,
            short_term_memory=self.stm,
            working_memory=self.working_mem,
            long_term_memory=self.ltm,
            context_engine=self.context_engine,
            model_router=self.model_router,
            enhanced_guardrails=self.enhanced_guardrails,
            delegation_protocol=self.delegation,
            project_id=self.project_id,
            session_id=self.session_id,
        )

    @property
    def planner(self) -> PlannerAgent:
        return PlannerAgent(
            llm_client=self.llm,
            memory=self.memory,
            guardrails=self.guardrails,
            skills=self.skills,
            tools=self.tools,
            project_context_engine=self.project_ctx,
            file_selector=self.file_selector,
            context_chunker=self.context_chunker,
            dep_graph_engine=self.dep_graph_engine,
            short_term_memory=self.stm,
            working_memory=self.working_mem,
            long_term_memory=self.ltm,
            context_engine=self.context_engine,
            model_router=self.model_router,
            enhanced_guardrails=self.enhanced_guardrails,
            delegation_protocol=self.delegation,
            project_id=self.project_id,
            session_id=self.session_id,
        )

    # -- resume from previous session ---------------------------------------

    def _resume_tasks(self, pending: list) -> list[Task]:
        """Rebuild Task objects from pending session entries."""
        tasks: list[Task] = []
        for entry in pending:
            tier = _TIER_INDEX.get(entry.agent_name, 0)
            task = Task(
                id=entry.task_id,
                description=entry.task_description,
                agent_name=entry.agent_name,
                priority=_TIER_PRIORITY.get(tier, 5),
            )
            tasks.append(task)
        return tasks

    # -- dependency graph ---------------------------------------------------

    @staticmethod
    def _build_dependency_graph(plan: list[dict[str, str]]) -> list[Task]:
        tasks: list[Task] = []
        tier_tasks: dict[int, list[str]] = {}

        for idx, item in enumerate(plan):
            agent = item.get("agent", "ArchitectAgent")
            task_id = f"task-{idx:03d}"
            tier = _TIER_INDEX.get(agent, 0)
            priority = _TIER_PRIORITY.get(tier, 5)

            deps: list[str] = []
            for earlier_tier in range(tier):
                deps.extend(tier_tasks.get(earlier_tier, []))

            task = Task(
                id=task_id,
                description=item.get("task", ""),
                agent_name=agent,
                depends_on=deps,
                priority=priority,
            )
            tasks.append(task)
            tier_tasks.setdefault(tier, []).append(task_id)

        return tasks

    # -- DAG-based scheduling -----------------------------------------------

    def _build_dag_tasks(self, plan: list[dict[str, str]]) -> list[Task]:
        """Use DAGScheduler for proper topological ordering with parallel batches."""
        execution_plan = self.dag_scheduler.build_dag(plan)
        node_map = {n.id: n for n in execution_plan.nodes}
        tasks: list[Task] = []
        for batch_idx, batch in enumerate(execution_plan.batches):
            for task_id in batch:
                node = node_map[task_id]
                priority = max(10 - batch_idx * 2, 1)
                task = Task(
                    id=node.id,
                    description=node.description,
                    agent_name=node.agent_name,
                    depends_on=list(node.depends_on),
                    priority=priority,
                )
                tasks.append(task)
        logger.info("DAG scheduler: %d tasks in %d batches",
                     len(tasks), len(execution_plan.batches))
        return tasks

    # -- delegation dispatch ------------------------------------------------

    async def _delegation_dispatch(self, agent_name: str, task: str, context: dict | None) -> str:
        """Called by DelegationProtocol when an agent delegates to another."""
        logger.info("[Delegation] %s delegated to %s: %s", context.get("from", "?") if context else "?", agent_name, task[:60])
        print(f"  [Delegation] -> {agent_name}: {task[:60]} ...", flush=True)
        agent = self._get_agent(agent_name)
        return await agent.run(
            task,
            context=context,
            enable_reflection=config.ENABLE_REFLECTION,
            enable_tools=True,
            stream=self.streaming,
        )

    # -- dispatch -----------------------------------------------------------

    async def _dispatch(self, task: Task) -> str:
        agent = self._get_agent(task.agent_name)

        # Default step log (always visible)
        print(f"  [{task.agent_name}] Working on: {task.description[:80]} ...", flush=True)

        # Verbose: show model routing decision
        logger.info("[%s] START task=%s desc=%s", task.agent_name, task.id, task.description[:60])
        if config.ENABLE_MODEL_ROUTING:
            route = self.model_router.route(task.agent_name, task.description)
            logger.info("[%s] Model route: %s/%s (%s)", task.agent_name, route.provider, route.model, route.complexity.value)

        # Snapshot before execution (if enabled)
        if config.ENABLE_SNAPSHOTS:
            self.enhanced_guardrails.snapshot_manager.take_snapshot(
                file_path=f"pre_task_{task.id}",
                session_id=self.session_id,
                agent_name=task.agent_name,
            )

        result = await agent.run(
            task.description,
            task_id=task.id,
            enable_reflection=config.ENABLE_REFLECTION,
            enable_tools=True,
            stream=self.streaming,
        )
        logger.info("[%s] FINISH task=%s result_len=%d", task.agent_name, task.id, len(result or ""))
        agent.publish(
            topic=task.agent_name.replace("Agent", "").lower(),
            fact=f"Completed: {task.description[:200]}",
            confidence=0.9,
        )

        # Result verification
        if config.ENABLE_VERIFICATION:
            try:
                verification = await self.verifier.verify(
                    agent_name=task.agent_name,
                    task_title=task.description[:120],
                    task_description=task.description,
                    agent_output=result,
                )
                status = "PASS" if verification.passed else "FAIL"
                print(f"  [{task.agent_name}] Done ({status}, score={verification.average_score:.1f})", flush=True)
                logger.info(
                    "[Verifier] %s | avg=%.1f passed=%s",
                    task.agent_name, verification.average_score, verification.passed,
                )
                if not verification.passed:
                    logger.warning(
                        "[Verifier] FAILED for %s:\n%s",
                        task.agent_name, verification.summary(),
                    )
            except Exception as exc:
                print(f"  [{task.agent_name}] Done", flush=True)
                logger.debug("Verification skipped: %s", exc)
        else:
            print(f"  [{task.agent_name}] Done", flush=True)

        return result

    def _get_agent(self, name: str) -> Any:
        if name not in self._agent_instances:
            cls = AGENT_REGISTRY.get(name)
            if cls is None:
                logger.warning("Unknown agent '%s', falling back to ArchitectAgent", name)
                cls = ArchitectAgent
            self._agent_instances[name] = cls(
                llm_client=self.llm,
                memory=self.memory,
                guardrails=self.guardrails,
                skills=self.skills,
                tools=self.tools,
                project_context_engine=self.project_ctx,
                file_selector=self.file_selector,
                context_chunker=self.context_chunker,
                dep_graph_engine=self.dep_graph_engine,
                short_term_memory=self.stm,
                working_memory=self.working_mem,
                long_term_memory=self.ltm,
                context_engine=self.context_engine,
                model_router=self.model_router,
                enhanced_guardrails=self.enhanced_guardrails,
                delegation_protocol=self.delegation,
                project_id=self.project_id,
                session_id=self.session_id,
            )
        return self._agent_instances[name]

    # -- plan display -------------------------------------------------------

    @staticmethod
    def _print_plan(plan: list[dict[str, str]]) -> None:
        """Show the plan to the user before execution starts."""
        sep = "=" * 72
        print(f"\n{sep}")
        print(f"  EXECUTION PLAN ({len(plan)} tasks)")
        print(sep)
        for idx, item in enumerate(plan, 1):
            agent = item.get("agent", "?")
            task_desc = item.get("task", "?")
            print(f"  {idx}. [{agent}] {task_desc[:70]}")
        print(f"{sep}")
        print(f"  Starting execution ...\n", flush=True)

    # -- summary report -----------------------------------------------------

    def _write_summary(self, tasks: list[Task], elapsed: float) -> None:
        mem_stats = self.memory.get_stats()
        gr_stats = self.guardrails.get_stats()
        completed = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in tasks if t.status == TaskStatus.FAILED)
        summary = {
            "session_id": self.session_id,
            "project_id": self.project_id,
            "elapsed_seconds": round(elapsed, 2),
            "total": len(tasks),
            "completed": completed,
            "failed": failed,
            "memory": mem_stats,
            "guardrails": gr_stats,
            "skills_loaded": len(self.skills.all_skills),
            "tasks": [
                {
                    "id": t.id,
                    "agent": t.agent_name,
                    "status": t.status.value,
                    "priority": t.priority,
                    "description": t.description[:120],
                    "depends_on": t.depends_on,
                    "elapsed_ms": t.elapsed_ms,
                    "error": t.error,
                }
                for t in tasks
            ],
        }
        path = os.path.join(config.ARTIFACTS_DIR, "logs", "run_summary.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        logger.info("Run summary -> %s", path)

        logger.info(
            "Summary: %d/%d completed, %d failed (%.1fs) | LLM calls: %d | Memory: %s",
            completed,
            summary["total"],
            failed,
            elapsed,
            gr_stats["llm_calls"],
            json.dumps(mem_stats),
        )

        # --- Print user-facing final report to terminal ---
        self._print_final_report(tasks, elapsed, completed, failed)

    def _print_final_report(
        self, tasks: list[Task], elapsed: float, completed: int, failed: int,
    ) -> None:
        """Print a clear, human-readable report to stdout."""
        sep = "=" * 72
        print(f"\n{sep}")
        print(f"  SESSION COMPLETE — {self.session_id}")
        print(sep)
        print(f"  Time: {elapsed:.1f}s | Tasks: {completed}/{len(tasks)} completed", end="")
        if failed:
            print(f" | {failed} FAILED", end="")
        print()
        print(sep)

        # Task-by-task status
        print("\n  TASK RESULTS:")
        print(f"  {'ID':<12} {'Agent':<20} {'Status':<12} {'Time':>8}  Description")
        print(f"  {'-'*10}   {'-'*18}   {'-'*10}   {'-'*6}  {'-'*30}")
        for t in tasks:
            status_icon = {
                TaskStatus.COMPLETED: "DONE",
                TaskStatus.FAILED: "FAIL",
            }.get(t.status, t.status.value.upper())
            time_str = f"{t.elapsed_ms / 1000:.1f}s" if t.elapsed_ms else "-"
            print(f"  {t.id:<12} {t.agent_name:<20} {status_icon:<12} {time_str:>8}  {t.description[:50]}")
            if t.error:
                print(f"  {'':12} {'':20} ERROR: {t.error[:60]}")

        # List generated files
        artifacts_dir = config.ARTIFACTS_DIR
        generated_files: list[str] = []
        if os.path.isdir(artifacts_dir):
            for dirpath, _, filenames in os.walk(artifacts_dir):
                for fn in filenames:
                    full = os.path.join(dirpath, fn)
                    rel = os.path.relpath(full, config.USER_APP_DIR)
                    generated_files.append(rel)

        if generated_files:
            print(f"\n  GENERATED FILES ({len(generated_files)}):")
            for f in sorted(generated_files):
                print(f"    {f}")

        # Next steps
        print(f"\n  OUTPUT DIRECTORY: {os.path.abspath(config.USER_APP_DIR)}")
        print(f"  FULL REPORT:     {os.path.join(config.ARTIFACTS_DIR, 'logs', 'run_summary.json')}")
        if failed:
            print(f"\n  NOTE: {failed} task(s) failed. You can retry with:")
            print(f"    python orchestrator.py --resume {self.session_id} \"<your goal>\"")
        print(f"\n  To continue this session:")
        print(f"    python orchestrator.py --resume {self.session_id} \"<next instruction>\"")
        print(f"{sep}\n")


# -- CLI entry point --------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Multi-Agent Orchestrator")
    parser.add_argument("goal", nargs="*", help="The goal to accomplish")
    parser.add_argument("--resume", type=str, default=None, help="Resume a previous session by ID")
    parser.add_argument("--project", type=str, default=None, help="Project ID for memory scoping")
    parser.add_argument("--stream", action="store_true", help="Enable streaming responses")
    parser.add_argument("--auto-resume", action="store_true", help="Auto-resume last incomplete session")
    args = parser.parse_args()

    project_id = args.project or config.DEFAULT_PROJECT_ID
    resume_session = args.resume

    # Auto-resume: find last incomplete session
    if args.auto_resume and not resume_session:
        store = get_memory_store()
        resume_session = store.find_incomplete_session(project_id)
        if resume_session:
            print(f"Auto-resuming session: {resume_session}")

    if not args.goal and not resume_session:
        parser.print_help()
        print('\nExample: python orchestrator.py "Build a web application hosted in Azure"')
        print('         python orchestrator.py --resume abc123 "Continue building"')
        print('         python orchestrator.py --auto-resume "Continue where we left off"')
        sys.exit(1)

    goal = " ".join(args.goal) if args.goal else ""
    if resume_session and not goal:
        store = get_memory_store()
        goal = store.get_session_goal(resume_session) or "Continue previous session"

    orchestrator = Orchestrator(
        project_id=project_id,
        resume_session=resume_session,
        enable_streaming=args.stream,
    )

    try:
        results = asyncio.run(orchestrator.run(goal))
    except Exception as exc:
        print(f"\n  [Error] Orchestrator run failed: {exc}", flush=True)
        import traceback
        traceback.print_exc()
        results = []

    # Print the consolidator report
    report = getattr(orchestrator, "_last_report", None)
    if report:
        print("\n" + report, flush=True)

    # Interactive loop — ask user what to do next
    _interactive_loop(orchestrator)


def _interactive_loop(orchestrator: Orchestrator) -> None:
    """Keep the session alive so the user can ask follow-up questions."""
    sep = "=" * 72
    print(f"\n{sep}")
    print("  INTERACTIVE MODE — type your next instruction, or 'quit' to exit.")
    print(f"{sep}")

    while True:
        try:
            user_input = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSession ended.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Session ended. Your files are in:", os.path.abspath(config.USER_APP_DIR))
            break

        # Run a new goal in the same session (preserves memory + context)
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                results = loop.run_until_complete(orchestrator.run(user_input))
            finally:
                loop.close()
            report = getattr(orchestrator, "_last_report", None)
            if report:
                print("\n" + report)
        except Exception as exc:
            print(f"\nError: {exc}")
            print("You can try again or type 'quit' to exit.")


if __name__ == "__main__":
    main()
