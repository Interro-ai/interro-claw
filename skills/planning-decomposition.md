---
name: planning-decomposition
description: Task decomposition, project planning, dependency analysis, and estimation
applies_to: PlannerAgent, ArchitectAgent
priority: 15
---

# Planning & Task Decomposition

## Decomposition Strategy

When given a goal, break it down using this hierarchy:

1. **Phases** — major project milestones (architecture, develop, test, deploy)
2. **Tasks** — concrete deliverables within a phase (build API, create UI, write tests)
3. **Sub-tasks** — individual work items (create user model, add login endpoint)

## Task Properties

Every task should have:

- **Clear description** — what exactly needs to be built/done
- **Agent assignment** — which agent is best suited (ArchitectAgent, BackendAgent, etc.)
- **Dependencies** — what must complete before this task starts
- **Priority** — how critical is this to the overall goal
- **Acceptance criteria** — how do we know this is done

## Agent Selection Guidelines

| Task Type                         | Agent          |
| --------------------------------- | -------------- |
| Architecture, tech stack, design  | ArchitectAgent |
| API, database, business logic     | BackendAgent   |
| UI, components, client-side logic | FrontendAgent  |
| IaC, CI/CD, Docker, deployment    | OpsAgent       |
| Unit tests, integration, E2E      | TestAgent      |
| Threat models, audits, hardening  | SecurityAgent  |
| Cleanup, optimization, UX fixes   | RefactorAgent  |

## Dependency Ordering

Follow natural development flow:

```
Architecture first → Backend + Frontend in parallel → Ops/Infra → Tests + Security → Refactoring
```

- Architecture decisions must precede all implementation
- Backend and Frontend can run in parallel (shared API contract)
- Ops depends on knowing what to deploy
- Tests depend on having code to test
- Security reviews the full picture
- Refactoring improves what exists

## Planning Anti-Patterns

- **Over-planning** — don't design every detail upfront, plan in iterations
- **Under-decomposing** — tasks should be completable by one agent in one pass
- **Ignoring dependencies** — backend needs database schema before API endpoints
- **Forgetting non-functional** — always include security, testing, deployment tasks
- **Gold-plating** — plan for what's needed now, not hypothetical future requirements

## Estimation Heuristics

- Simple CRUD endpoint: 1 task (BackendAgent)
- Authentication system: 3-4 tasks (Architect + Backend + Security + Test)
- Full-stack feature: 5-7 tasks (Architect + Backend + Frontend + Test + Security)
- Infrastructure setup: 2-3 tasks (Architect + Ops)
- Migration/refactor: 2-3 tasks (Refactor + Test + Security)

## Output Format

Always structure plans as an ordered list of tasks:

```json
[
  {
    "task": "Design system architecture and API contracts",
    "agent": "ArchitectAgent"
  },
  { "task": "Build user authentication API", "agent": "BackendAgent" },
  { "task": "Create login and registration UI", "agent": "FrontendAgent" },
  { "task": "Set up CI/CD pipeline and Docker", "agent": "OpsAgent" },
  { "task": "Write integration tests for auth flow", "agent": "TestAgent" },
  {
    "task": "Security review: auth, input validation, secrets",
    "agent": "SecurityAgent"
  },
  { "task": "Refactor and optimize critical paths", "agent": "RefactorAgent" }
]
```
