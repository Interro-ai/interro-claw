"""
Interro-Claw CLI — the main entry point.

Usage:
    interro-claw "Build a web application with auth"
    interro-claw --project myapp "Add user authentication"
    interro-claw --resume abc123 "Continue building"
    interro-claw --chat               (pure chat mode — no agents, just LLM)
    interro-claw --matrix-mode         (persistent interactive session with full agents)
    interro-claw --get-session         (list recent session IDs for resume)
    interro-claw --create-project      (create a new project interactively)
    interro-claw --list-projects       (list all registered projects)
    interro-claw --verbose "Build a REST API"   (see multi-agent details)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

def main() -> None:
    """Entry point for `interro-claw` command."""
    # Parse args first so --version works without LLM setup
    parser = argparse.ArgumentParser(
        prog="interro-claw",
        description="Interro-Claw — Autonomous Development System",
    )
    parser.add_argument("goal", nargs="*", help="The goal to accomplish")
    parser.add_argument("--resume", type=str, default=None, help="Resume a previous session by ID")
    parser.add_argument("--project", type=str, default=None, help="Project ID for memory scoping")
    parser.add_argument("--stream", action="store_true", help="Enable streaming responses")
    parser.add_argument("--auto-resume", action="store_true", help="Auto-resume last incomplete session")
    parser.add_argument("--chat", action="store_true", help="Pure chat mode (no agents, just LLM)")
    parser.add_argument("--matrix-mode", action="store_true", help="Persistent interactive session with full agent orchestration")
    parser.add_argument("--get-session", action="store_true", help="List recent session IDs (for --resume)")
    parser.add_argument("--create-project", action="store_true", help="Create a new project interactively")
    parser.add_argument("--list-projects", action="store_true", help="List all registered projects")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed multi-agent execution logs")
    parser.add_argument("--version", action="store_true", help="Show version and exit")
    args = parser.parse_args()

    if args.version:
        from interro_claw import __version__
        print(f"interro-claw {__version__}")
        return

    # Configure logging level based on --verbose
    _setup_logging(verbose=args.verbose)

    # Initialize Sentry (before anything else can fail)
    from interro_claw.sentry_integration import init_sentry
    init_sentry()

    from interro_claw import config
    from interro_claw.sentry_integration import capture_exception, set_user_context

    # --get-session: list recent sessions and exit
    if args.get_session:
        _show_sessions()
        return

    # --create-project: interactive project creation and exit
    if args.create_project:
        _create_project_interactive()
        return

    # --list-projects: list all registered projects and exit
    if args.list_projects:
        _list_projects()
        return

    # Show config source info (always, so the user knows what's happening)
    _print_config_info(config)

    # Ensure LLM provider + API key are configured (interactive if needed)
    config.ensure_llm_configured()

    # Pure chat mode — simple LLM conversation, no agents
    if args.chat:
        _chat_mode()
        return

    # Matrix mode — persistent interactive session with full agents
    if args.matrix_mode:
        _matrix_mode(config, args)
        return

    # Agent orchestration mode
    from interro_claw.orchestrator import Orchestrator
    from interro_claw.memory import get_memory_store

    project_id = _resolve_project_id(args.project) or config.DEFAULT_PROJECT_ID
    resume_session = args.resume

    if args.auto_resume and not resume_session:
        store = get_memory_store()
        resume_session = store.find_incomplete_session(project_id)
        if resume_session:
            print(f"Auto-resuming session: {resume_session}")

    if not args.goal and not resume_session:
        parser.print_help()
        print('\nExamples:')
        print('  interro-claw "Build a web application with auth"')
        print('  interro-claw --chat                              (pure LLM chat)')
        print('  interro-claw --matrix-mode                       (persistent interactive session)')
        print('  interro-claw --get-session                       (list session IDs for --resume)')
        print('  interro-claw --create-project                    (create a new project)')
        print('  interro-claw --list-projects                     (list all projects)')
        print('  interro-claw --resume abc123 "Continue building"')
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

    set_user_context(orchestrator.session_id, project_id)

    try:
        results = asyncio.run(orchestrator.run(goal))
    except Exception as exc:
        print(f"\n  [Error] Orchestrator run failed: {exc}", flush=True)
        capture_exception(exc, goal=goal, project_id=project_id)
        import traceback
        traceback.print_exc()
        results = []

    # Print the consolidator report
    report = getattr(orchestrator, "_last_report", None)
    if report:
        print("\n" + report, flush=True)

    # Interactive loop
    _interactive_loop(orchestrator)


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging(verbose: bool = False) -> None:
    """Configure console logging level.

    Default (no --verbose):
        Only WARNING+ goes to console.  Key step prints use print() directly.
    With --verbose:
        DEBUG+ goes to console — shows every agent start/stop, LLM call,
        delegation, DAG batch, memory store/recall, etc.
    File logging (orchestrator.log) is always at INFO level regardless.
    """
    console_level = logging.DEBUG if verbose else logging.WARNING
    # Set the root logger; file handler in orchestrator.py keeps its own level
    logging.basicConfig(
        level=console_level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s" if verbose
               else "%(levelname)-8s  %(message)s",
        force=True,  # override any previous basicConfig
    )
    if verbose:
        print("  [verbose] Detailed multi-agent logs enabled\n", flush=True)


def _print_config_info(config) -> None:
    """Always show the user which provider/config is in use.

    This is the 'default step logging' that runs even without --verbose.
    """
    from interro_claw import __version__

    env_sources = []
    cwd_env = os.path.join(os.getcwd(), ".env")
    home_env = str(config._ENV_FILE)
    if os.path.exists(cwd_env):
        env_sources.append(f"CWD ({cwd_env})")
    if os.path.exists(home_env):
        env_sources.append(f"HOME ({home_env})")

    print(f"\n  interro-claw v{__version__}")
    print(f"  Provider : {config.LLM_PROVIDER or '<not set>'}")
    if env_sources:
        print(f"  .env from: {' > '.join(env_sources)}")
    print(f"  Output   : {os.path.abspath(config.USER_APP_DIR)}")
    print(f"  Logs     : {config.LOG_DIR}")
    print()


def _interactive_loop(orchestrator: object) -> None:
    """Keep the session alive for follow-up instructions."""
    from interro_claw import config
    from interro_claw.sentry_integration import capture_exception

    session_id = getattr(orchestrator, "session_id", "unknown")
    sep = "=" * 72
    print(f"\n{sep}")
    print(f"  INTERRO-CLAW — Session: {session_id}")
    print("  Type your next instruction, or 'quit' to exit.")
    print(f"{sep}")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
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
                print(f"  Session ID: {session_id}  (use --resume {session_id} to continue)")
                break

            try:
                results = loop.run_until_complete(orchestrator.run(user_input))
                report = getattr(orchestrator, "_last_report", None)
                if report:
                    print("\n" + report)
            except Exception as exc:
                print(f"\nError: {exc}")
                capture_exception(exc, user_input=user_input)
                print("You can try again or type 'quit' to exit.")
    finally:
        loop.close()


def _chat_mode() -> None:
    """
    Pure chat mode — no agents, no planning, just direct LLM conversation.
    Maintains conversation history with context window management.
    """
    from interro_claw import config
    from interro_claw.llm_client import get_llm_client
    from interro_claw.sentry_integration import capture_exception

    MAX_HISTORY_CHARS = config.MAX_CONTEXT_CHARS  # reuse the same budget

    print("\n" + "=" * 60)
    print(f"  INTERRO-CLAW Chat  ({config.LLM_PROVIDER})")
    print("  Type your question, or 'quit' to exit.")
    print("  Type '/clear' to reset conversation history.")
    print("=" * 60)

    client = get_llm_client()
    system_prompt = (
        "You are Interro-Claw, a helpful AI assistant for software development. "
        "Answer questions clearly and concisely. When asked to write code, "
        "provide complete, working code with explanations."
    )
    conversation_history: list[dict[str, str]] = []

    def _trim_history() -> None:
        """Evict oldest messages if total chars exceed budget."""
        total = sum(len(m["content"]) for m in conversation_history)
        while total > MAX_HISTORY_CHARS and len(conversation_history) > 2:
            removed = conversation_history.pop(0)
            total -= len(removed["content"])

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        while True:
            try:
                user_input = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nChat ended.")
                break

            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "q"):
                print("Chat ended.")
                break
            if user_input.lower() == "/clear":
                conversation_history.clear()
                print("  Conversation history cleared.")
                continue

            # Build context-aware prompt from history
            conversation_history.append({"role": "user", "content": user_input})
            _trim_history()

            history_text = "\n".join(
                f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
                for m in conversation_history[:-1]  # exclude current message
            )
            full_message = ""
            if history_text:
                full_message = f"## Conversation history\n{history_text}\n\n## Current message\n{user_input}"
            else:
                full_message = user_input

            try:
                response = loop.run_until_complete(
                    client.chat(system_prompt, full_message)
                )
                conversation_history.append({"role": "assistant", "content": response})
                _trim_history()
                print(f"\n{response}")
            except Exception as exc:
                print(f"\nError: {exc}")
                capture_exception(exc, user_input=user_input)
                # Remove the failed user message from history
                if conversation_history and conversation_history[-1]["role"] == "user":
                    conversation_history.pop()
                print("Try again or type 'quit' to exit.")
    finally:
        loop.close()


_INTENT_CLASSIFICATION_PROMPT = """\
You are a routing classifier for an autonomous development system called Interro-Claw.
Given the user's message and conversation history, classify the intent into EXACTLY ONE of:

