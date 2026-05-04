"""
Adapter: converts stream_plan() AsyncGenerator → single ExperimentPlan return value.
Used by MCP tools, which return once (not stream).
"""
import asyncio
import json
import re
from typing import Callable

from anthropic import AsyncAnthropic

from rivulet.models import ExperimentPlan
from rivulet.planner import stream_plan

# 30s timeout matches MCP client expectations and Anthropic's p99 latency
_TIMEOUT_S = 30.0

# Fields to surface as thinking lines, in order: (json_key, display_label, value_transform)
_PROGRESS_FIELDS = [
    ("mode",               "mode",       lambda v: v.replace("_", " ")),
    ("protocol_name",      "protocol",   lambda v: v),
    ("cell_type",          "cell type",  lambda v: v),
    ("drug_count",         "compounds",  lambda v: str(v)),
    ("total_combinations", "combinations", lambda v: str(v)),
    ("input_gate",         "input gate", lambda v: str(v)),
]

_FIELD_RE = {
    key: re.compile(r'"' + key + r'"\s*:\s*(?:"([^"]+)"|(\d+))')
    for key, *_ in _PROGRESS_FIELDS
}


def _emit_progress(
    accumulated: str,
    emitted: set,
    on_progress: Callable[[str], None],
) -> None:
    for key, label, transform in _PROGRESS_FIELDS:
        if key in emitted:
            continue
        m = _FIELD_RE[key].search(accumulated)
        if m:
            raw = m.group(1) if m.group(1) is not None else m.group(2)
            on_progress(f"  → {label}: {transform(raw)}")
            emitted.add(key)


async def collect_plan(
    prompt: str,
    client: AsyncAnthropic,
    on_progress: Callable[[str], None] | None = None,
) -> ExperimentPlan:
    """Consume stream_plan chunks and return the final ExperimentPlan."""
    plan_data = None
    error_msg = None
    accumulated = ""
    emitted: set = set()

    async for chunk in stream_plan(prompt, client):
        if not chunk.startswith("data: "):
            continue
        payload = chunk[6:].strip()
        if not payload:
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "token":
            accumulated += event.get("text", "")
            if on_progress:
                _emit_progress(accumulated, emitted, on_progress)
        elif event.get("type") == "done":
            plan_data = event.get("plan")
        elif event.get("type") == "error":
            error_msg = event.get("message", "Unknown planner error")

    if error_msg:
        raise RuntimeError(f"Planner error: {error_msg}")
    if plan_data is None:
        raise RuntimeError("Planner returned no plan — check ANTHROPIC_API_KEY and retry")
    return ExperimentPlan(**plan_data)


async def call_planner(
    prompt: str,
    client: AsyncAnthropic,
    on_progress: Callable[[str], None] | None = None,
) -> ExperimentPlan:
    """Call planner with timeout. For use in async contexts (MCP tools)."""
    try:
        return await asyncio.wait_for(
            collect_plan(prompt, client, on_progress=on_progress),
            timeout=_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        raise RuntimeError(f"Anthropic timed out after {int(_TIMEOUT_S)}s. Try again.")


def call_planner_sync(
    prompt: str,
    api_key: str,
    on_progress: Callable[[str], None] | None = None,
) -> ExperimentPlan:
    """Synchronous planner call. For use in CLI (non-async context)."""
    client = AsyncAnthropic(api_key=api_key)
    return asyncio.run(call_planner(prompt, client, on_progress=on_progress))
