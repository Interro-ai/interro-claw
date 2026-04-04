"""
DAG Scheduler

Converts a flat task list into a Directed Acyclic Graph with explicit dependencies:
- Architecture tasks have no dependencies
- Backend/Frontend depend on Architecture
- Tests depend on Backend + Frontend
- Ops depends on Architecture
- Security depends on all code outputs
- Refactor depends on everything

Supports:
- Topological sorting for execution order
- Parallel batch detection (tasks at same depth can run concurrently)
- Cycle detection
- Dynamic dependency injection
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Default dependency rules: agent -> depends_on agents
_DEFAULT_DEPS: dict[str, list[str]] = {
    "ArchitectAgent": [],
    "PlannerAgent": [],
    "BackendAgent": ["ArchitectAgent"],
    "FrontendAgent": ["ArchitectAgent"],
    "OpsAgent": ["ArchitectAgent"],
    "TestAgent": ["BackendAgent", "FrontendAgent"],
    "SecurityAgent": ["BackendAgent", "FrontendAgent", "OpsAgent"],
    "RefactorAgent": ["BackendAgent", "FrontendAgent", "TestAgent", "SecurityAgent"],
}


@dataclass
class TaskNode:
    """A node in the task DAG."""
    id: str
    description: str
    agent_name: str
    depends_on: list[str] = field(default_factory=list)  # IDs of prerequisite tasks
    depth: int = 0  # topological depth (0 = no deps)
    priority: int = 5  # execution priority within same depth
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionPlan:
    """The resolved DAG as batches of concurrent tasks."""
    nodes: list[TaskNode] = field(default_factory=list)
    batches: list[list[str]] = field(default_factory=list)  # groups of task IDs that can run in parallel
    has_cycle: bool = False
    total_depth: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_tasks": len(self.nodes),
            "total_batches": len(self.batches),
            "total_depth": self.total_depth,
            "has_cycle": self.has_cycle,
            "batches": [
                [{"id": tid, "agent": self._find_agent(tid)} for tid in batch]
                for batch in self.batches
            ],
        }

    def _find_agent(self, task_id: str) -> str:
        for n in self.nodes:
            if n.id == task_id:
                return n.agent_name
        return "unknown"


class DAGScheduler:
    """Builds and resolves task DAGs."""

    def __init__(self, dep_rules: dict[str, list[str]] | None = None) -> None:
        self._dep_rules = dep_rules or _DEFAULT_DEPS

    def build_dag(
        self,
        tasks: list[dict[str, str]],
        custom_deps: dict[str, list[str]] | None = None,
    ) -> ExecutionPlan:
        """Convert a flat task list into a DAG execution plan.

        Args:
            tasks: List of {"task": "...", "agent": "AgentName"}
            custom_deps: Optional per-task-id dependency overrides
        """
        nodes: list[TaskNode] = []
        agent_to_ids: dict[str, list[str]] = defaultdict(list)

        # Create nodes
        for idx, item in enumerate(tasks):
            task_id = f"task-{idx:03d}"
            agent = item.get("agent", "ArchitectAgent")
            node = TaskNode(
                id=task_id,
                description=item.get("task", ""),
                agent_name=agent,
            )
            nodes.append(node)
            agent_to_ids[agent].append(task_id)

        # Resolve dependencies
        id_to_node: dict[str, TaskNode] = {n.id: n for n in nodes}

        for node in nodes:
            if custom_deps and node.id in custom_deps:
                node.depends_on = custom_deps[node.id]
            else:
                # Use default agent-type dependency rules
                dep_agents = self._dep_rules.get(node.agent_name, [])
                for dep_agent in dep_agents:
                    node.depends_on.extend(agent_to_ids.get(dep_agent, []))

        # Topological sort + depth assignment
        plan = ExecutionPlan(nodes=nodes)
        self._topological_sort(plan, id_to_node)

        return plan

    def _topological_sort(
        self,
        plan: ExecutionPlan,
        id_to_node: dict[str, TaskNode],
    ) -> None:
        """Kahn's algorithm for topological sorting + batch detection."""
        # Build adjacency and in-degree
        in_degree: dict[str, int] = {n.id: 0 for n in plan.nodes}
        successors: dict[str, list[str]] = defaultdict(list)

        for node in plan.nodes:
            for dep_id in node.depends_on:
                if dep_id in id_to_node:
                    successors[dep_id].append(node.id)
                    in_degree[node.id] += 1

        # Find all nodes with no incoming edges
        queue: deque[str] = deque(
            tid for tid, deg in in_degree.items() if deg == 0
        )

        batches: list[list[str]] = []
        visited = 0

        while queue:
            # Current batch = all nodes with in_degree 0
            batch = list(queue)
            queue.clear()
            batches.append(batch)

            for tid in batch:
                visited += 1
                node = id_to_node[tid]
                node.depth = len(batches) - 1

                for succ in successors[tid]:
                    in_degree[succ] -= 1
                    if in_degree[succ] == 0:
                        queue.append(succ)

        plan.batches = batches
        plan.total_depth = len(batches)
        plan.has_cycle = visited < len(plan.nodes)

        if plan.has_cycle:
            logger.error("Cycle detected in task DAG! %d/%d nodes visited", visited, len(plan.nodes))

    def add_dep_rule(self, agent: str, depends_on: list[str]) -> None:
        """Add or override a dependency rule."""
        self._dep_rules[agent] = depends_on


# -- Singleton ---------------------------------------------------------------

_instance: DAGScheduler | None = None


def get_dag_scheduler() -> DAGScheduler:
    global _instance
    if _instance is None:
        _instance = DAGScheduler()
    return _instance
