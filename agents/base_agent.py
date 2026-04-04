"""
Base class for all agents.

Capabilities:
- LLM interaction with persistent memory
- 3-layer memory hierarchy (short-term, working, long-term)
- Self-reflection loop (agent critiques own output, optionally re-runs)
- Skills injection (auto-loaded .md skill files)
- Tool use (parse tool invocations from LLM output, execute them)
- Unified context engine (selective file injection + chunking + graph)
- Smart model routing (complexity-based model selection)
- Guardrails v2 (snapshots, bad-pattern detection, rollback)
- Agent delegation (request help from other agents)
- Sandbox execution
- Streaming support
"""

from __future__ import annotations

import json
import logging
import os
import re
from abc import ABC
from typing import Any

import interro_claw.config as config
from interro_claw.llm_client import BaseLLMClient, get_llm_client
from interro_claw.memory import MemoryStore, get_memory_store
from interro_claw.guardrails import Guardrails, get_guardrails
from interro_claw.skills_manager import SkillsManager, get_skills_manager
from interro_claw.agent_tools import ToolRegistry, ToolResult, get_tool_registry
from interro_claw.project_context import ProjectContextEngine, get_project_context_engine
from interro_claw.file_selector import FileSelector, get_file_selector
from interro_claw.context_chunker import ContextChunker, get_context_chunker
from interro_claw.dep_graph import DependencyGraphEngine, get_dep_graph_engine
from interro_claw.memory.short_term import ShortTermMemory, get_short_term_memory
from interro_claw.memory.working import WorkingMemory, get_working_memory
from interro_claw.memory.long_term import LongTermMemory, get_long_term_memory
from interro_claw.context_engine import UnifiedContextEngine, get_context_engine
from interro_claw.model_router import SmartModelRouter, get_model_router
from interro_claw.guardrails_v2 import EnhancedGuardrails, get_enhanced_guardrails

logger = logging.getLogger(__name__)

_MEMORY_RECALL_LIMIT = 10
_KNOWLEDGE_RECALL_LIMIT = 10
_MAX_TOOL_ITERATIONS = 5  # max tool-use round-trips per run


