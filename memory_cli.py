"""
CLI utility for inspecting and managing the SQLite memory database.

Usage:
    python memory_cli.py stats
    python memory_cli.py recall <agent_name> [--limit N]
    python memory_cli.py knowledge [--topic TOPIC] [--limit N]
    python memory_cli.py sessions [--session SESSION_ID]
    python memory_cli.py clear-cache
    python memory_cli.py reset            # WARNING: wipes all memory
"""

from __future__ import annotations

import argparse
import json
import sys

from interro_claw.memory import get_memory_store


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-Agent Memory Inspector")
    sub = parser.add_subparsers(dest="command")

    # stats
    sub.add_parser("stats", help="Show memory statistics")

    # recall
    recall = sub.add_parser("recall", help="Recall agent memories")
    recall.add_argument("agent_name")
    recall.add_argument("--limit", type=int, default=20)

    # knowledge
    kb = sub.add_parser("knowledge", help="Query shared knowledge base")
    kb.add_argument("--topic", default=None)
    kb.add_argument("--limit", type=int, default=20)

    # sessions
    sess = sub.add_parser("sessions", help="View session history")
    sess.add_argument("--session", default=None)
    sess.add_argument("--limit", type=int, default=50)

    # clear-cache
    sub.add_parser("clear-cache", help="Clear expired response cache entries")

    # reset
    sub.add_parser("reset", help="Wipe all memory (destructive!)")

    args = parser.parse_args()
    store = get_memory_store()

    if args.command == "stats":
        print(json.dumps(store.get_stats(), indent=2))

    elif args.command == "recall":
        entries = store.recall_agent_memory(args.agent_name, limit=args.limit)
        for e in entries:
            print(f"[{e.category}] {e.content[:200]}")
            print(f"  metadata: {e.metadata}")
            print()

    elif args.command == "knowledge":
        facts = store.query_knowledge(topic=args.topic, limit=args.limit)
        for f in facts:
            print(f"[{f.publisher} | {f.topic}] (confidence={f.confidence})")
            print(f"  {f.fact[:300]}")
            print()

    elif args.command == "sessions":
        if args.session:
            entries = store.get_session_history(args.session, limit=args.limit)
        else:
            # Show recent session entries across all sessions
            entries = store.get_recent_sessions(limit=args.limit)
        for e in entries:
            print(f"[{e.session_id}] {e.task_id} | {e.agent_name} | {e.status} ({e.elapsed_ms}ms)")
            print(f"  Task: {e.task_description[:120]}")
            print()

    elif args.command == "clear-cache":
        removed = store.cache_clear_expired()
        print(f"Removed {removed} expired cache entries.")

    elif args.command == "reset":
        confirm = input("This will DELETE ALL memory data. Type 'yes' to confirm: ")
        if confirm.strip().lower() == "yes":
            import os
            import interro_claw.config as config
            db_path = config.MEMORY_DB_PATH
            if os.path.exists(db_path):
                os.remove(db_path)
                print(f"Deleted {db_path}")
            else:
                print("No memory database found.")
        else:
            print("Aborted.")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