1. **chat** — The user is asking a general question, requesting explanations, definitions,
   opinions, or having a casual conversation. No code generation or project work is needed.
   Examples: "what is SSH?", "explain REST vs GraphQL", "what's the best Python web framework?"

2. **clarify** — The user wants to build, create, or modify something, but the request is
   too vague or missing critical details for the agents to execute well. You need to ask
   follow-up questions to gather requirements before proceeding.
   Examples: "create a web app", "build me an API", "make a dashboard"

3. **goal** — The user has given a clear, actionable instruction with enough detail for
   the development agents to start working. The task involves creating, modifying, or
   analyzing code/infrastructure.
   Examples: "Build a FastAPI REST API with JWT auth and PostgreSQL",
   "Add unit tests for the user service", "Deploy this app to Azure with Bicep"

Respond with ONLY a JSON object (no markdown fences, no explanation):
{"intent": "chat"|"clarify"|"goal", "reason": "<brief one-line reason>"}

If intent is "clarify", also include a "questions" field with 1-3 focused questions:
{"intent": "clarify", "reason": "...", "questions": ["What is the webapp about?", "..."]}
"""

_CHAT_SYSTEM_PROMPT = (
    "You are Interro-Claw, a knowledgeable AI assistant specialized in software development, "
    "DevOps, cloud architecture, and engineering best practices. "
    "Answer questions clearly and concisely. When asked to write code snippets, "
    "provide complete, working code with brief explanations. "
    "You are running inside an interactive matrix session — the user can also "
    "give you development goals which will be handled by specialized agents."
)


def _matrix_mode(config, args) -> None:
    """
    Matrix Mode — persistent interactive session with intelligent intent routing.

    Routes user input through LLM-based intent classification:
    - **chat**: Simple questions answered directly by the LLM (no agents).
    - **clarify**: Vague goals trigger follow-up questions to gather requirements
      before dispatching to agents.
    - **goal**: Clear, actionable goals dispatched to the full agent orchestrator.
    """
    from interro_claw.orchestrator import Orchestrator
    from interro_claw.llm_client import get_llm_client
    from interro_claw.sentry_integration import capture_exception, set_user_context

    # Resolve or interactively select a project
    project_id = _resolve_or_select_project(args.project, config)
    resume_session = args.resume

    if args.auto_resume and not resume_session:
        from interro_claw.memory import get_memory_store
        store = get_memory_store()
        resume_session = store.find_incomplete_session(project_id)
        if resume_session:
            print(f"  Auto-resuming session: {resume_session}")

    orchestrator = Orchestrator(
        project_id=project_id,
        resume_session=resume_session,
        enable_streaming=args.stream,
    )
    set_user_context(orchestrator.session_id, project_id)
    llm = get_llm_client()

    # Conversation history for chat context and intent classification
    conversation_history: list[dict[str, str]] = []
    MAX_HISTORY_CHARS = config.MAX_CONTEXT_CHARS // 2

    def _trim_history() -> None:
        total = sum(len(m["content"]) for m in conversation_history)
        while total > MAX_HISTORY_CHARS and len(conversation_history) > 2:
            removed = conversation_history.pop(0)
            total -= len(removed["content"])

    def _history_text() -> str:
        if not conversation_history:
            return ""
        lines = []
        for m in conversation_history:
            role = "User" if m["role"] == "user" else "Assistant"
            lines.append(f"{role}: {m['content'][:500]}")
        return "\n".join(lines)

    sep = "=" * 72
    print(f"\n{sep}")
    print(f"  INTERRO-CLAW  Matrix Mode")
    print(f"  Session : {orchestrator.session_id}")
    print(f"  Project : {project_id}")
    print(f"  Provider: {config.LLM_PROVIDER}")
    print(f"  Output  : {os.path.abspath(config.USER_APP_DIR)}")
    print(sep)
    print("  Type anything — questions, goals, or tasks.")
    print("  Simple questions are answered directly; goals are sent to agents.")
    print(f"  To resume later: interro-claw --resume {orchestrator.session_id}")
    print(f"  Type /help for commands, 'exit' to quit.")
    print(sep)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        while True:
            try:
                user_input = input("\n[matrix] > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  Matrix session ended.")
                break

            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "q"):
                print(f"  Session ended: {orchestrator.session_id}")
                print(f"  Your files are in: {os.path.abspath(config.USER_APP_DIR)}")
                print(f"  Resume with: interro-claw --resume {orchestrator.session_id}")
                break
            if user_input.lower() == "/session":
                print(f"  Session ID: {orchestrator.session_id}")
                continue
            if user_input.lower() == "/clear-context":
                _clear_session_context(orchestrator)
                conversation_history.clear()
                print("  Conversation history also cleared.")
                continue
            if user_input.lower() == "/stats":
                _print_session_stats(orchestrator)
                continue
            if user_input.lower() == "/projects":
                _list_projects()
                continue
            if user_input.lower() == "/new-project":
                proj = _create_project_interactive()
                if proj:
                    print(f"  To use this project: interro-claw --matrix-mode --project {proj.id}")
                continue
            if user_input.lower() == "/help":
                print("  /session         Show current session ID")
                print("  /clear-context   Clear session memory + conversation history")
                print("  /stats           Show memory and LLM call stats")
                print("  /projects        List all registered projects")
                print("  /new-project     Create a new project")
                print("  /help            Show this help")
                print("  exit             Exit matrix mode")
                print()
                print("  Your input is automatically classified:")
                print("    Questions     → answered directly by the LLM")
                print("    Vague goals   → follow-up questions asked first")
                print("    Clear goals   → sent to the agent orchestrator")
                continue

            # ----- Intent classification -----
            intent = _classify_intent(loop, llm, user_input, _history_text())

            if intent["intent"] == "chat":
                # Direct LLM answer — no agents needed
                conversation_history.append({"role": "user", "content": user_input})
                _trim_history()
                try:
                    history = _history_text()
                    msg = user_input
                    if history:
                        msg = f"## Conversation history\n{history}\n\n## Current message\n{user_input}"
                    response = loop.run_until_complete(
                        llm.chat(_CHAT_SYSTEM_PROMPT, msg)
                    )
                    conversation_history.append({"role": "assistant", "content": response})
                    _trim_history()
                    print(f"\n{response}")
                except Exception as exc:
                    print(f"\n  [Error] {exc}")
                    capture_exception(exc, user_input=user_input)

            elif intent["intent"] == "clarify":
                # Ask follow-up questions, then build enriched goal
                questions = intent.get("questions", [])
                if questions:
                    print("\n  Before I send this to the agents, I need a few details:\n")
                    answers = []
                    for i, q in enumerate(questions, 1):
                        print(f"  {i}. {q}")
                        try:
                            ans = input("     > ").strip()
                            if ans:
                                answers.append(f"- {q} → {ans}")
                        except (EOFError, KeyboardInterrupt):
                            break

                    if answers:
                        enriched_goal = (
                            f"{user_input}\n\n"
                            f"Additional requirements gathered from the user:\n"
                            + "\n".join(answers)
                        )
                    else:
                        enriched_goal = user_input
                else:
                    enriched_goal = user_input

                # Now dispatch the enriched goal to orchestrator
                conversation_history.append({"role": "user", "content": enriched_goal})
                _trim_history()
                print(f"\n  Dispatching to agents...")
                try:
                    results = loop.run_until_complete(orchestrator.run(enriched_goal))
                    report = getattr(orchestrator, "_last_report", None)
                    if report:
                        conversation_history.append({"role": "assistant", "content": report[:2000]})
                        _trim_history()
                        print("\n" + report)
                except Exception as exc:
                    print(f"\n  [Error] {exc}")
                    capture_exception(exc, user_input=enriched_goal)
                    print("  You can try again or type 'exit'.")

            else:  # intent == "goal"
                # Clear actionable goal — dispatch directly to orchestrator
                conversation_history.append({"role": "user", "content": user_input})
                _trim_history()
                print(f"\n  Dispatching to agents...")
                try:
                    results = loop.run_until_complete(orchestrator.run(user_input))
                    report = getattr(orchestrator, "_last_report", None)
                    if report:
                        conversation_history.append({"role": "assistant", "content": report[:2000]})
                        _trim_history()
                        print("\n" + report)
                except Exception as exc:
                    print(f"\n  [Error] {exc}")
                    capture_exception(exc, user_input=user_input)
                    print("  You can try again or type 'exit'.")
    finally:
        loop.close()


def _classify_intent(
    loop: asyncio.AbstractEventLoop,
    llm,
    user_input: str,
    history_text: str,
) -> dict:
    """Use a lightweight LLM call to classify the user's intent.

    Returns {"intent": "chat"|"clarify"|"goal", "reason": "...", "questions": [...]}.
    Falls back to "goal" if classification fails.
    """
    import json as _json

    context = f"User message: {user_input}"
    if history_text:
        context = f"Recent conversation:\n{history_text[-2000:]}\n\n{context}"

    try:
        raw = loop.run_until_complete(
            llm.chat(_INTENT_CLASSIFICATION_PROMPT, context)
        )
        # Strip markdown fences if the model wraps them
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()

        result = _json.loads(cleaned)
        if result.get("intent") in ("chat", "clarify", "goal"):
            return result
    except Exception:
        pass  # Classification failed — fall back to goal

    return {"intent": "goal", "reason": "classification fallback"}


def _clear_session_context(orchestrator) -> None:
    """Clear volatile context to free up context window budget."""
    try:
        from interro_claw.memory import get_memory_store
        store = get_memory_store()
        session_id = orchestrator.session_id
        # Prune old session entries keeping only last 5
        with store._connect() as conn:
            conn.execute(
                """DELETE FROM session_history WHERE session_id = ? AND id NOT IN (
                       SELECT id FROM session_history WHERE session_id = ?
                       ORDER BY created_at DESC LIMIT 5
                   )""",
                (session_id, session_id),
            )
        print("  Context pruned — kept last 5 session entries.")
    except Exception as exc:
        print(f"  Error clearing context: {exc}")


def _print_session_stats(orchestrator) -> None:
    """Print memory and LLM call stats."""
    try:
        from interro_claw.memory import get_memory_store
        store = get_memory_store()
        stats = store.get_stats()
        gr_stats = orchestrator.guardrails.get_stats()
        print("  Memory stats:")
        for table, count in stats.items():
            print(f"    {table}: {count} rows")
        print(f"  LLM calls this session: {gr_stats['llm_calls']}/{gr_stats['max_llm_calls']}")
    except Exception as exc:
        print(f"  Error getting stats: {exc}")


def _show_sessions() -> None:
    """List recent sessions with their IDs, goals, and status."""
    from interro_claw import config
    from interro_claw.memory import get_memory_store

    store = get_memory_store()
    entries = store.get_recent_sessions(limit=50)
    if not entries:
        print("  No sessions found.")
        return

    # Group by session_id, show latest entry per session
    sessions: dict[str, dict] = {}
    for e in entries:
        if e.session_id not in sessions:
            sessions[e.session_id] = {
                "session_id": e.session_id,
                "project_id": e.project_id,
                "status": e.status,
                "task_count": 0,
                "last_task": e.task_description[:60],
                "created_at": e.created_at,
            }
        sessions[e.session_id]["task_count"] += 1

    import time as _time
    sep = "=" * 72
    print(f"\n{sep}")
    print(f"  RECENT SESSIONS ({len(sessions)})")
    print(sep)
    print(f"  {'Session ID':<24} {'Project':<12} {'Tasks':>5}  {'Status':<10}  Last Task")
    print(f"  {'-'*22}   {'-'*10}   {'-'*5}  {'-'*8}   {'-'*30}")
    for s in sessions.values():
        print(f"  {s['session_id']:<24} {s['project_id']:<12} {s['task_count']:>5}  {s['status']:<10}  {s['last_task']}")
    print(sep)
    print("  To resume: interro-claw --resume <session_id>")
    print()


# ---------------------------------------------------------------------------
# Project management
# ---------------------------------------------------------------------------

def _resolve_project_id(project_arg: str | None) -> str | None:
    """Resolve a --project argument to a valid project ID.

    Accepts a project ID or project name. If found, touches last_accessed_at.
    Returns the project ID or None if not found / not specified.
    """
    if not project_arg:
        return None
    from interro_claw.memory import get_memory_store
    store = get_memory_store()
    proj = store.resolve_project(project_arg)
    if proj:
        store.touch_project(proj.id)
        return proj.id
    # Not found — maybe user passed a raw string they want to use directly
    # (backward compat: allow any string as project_id)
    return project_arg


def _resolve_or_select_project(project_arg: str | None, config) -> str:
    """Resolve --project or interactively select/create a project.

    Used by matrix-mode to ensure the user consciously picks a project.
    Returns a project_id string.
    """
    from interro_claw.memory import get_memory_store

    # If --project was provided, resolve it
    if project_arg:
        resolved = _resolve_project_id(project_arg)
        if resolved:
            return resolved

    store = get_memory_store()
    projects = store.list_projects()

    if not projects:
        # No projects exist — offer to create one or use default
        print("\n  No projects registered yet.")
        print("  1) Create a new project")
        print("  2) Use default project")
        try:
            choice = input("  Choose [1/2]: ").strip()
        except (EOFError, KeyboardInterrupt):
            return config.DEFAULT_PROJECT_ID

        if choice == "1":
            proj = _create_project_interactive()
            return proj.id if proj else config.DEFAULT_PROJECT_ID
        return config.DEFAULT_PROJECT_ID

    # Projects exist — show them and let user pick
    sep = "-" * 60
    print(f"\n{sep}")
    print("  SELECT A PROJECT")
    print(sep)
    for i, p in enumerate(projects, 1):
        desc = f" — {p.description}" if p.description else ""
        print(f"  {i}) {p.name} [{p.id}]{desc}")
    print(f"  {len(projects) + 1}) Create a new project")
    print(f"  {len(projects) + 2}) Use default project")
    print(sep)

    try:
        choice = input(f"  Choose [1-{len(projects) + 2}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        return config.DEFAULT_PROJECT_ID

    try:
        idx = int(choice)
    except ValueError:
        # Maybe they typed a project name/id directly
        resolved = _resolve_project_id(choice)
        return resolved or config.DEFAULT_PROJECT_ID

    if 1 <= idx <= len(projects):
        selected = projects[idx - 1]
        store.touch_project(selected.id)
        return selected.id
    elif idx == len(projects) + 1:
        proj = _create_project_interactive()
        return proj.id if proj else config.DEFAULT_PROJECT_ID
    else:
        return config.DEFAULT_PROJECT_ID


def _create_project_interactive():
    """Create a new project interactively. Returns the ProjectRecord or None."""
    from interro_claw.memory import get_memory_store

    store = get_memory_store()
    sep = "=" * 60
    print(f"\n{sep}")
    print("  CREATE NEW PROJECT")
    print(sep)

    try:
        name = input("  Project name: ").strip()
        if not name:
            print("  Cancelled — name is required.")
            return None

        # Check if name already exists
        existing = store.get_project_by_name(name)
        if existing:
            print(f"  Project '{name}' already exists with ID: {existing.id}")
            return existing

        description = input("  Description (optional): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n  Cancelled.")
        return None

    try:
        proj = store.create_project(name=name, description=description)
        print(f"\n  Project created!")
        print(f"    Name : {proj.name}")
        print(f"    ID   : {proj.id}")
        if proj.description:
            print(f"    Desc : {proj.description}")
        print(f"\n  Use it with: interro-claw --project {proj.id} \"your goal\"")
        print(f"           or: interro-claw --matrix-mode --project {proj.id}")
        return proj
    except Exception as exc:
        print(f"  Error creating project: {exc}")
        return None


def _list_projects() -> None:
    """List all registered projects."""
    from interro_claw.memory import get_memory_store

    store = get_memory_store()
    projects = store.list_projects()

    if not projects:
        print("  No projects registered.")
        print("  Create one with: interro-claw --create-project")
        return

    import time as _time
    sep = "=" * 72
    print(f"\n{sep}")
    print(f"  REGISTERED PROJECTS ({len(projects)})")
    print(sep)
    print(f"  {'ID':<28} {'Name':<20} {'Last Accessed':<20} Description")
    print(f"  {'-'*26}   {'-'*18}   {'-'*18}   {'-'*20}")
    for p in projects:
        accessed = _time.strftime("%Y-%m-%d %H:%M", _time.localtime(p.last_accessed_at))
        desc = p.description[:30] if p.description else ""
        print(f"  {p.id:<28} {p.name:<20} {accessed:<20} {desc}")
    print(sep)
    print("  Use a project: interro-claw --project <id> \"your goal\"")
    print("  Create new:    interro-claw --create-project")
    print()


if __name__ == "__main__":
    main()
