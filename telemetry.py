"""
Token Reduction Telemetry — tracks how much the code-review-graph
integration saves in LLM calls, tokens, and cost per session.

Thread-safe singleton. Instrument call sites with `record()`,
print summary with `report()`.
"""

from __future__ import annotations

import threading
from typing import Any

_AVG_TOKENS_PER_CALL = 3000  # conservative estimate for mixed heavy/light calls
_COST_PER_1K_TOKENS = 0.003  # blended average across providers

_lock = threading.Lock()
_counters: dict[str, int] = {
    "cache_hits_exact": 0,
    "cache_hits_fingerprint": 0,
    "cache_misses": 0,
    "files_pruned_by_blast_radius": 0,
    "files_skipped_unchanged": 0,
    "context_chars_saved": 0,
}


def record(metric: str, value: int = 1) -> None:
    """Increment a telemetry counter (thread-safe)."""
    with _lock:
        _counters[metric] = _counters.get(metric, 0) + value


def summary() -> dict[str, Any]:
    """Return current telemetry snapshot with computed savings."""
    with _lock:
        data = dict(_counters)

    total_hits = data["cache_hits_exact"] + data["cache_hits_fingerprint"]
    total_calls = total_hits + data["cache_misses"]
    hit_rate = (total_hits / total_calls * 100) if total_calls > 0 else 0.0
    tokens_saved = total_hits * _AVG_TOKENS_PER_CALL
    cost_saved = tokens_saved / 1000 * _COST_PER_1K_TOKENS

    return {
        **data,
        "total_llm_calls_attempted": total_calls,
        "cache_hit_rate_pct": round(hit_rate, 1),
        "est_tokens_saved": tokens_saved,
        "est_cost_saved_usd": round(cost_saved, 4),
    }


def report() -> str:
    """Formatted telemetry report string for console output."""
    s = summary()

    if s["total_llm_calls_attempted"] == 0:
        return ""  # nothing to report

    lines = [
        "",
        "+" + "=" * 58 + "+",
        "|{:^58s}|".format("Token Reduction Summary"),
        "+" + "=" * 58 + "+",
        "| {:<40s}{:>16s} |".format("LLM Calls Saved (exact cache):", str(s["cache_hits_exact"])),
        "| {:<40s}{:>16s} |".format("LLM Calls Saved (fuzzy fingerprint):", str(s["cache_hits_fingerprint"])),
        "| {:<40s}{:>16s} |".format("Actual LLM Calls Made:", str(s["cache_misses"])),
        "| {:<40s}{:>16s} |".format("Cache Hit Rate:", f"{s['cache_hit_rate_pct']}%"),
        "+" + "-" * 58 + "+",
        "| {:<40s}{:>16s} |".format("Files Pruned by Blast Radius:", str(s["files_pruned_by_blast_radius"])),
        "| {:<40s}{:>16s} |".format("Files Skipped (unchanged hash):", str(s["files_skipped_unchanged"])),
        "| {:<40s}{:>16s} |".format("Context Chars Saved:", f"~{s['context_chars_saved']:,}"),
        "+" + "-" * 58 + "+",
        "| {:<40s}{:>16s} |".format("Est. Tokens Saved:", f"~{s['est_tokens_saved']:,}"),
        "| {:<40s}{:>16s} |".format("Est. Cost Saved:", f"~${s['est_cost_saved_usd']:.4f}"),
        "+" + "=" * 58 + "+",
        "",
    ]
    return "\n".join(lines)


def reset() -> None:
    """Reset all counters (for testing or new session)."""
    with _lock:
        for key in _counters:
            _counters[key] = 0