class BaseAgent(ABC):
    """
    Every specialised agent inherits from this.

    Subclasses must set:
        name            - human-readable agent name
        system_prompt   - the LLM system prompt
        output_subdir   - folder under artifacts/ for this agent's output
    """

    name: str = "BaseAgent"
    system_prompt: str = "You are a helpful assistant."
    output_subdir: str = ""

    def __init__(
        self,
        llm_client: BaseLLMClient | None = None,
        memory: MemoryStore | None = None,
        guardrails: Guardrails | None = None,
        skills: SkillsManager | None = None,
        tools: ToolRegistry | None = None,
        project_context_engine: ProjectContextEngine | None = None,
        file_selector: FileSelector | None = None,
        context_chunker: ContextChunker | None = None,
        dep_graph_engine: DependencyGraphEngine | None = None,
        short_term_memory: ShortTermMemory | None = None,
        working_memory: WorkingMemory | None = None,
        long_term_memory: LongTermMemory | None = None,
        context_engine: UnifiedContextEngine | None = None,
        model_router: SmartModelRouter | None = None,
        enhanced_guardrails: EnhancedGuardrails | None = None,
        delegation_protocol: Any | None = None,
        project_id: str = "default",
        session_id: str = "",
    ) -> None:
        self.llm = llm_client or get_llm_client()
        self.memory = memory or get_memory_store()
        self.guardrails = guardrails or get_guardrails()
        self.skills = skills or get_skills_manager()
        self.tools = tools or get_tool_registry()
        self.project_ctx_engine = project_context_engine or get_project_context_engine()
        root = os.path.dirname(os.path.dirname(__file__))
        self.file_selector = file_selector or get_file_selector(root)
        self.context_chunker = context_chunker or get_context_chunker()
        self.dep_graph_engine = dep_graph_engine or get_dep_graph_engine()
        # 3-layer memory
        self.stm = short_term_memory or get_short_term_memory()
        self.working_mem = working_memory or get_working_memory(project_id)
        self.ltm = long_term_memory or get_long_term_memory()
        # New subsystems
        self.context_engine = context_engine or get_context_engine(root)
        self.model_router = model_router or get_model_router()
        self.enhanced_guardrails = enhanced_guardrails or get_enhanced_guardrails()
        self.delegation = delegation_protocol
        self.project_id = project_id
        self.session_id = session_id
        self._output_dir = os.path.join(config.ARTIFACTS_DIR, self.output_subdir)
        os.makedirs(self._output_dir, exist_ok=True)

    # -- public API ---------------------------------------------------------

    async def run(
        self,
        task: str,
        context: dict[str, Any] | None = None,
        task_id: str = "",
        enable_reflection: bool = True,
        enable_tools: bool = True,
        stream: bool = False,
    ) -> str:
        """Execute the agent's task with reflection, tools, and guardrails."""
        task_id = task_id or f"{self.name}_{id(task)}"

        # --- STM: record task start ---
        self.stm.store(self.name, task_id, "task", task[:2000])

        # --- Model routing ---
        if config.ENABLE_MODEL_ROUTING:
            routed = self.model_router.route(self.name, task)
            logger.info("[%s] Model router → %s (complexity=%s)",
                        self.name, routed.model, routed.complexity.name)

        full_system = self._build_system_prompt(task)
        user_message = self._build_user_message(task, context)

        logger.info("[%s] Running task: %s", self.name, task[:120])

        # Step 1 — Initial LLM call
        if stream:
            response = await self._chat_streaming(full_system, user_message)
        else:
            response = await self.llm.chat(full_system, user_message)

        # Log initial reasoning to task memory
        if self.session_id and task_id:
            self.memory.store_task_memory(
                session_id=self.session_id, task_id=task_id,
                agent_name=self.name, action="reasoning",
                content=response[:2000], step=0,
                project_id=self.project_id,
            )

        # Store reasoning step in working memory
        self.working_mem.add_reasoning_step(
            chain_id=task_id,
            step=0,
            agent_name=self.name,
            thought=response[:2000],
        )

        # Step 2 — Tool use loop
        if enable_tools:
            response = await self._tool_use_loop(
                response, full_system, user_message, task_id,
            )

        # Step 3 — Self-reflection loop
        if enable_reflection:
            response = await self._reflection_loop(
                task, response, full_system, task_id,
            )

        # Step 4 — Enhanced guardrails validation
        response = self.guardrails.check_output_size(response)

        # Persist reasoning to long-term memory + legacy memory
        self.memory.store_agent_memory(
            agent_name=self.name,
            content=response[:2000],
            category="reasoning",
            metadata={"task": task[:200]},
            project_id=self.project_id,
        )

        await self._post_process(task, response)

        # --- STM: clear ephemeral task data ---
        self.stm.clear(self.name, task_id)

        return response

    # -- system prompt construction -----------------------------------------

    def _build_system_prompt(self, task: str) -> str:
        """Build enriched system prompt with skills, tools, memory layers, and project context.

        Enforces a total character budget (MAX_CONTEXT_CHARS) to prevent context
        window overflow and LLM hallucination from overly large prompts.
        """
        budget = config.MAX_CONTEXT_CHARS
        parts = [self.system_prompt]
        used = len(self.system_prompt)

        def _add(section: str) -> None:
            nonlocal used
            if section and used + len(section) < budget:
                parts.append("\n" + section)
                used += len(section) + 1

        # Inject matched skills
        _add(self.skills.format_skills_prompt(self.name, task))

        # Inject tool descriptions
        tools_desc = self.tools.describe_tools()
        if tools_desc:
            tool_block = (
                tools_desc + "\n"
                "\nTo use a tool, output a JSON block like:\n"
                '```tool\n{"tool": "tool_name", "args": {"param": "value"}}\n```\n'
                "You may use multiple tool blocks. Results will be provided back to you."
            )
            _add(tool_block)

        # Inject long-term memory patterns & style
        _add(self.ltm.to_prompt_section())

        # Inject working memory (project-level context)
        _add(self.working_mem.to_prompt_section())

        # Inject project context + project graph
        try:
            root = os.path.dirname(os.path.dirname(__file__))
            ctx = self.project_ctx_engine.analyze(root)
            _add(ctx.to_prompt_section())
            graph = self.dep_graph_engine.query(root, self.project_id)
            _add(graph.to_prompt_section())
        except Exception:
            pass  # Don't fail if project scan fails

        if used >= budget:
            logger.warning("[%s] System prompt at budget limit (%d/%d chars)", self.name, used, budget)

        return "\n".join(parts)

    def _build_user_message(self, task: str, context: dict[str, Any] | None) -> str:
        """Build the user message enriched with memory + knowledge.

        Respects a character budget so the combined system+user prompt
        does not blow through the LLM context window.
        """
        # Reserve half the budget for user message (system prompt gets the other half)
        budget = config.MAX_CONTEXT_CHARS // 2
        parts: list[str] = []
        used = 0

        def _add(section: str) -> None:
            nonlocal used
            if section and used + len(section) < budget:
                parts.append(section)
                used += len(section)

        # Recall past reasoning (limit to 5 most recent to save budget)
        past = self.memory.recall_agent_memory(
            self.name, limit=5, project_id=self.project_id,
        )
        if past:
            lines = ["## Your past reasoning (most recent first)"]
            for m in past:
                lines.append(f"- [{m.category}] {m.content[:200]}")
            lines.append("")
            _add("\n".join(lines))

        # Semantic search for relevant memories
        similar = self.memory.semantic_search(
            query=task, source_table="agent_memory", limit=3, min_score=0.2,
        )
        if similar:
            lines = ["## Semantically related past work"]
            for s in similar:
                lines.append(f"- (score={s.score:.2f}) {s.content[:200]}")
            lines.append("")
            _add("\n".join(lines))

        # Cross-agent shared knowledge (limit to 5)
        knowledge = self.memory.query_knowledge(
            limit=5, project_id=self.project_id,
        )
        if knowledge:
            lines = ["## Shared knowledge from other agents"]
            for k in knowledge:
                lines.append(f"- [{k.publisher} | {k.topic}] {k.fact[:200]}")
            lines.append("")
            _add("\n".join(lines))

        # The actual task (always included, not budget-gated)
        parts.append("## Current task")
        parts.append(task)
        used += len(task) + 20

        if context:
            ctx_text = json.dumps(context, indent=2)[:2000]
            _add(f"\nAdditional context:\n{ctx_text}")

        # Intelligent file selection — only pass relevant files
        # Uses blast-radius analysis: the dep graph tracks which files changed,
        # and the file selector boosts files in the impact zone.
        if config.ENABLE_FILE_SELECTION and used < budget:
            try:
                root = os.path.dirname(os.path.dirname(__file__))
                graph = self.dep_graph_engine.query(root, self.project_id)
                # Pass changed files from graph engine for blast-radius scoring
                changed = getattr(graph, "changed_files", None) or []
                selection = self.file_selector.select(
                    task=task,
                    dep_graph=graph,
                    changed_files=changed if changed else None,
                    max_files=config.MAX_SELECTED_FILES,
                )
                if selection.files:
                    file_parts = ["\n## Relevant project files"]
                    for sf in selection.files:
                        remaining = budget - used
                        if remaining < 500:
                            break
                        if len(sf.content) > config.MAX_CHUNK_SIZE:
                            chunked = self.context_chunker.chunk_file(sf.path)
                            chunk_text = chunked.to_prompt_section(
                                task=task,
                                max_chars=min(config.MAX_CHUNK_SIZE, remaining),
                            )
                            file_parts.append(chunk_text)
                            used += len(chunk_text)
                        else:
                            block = (
                                f"### {sf.path} (score={sf.relevance:.2f})\n"
                                f"```\n{sf.content[:remaining]}\n```"
                            )
                            file_parts.append(block)
                            used += len(block)
                    _add("\n".join(file_parts))
            except Exception as exc:
                logger.debug("File selection skipped: %s", exc)

        if used >= budget:
            logger.warning("[%s] User message at budget limit (%d/%d chars)", self.name, used, budget)

        return "\n".join(parts)

    # -- streaming ----------------------------------------------------------

    async def _chat_streaming(self, system_prompt: str, user_message: str) -> str:
        """Stream LLM response, collecting full text."""
        chunks: list[str] = []
        async for chunk in self.llm.chat_stream(system_prompt, user_message):
            chunks.append(chunk)
        return "".join(chunks)

    # -- self-reflection loop -----------------------------------------------

    async def _reflection_loop(
        self,
        task: str,
        response: str,
        system_prompt: str,
        task_id: str,
    ) -> str:
        """Agent critiques its own output and optionally re-generates."""
        depth = 0
        while self.guardrails.check_reflection_depth(depth):
            critique_prompt = (
                "You are reviewing your own output for quality and completeness.\n\n"
                f"## Original task\n{task}\n\n"
                f"## Your output\n{response[:3000]}\n\n"
                "## Instructions\n"
                "Rate your output 1-10 for: correctness, completeness, code quality.\n"
                "If ALL scores are >= 8, respond with the SINGLE word APPROVED on the first line "
                "(nothing else before it).\n"
                "If any score is below 8, provide ONLY the improved version of the output "
                "(no ratings, no commentary — just the improved content)."
            )
            critique = await self.llm.chat(system_prompt, critique_prompt)

            if self.session_id and task_id:
                self.memory.store_task_memory(
                    session_id=self.session_id, task_id=task_id,
                    agent_name=self.name, action="reflection",
                    content=critique[:2000], step=depth + 1,
                    project_id=self.project_id,
                )

            # Check for approval in the first 200 chars (LLM may prefix with whitespace/markdown)
            if "APPROVED" in critique.upper()[:200]:
                logger.info("[%s] Reflection approved at depth %d", self.name, depth)
                break

            logger.info("[%s] Reflection depth %d — improving output", self.name, depth)
            response = critique
            depth += 1

        return response

    # -- tool use loop ------------------------------------------------------

    async def _tool_use_loop(
        self,
        response: str,
        system_prompt: str,
        user_message: str,
        task_id: str,
    ) -> str:
        """Parse tool invocations from LLM output, execute them, and re-prompt."""
        for iteration in range(_MAX_TOOL_ITERATIONS):
            tool_calls = self._parse_tool_calls(response)
            if not tool_calls:
                break

            logger.info("[%s] Executing %d tool calls (iter %d)", self.name, len(tool_calls), iteration)
            results: list[str] = []
            for call in tool_calls:
                tool_name = call.get("tool", "")
                args = call.get("args", {})
                result = await self.tools.invoke(tool_name, **args)
                result_text = f"Tool `{tool_name}`: {'OK' if result.success else 'FAILED'} — {json.dumps(result.output)[:1000]}"
                if result.error:
                    result_text += f" (error: {result.error})"
                results.append(result_text)

                if self.session_id and task_id:
                    self.memory.store_task_memory(
                        session_id=self.session_id, task_id=task_id,
                        agent_name=self.name, action="tool_call",
                        content=result_text[:2000], step=iteration,
                        metadata={"tool": tool_name},
                        project_id=self.project_id,
                    )

            # Re-prompt with tool results (only include results, not full history)
            followup = (
                f"## Original task\n{user_message[:2000]}\n\n"
                "## Tool Results\n" + "\n".join(results) + "\n\n"
                "Continue your task using these tool results. "
                "If you need more tools, use them. Otherwise, provide your final answer."
            )
            response = await self.llm.chat(system_prompt, followup)

        return response

    @staticmethod
    def _parse_tool_calls(text: str) -> list[dict[str, Any]]:
        """Extract ```tool JSON blocks from LLM output."""
        calls: list[dict[str, Any]] = []
        pattern = r"```tool\s*\n({.*?})\s*\n```"
        for match in re.finditer(pattern, text, re.DOTALL):
            try:
                data = json.loads(match.group(1))
                if "tool" in data:
                    calls.append(data)
            except json.JSONDecodeError:
                continue
        return calls

    # -- hooks for subclasses -----------------------------------------------

    async def _post_process(self, task: str, response: str) -> None:
        """Hook called after the LLM responds. Override to write files, etc."""
        pass

    # -- memory helpers -----------------------------------------------------

    def remember(self, content: str, category: str = "learning", **meta: Any) -> int:
        return self.memory.store_agent_memory(
            agent_name=self.name,
            content=content,
            category=category,
            metadata=meta,
            project_id=self.project_id,
        )

    def publish(self, topic: str, fact: str, confidence: float = 1.0) -> int:
        return self.memory.publish_knowledge(
            publisher=self.name,
            topic=topic,
            fact=fact,
            confidence=confidence,
            project_id=self.project_id,
        )

    # -- file helpers -------------------------------------------------------

    def write_artifact(self, filename: str, content: str) -> str:
        """Write content to the agent's output directory with guardrails + snapshot."""
        path = os.path.join(self._output_dir, filename)
        # Take snapshot before overwriting (if enabled)
        if config.ENABLE_SNAPSHOTS:
            self.enhanced_guardrails.snapshot_before_write(
                path, session_id=self.session_id, agent_name=self.name,
            )
        content = self.guardrails.validate_output(self.name, path, content)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("[%s] Wrote artifact: %s", self.name, path)
        return path

    # -- delegation helpers -------------------------------------------------

    async def delegate(
        self,
        target_agent: str,
        task: str,
        context: dict[str, Any] | None = None,
        blocking: bool = True,
    ) -> str | None:
        """Delegate a sub-task to another agent via the delegation protocol."""
        if not self.delegation:
            logger.warning("[%s] Delegation not available — protocol not wired", self.name)
            return None
        if blocking:
            return await self.delegation.delegate(
                requester=self.name, delegate_agent=target_agent,
                task=task, context=context,
            )
        await self.delegation.delegate_async(
            requester=self.name, delegate_agent=target_agent,
            task=task, context=context,
        )
        return None

    # -- long-term memory helpers -------------------------------------------

    def store_pattern(self, pattern: str, domain: str = "general", usefulness: float = 0.5) -> int:
        """Store a learned pattern in long-term memory."""
        return self.ltm.store_pattern(
            domain=domain,
            pattern_type="learned",
            content=pattern,
            source_agent=self.name,
            usefulness=usefulness,
        )
