"""
Rivulet MCP server — FastMCP tool definitions.

Entry point: `rivulet-mcp` (installed via pyproject.toml scripts).
For Claude Desktop: use `uvx rivulet-mcp` in claude_desktop_config.json.

Tool names are frozen after 0.1.0. Do not rename:
  design_experiment, iterate_protocol, estimate_throughput, run_experiment, list_presets
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
from anthropic import AsyncAnthropic
from fastmcp import FastMCP

from rivulet._planner_wrapper import call_planner
from rivulet.models import ExperimentPlan
from rivulet.presets import PRESETS
from rivulet.throughput import estimate_throughput as _estimate_throughput

mcp = FastMCP(
    "Rivulet",
    instructions=(
        "Rivulet is a digital microfluidics platform for high-throughput biological experiments. "
        "Use design_experiment to create protocols from natural language, iterate_protocol to revise them, "
        "estimate_throughput for runtime estimates, list_presets to see built-in examples, "
        "and run_experiment when a researcher explicitly requests to run a physical experiment "
        "(currently stub — hardware not yet deployed)."
    ),
)

# Debug logging — enabled when RIVULET_DEBUG=1
_DEBUG = os.environ.get("RIVULET_DEBUG") == "1"
_LOG_FILE = Path.home() / ".rivulet-mcp.log"


def _debug_log(tool: str, status: str, detail: str, api_key: str = "") -> None:
    if not _DEBUG:
        return
    key_suffix = (api_key[-4:] if api_key and len(api_key) >= 4 else "????")
    ts = datetime.now(timezone.utc).isoformat()
    line = f"[{ts}] [{tool}] [{status}] {detail} key=...{key_suffix}\n"
    try:
        with open(_LOG_FILE, "a") as f:
            f.write(line)
    except OSError:
        pass


def _get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise ValueError(
            "ANTHROPIC_API_KEY not set. "
            "For Claude Desktop: add it to the 'env' block in claude_desktop_config.json. "
            "For CLI: export ANTHROPIC_API_KEY=sk-ant-..."
        )
    return key


def _post_slack(message: str) -> None:
    """Optionally POST to RIVULET_SLACK_WEBHOOK if configured."""
    webhook_url = os.environ.get("RIVULET_SLACK_WEBHOOK", "").strip()
    if not webhook_url:
        return
    try:
        import urllib.request
        data = json.dumps({"text": message}).encode()
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool(
    description=(
        "Design a DEP microfluidics experiment protocol from a natural language description. "
        "Use this when a researcher describes what they want to test and you need a concrete, "
        "structured protocol. Returns an ExperimentPlan JSON with mode, cell types, drug "
        "concentrations, timing, and estimated throughput. Input: one plain-language sentence "
        "describing the biological goal. Does NOT run the experiment — use run_experiment for "
        "that (currently stub only, contact asmay@rivulet.bio)."
    )
)
async def design_experiment(prompt: str) -> dict:
    api_key = _get_api_key()
    client = AsyncAnthropic(api_key=api_key)
    _debug_log("design_experiment", "called", f"prompt_len={len(prompt)}", api_key)
    plan = await call_planner(prompt, client)
    _debug_log("design_experiment", "success", f"mode={plan.mode}", api_key)
    return plan.model_dump()


@mcp.tool(
    description=(
        "Revise an existing ExperimentPlan based on researcher feedback. Use after "
        "design_experiment when the researcher wants to adjust parameters (change drug count, "
        "swap cell types, modify timing, add conditions). REQUIRED: pass the full prior "
        "ExperimentPlan JSON as the plan parameter — the server holds no session state. "
        "Returns a revised ExperimentPlan. Do not call this without a prior plan from "
        "design_experiment."
    )
)
async def iterate_protocol(plan: dict, feedback: str) -> dict:
    if not plan:
        raise ValueError("plan parameter required and must be valid ExperimentPlan")
    try:
        prior_plan = ExperimentPlan(**{k: v for k, v in plan.items() if k in ExperimentPlan.model_fields})
    except Exception:
        raise ValueError("plan parameter required and must be valid ExperimentPlan")

    api_key = _get_api_key()
    client = AsyncAnthropic(api_key=api_key)

    iterate_prompt = (
        f"Revise this DEP experiment protocol based on the following feedback.\n\n"
        f"Current plan (JSON):\n{prior_plan.model_dump_json(indent=2)}\n\n"
        f"Feedback: {feedback}\n\n"
        f"Return only the revised plan JSON, following the same schema."
    )

    _debug_log("iterate_protocol", "called", f"mode={prior_plan.mode} feedback_len={len(feedback)}", api_key)
    revised = await call_planner(iterate_prompt, client)
    _debug_log("iterate_protocol", "success", f"mode={revised.mode}", api_key)
    return revised.model_dump()


@mcp.tool(
    description=(
        "Calculate runtime and throughput estimates for an ExperimentPlan. Returns "
        "run_time_min, compound_count, and rivulet_speedup_x (estimated speedup vs "
        "traditional plate-based methods). ALWAYS includes a WARNING field — "
        "these are pre-validation estimates, not benchmarked numbers. Call after "
        "design_experiment to give the researcher a time and scale estimate before "
        "committing to a run."
    )
)
def estimate_throughput(plan: dict) -> dict:
    if not plan:
        raise ValueError("plan parameter required")
    try:
        exp_plan = ExperimentPlan(**{k: v for k, v in plan.items() if k in ExperimentPlan.model_fields})
    except Exception:
        raise ValueError("plan parameter required and must be valid ExperimentPlan")
    _debug_log("estimate_throughput", "called", f"mode={exp_plan.mode}")
    return _estimate_throughput(exp_plan)


_DEMO_URL = os.environ.get("RIVULET_DEMO_URL", "").rstrip("/")
_DEMO_TOKEN = os.environ.get("RIVULET_DEMO_TOKEN", "")


@mcp.tool(
    description=(
        "Submit an ExperimentPlan for execution. When RIVULET_DEMO_URL is set, "
        "forwards the plan to the DMF simulation app for live demo. Otherwise raises "
        "NotImplementedError — hardware deployment not yet available. Call this when "
        "a researcher explicitly asks to run a physical experiment."
    )
)
async def run_experiment(plan: dict, chip_id: str = "unknown") -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    key_suffix = api_key[-4:] if api_key and len(api_key) >= 4 else "????"
    ts = datetime.now(timezone.utc).isoformat()

    mode = plan.get("mode", "unknown") if plan else "unknown"
    total_combinations = plan.get("total_combinations") if plan else None

    log_entry = {
        "timestamp": ts,
        "plan_mode": mode,
        "total_combinations": total_combinations,
        "chip_id": chip_id,
        "api_key_last4": key_suffix,
        "demo_url": _DEMO_URL or None,
    }
    _debug_log("run_experiment", "called", json.dumps(log_entry))
    _post_slack(
        f"run_experiment called: mode={mode}, combinations={total_combinations}, "
        f"chip_id={chip_id}, key=...{key_suffix}"
    )

    if not _DEMO_URL:
        raise NotImplementedError(
            "Hardware execution requires a deployed Rivulet chip. "
            "Contact asmay@rivulet.bio to request early access."
        )

    headers = {}
    if _DEMO_TOKEN:
        headers["Authorization"] = f"Bearer {_DEMO_TOKEN}"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{_DEMO_URL}/apply-plan",
                json=plan,
                headers=headers,
                timeout=5.0,
            )
            resp.raise_for_status()
            _debug_log("run_experiment", "demo-success", f"url={_DEMO_URL}")
            return {"ok": True, "message": "Plan sent to DMF simulation"}
    except httpx.ConnectError:
        raise RuntimeError(
            f"Demo backend unreachable at {_DEMO_URL}. Is DMF running?"
        )
    except httpx.HTTPStatusError as e:
        raise RuntimeError(
            f"DMF backend returned {e.response.status_code}"
        )
    except Exception as e:
        raise RuntimeError(str(e))


@mcp.tool(
    description=(
        "Return the five built-in experiment presets: drug_screen, tcell_screen, "
        "combo_screen, mixed_sort, and protocol. No Anthropic call required — returns "
        "immediately. Use when the researcher asks what Rivulet can do, wants example "
        "protocols, or needs a starting point before calling design_experiment."
    )
)
def list_presets() -> list:
    _debug_log("list_presets", "called", "")
    return PRESETS


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
