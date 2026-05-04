"""
Tests for rivulet MCP tools and CLI.

Run: pytest tests/ -v
Requires: pip install -e ".[dev]"

Anthropic calls are mocked — no real API key needed.
"""
import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from rivulet.models import ExperimentPlan, ChecklistPhase, ChecklistStep
from rivulet.throughput import estimate_throughput
from rivulet.presets import PRESETS


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _drug_screen_plan() -> ExperimentPlan:
    return ExperimentPlan(
        mode="drug_screen",
        drug_count=5,
        cell_type="T-Cell",
        total_combinations=15,
    )


def _protocol_plan() -> ExperimentPlan:
    return ExperimentPlan(
        mode="protocol",
        protocol_plan={
            "protocol_name": "Test Protocol",
            "reagents": [],
            "steps": [
                {"id": "s0", "type": "add", "reagent_id": "r0", "label": "Load"},
                {
                    "id": "s1", "type": "mix",
                    "input_ids": ["r0"],
                    "product_id": "p0", "product_name": "P0",
                    "duration_real_s": 1800,
                    "duration_compressed_s": 5,
                    "label": "Incubate 30 min",
                    "mix_col": 35, "mix_row": 8,
                },
                {
                    "id": "s2", "type": "mix",
                    "input_ids": ["p0"],
                    "product_id": "p1", "product_name": "P1",
                    "duration_real_s": 300,
                    "duration_compressed_s": 3,
                    "label": "Wash 5 min",
                    "mix_col": 55, "mix_row": 14,
                },
            ],
            "manual_time_h": 8.5,
        },
    )


MOCK_PLAN_JSON = json.dumps({
    "mode": "drug_screen",
    "drug_count": 5,
    "cell_type": "T-Cell",
    "total_combinations": 5,
    "combinations": [],
    "steps": [],
    "raw": "",
})


async def _mock_stream(prompt: str, client):
    """Yields a minimal SSE stream matching stream_plan() output format."""
    yield f'data: {json.dumps({"type": "token", "text": MOCK_PLAN_JSON})}\n\n'
    plan = ExperimentPlan(mode="drug_screen", drug_count=5, cell_type="T-Cell", total_combinations=5)
    yield f'data: {json.dumps({"type": "done", "plan": plan.model_dump()})}\n\n'


# ── Test: design_experiment roundtrip ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_design_experiment_roundtrip():
    """Mock Anthropic — assert ExperimentPlan is returned with correct structure."""
    with patch("rivulet._planner_wrapper.stream_plan", side_effect=_mock_stream):
        from rivulet._planner_wrapper import call_planner
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key="sk-test-key")
        plan = await call_planner("screen 5 drugs against T-cells", client)
        assert isinstance(plan, ExperimentPlan)
        assert plan.mode == "drug_screen"
        assert plan.drug_count == 5


# ── Test: iterate_protocol requires a prior plan ──────────────────────────────

@pytest.mark.asyncio
async def test_iterate_without_prior_plan():
    """iterate_protocol with no plan dict should raise ValueError."""
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-key"}):
        from rivulet.mcp_server import iterate_protocol
        with pytest.raises(ValueError, match="plan parameter required"):
            await iterate_protocol(plan={}, feedback="add more drugs")


@pytest.mark.asyncio
async def test_iterate_invalid_plan():
    """iterate_protocol with garbage dict should raise ValueError."""
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-key"}):
        from rivulet.mcp_server import iterate_protocol
        with pytest.raises(ValueError, match="plan parameter required"):
            await iterate_protocol(plan={"not": "a plan", "mode": "invalid_mode"}, feedback="change it")


# ── Test: iterate_protocol after design ───────────────────────────────────────

@pytest.mark.asyncio
async def test_iterate_after_design():
    """iterate_protocol with a valid plan should return a revised plan."""
    prior = _drug_screen_plan()

    async def _mock_iterate_stream(prompt, client):
        # Return a revised plan with more drugs
        revised = ExperimentPlan(mode="drug_screen", drug_count=8, cell_type="T-Cell", total_combinations=8)
        yield f'data: {json.dumps({"type": "done", "plan": revised.model_dump()})}\n\n'

    with patch("rivulet._planner_wrapper.stream_plan", side_effect=_mock_iterate_stream):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-key"}):
            from rivulet.mcp_server import iterate_protocol
            result = await iterate_protocol(
                plan=prior.model_dump(),
                feedback="add 3 more drug concentrations",
            )
            assert result["mode"] == "drug_screen"
            assert result["drug_count"] == 8


# ── Test: estimate_throughput all modes ───────────────────────────────────────

def test_throughput_drug_screen():
    plan = ExperimentPlan(mode="drug_screen", drug_count=5)
    result = estimate_throughput(plan)
    assert result["compound_count"] == 5
    assert result["run_time_min"] == pytest.approx(0.006, rel=0.01)
    assert result["rivulet_speedup_x"] == 2400000  # 5 * 2 * 24 * 60 / 0.006
    assert "WARNING" in result


def test_throughput_combo_screen():
    plan = ExperimentPlan(mode="combo_screen", drug_count=10)
    result = estimate_throughput(plan)
    assert result["compound_count"] == 10
    assert "run_time_min" in result
    assert "rivulet_speedup_x" in result


def test_throughput_tcell_screen():
    plan = ExperimentPlan(mode="tcell_screen", drug_count=100)
    result = estimate_throughput(plan)
    assert result["compound_count"] == 100


def test_throughput_mixed_sort_default_count():
    """mixed_sort with no drug_count defaults to 1000."""
    plan = ExperimentPlan(mode="mixed_sort")
    result = estimate_throughput(plan)
    assert result["compound_count"] == 1000


def test_throughput_protocol_mode():
    """Protocol mode sums mix step duration_real_s and returns incubation_time_min."""
    plan = _protocol_plan()
    result = estimate_throughput(plan)
    # 1800 + 300 = 2100s = 35.0 min
    assert result["incubation_time_min"] == 35.0
    assert result["rivulet_speedup_x"] == "N/A"
    assert result["manual_time_h"] == 8.5
    assert "WARNING" in result


def test_throughput_zero_compound_guard():
    """ZeroDivisionError guard: drug_count=0 returns WARNING dict, not exception."""
    plan = ExperimentPlan(mode="drug_screen", drug_count=0)
    result = estimate_throughput(plan)
    assert result["compound_count"] == 0
    assert "WARNING" in result
    assert "run_time_min" not in result


def test_throughput_default_mode():
    plan = ExperimentPlan(mode="default", drug_count=50)
    result = estimate_throughput(plan)
    assert result["compound_count"] == 50
    assert "WARNING" in result


# ── Test: run_experiment stub (DEMO_URL unset) ────────────────────────────────

@pytest.mark.asyncio
async def test_run_experiment_stub():
    """run_experiment raises NotImplementedError when DEMO_URL is not set."""
    import rivulet.mcp_server as srv
    from rivulet.mcp_server import run_experiment
    original = srv._DEMO_URL
    try:
        srv._DEMO_URL = ""
        with pytest.raises(NotImplementedError) as exc_info:
            await run_experiment(plan=_drug_screen_plan().model_dump(), chip_id="chip-001")
        assert "asmay@rivulet.bio" in str(exc_info.value)
        assert "Hardware execution" in str(exc_info.value)
    finally:
        srv._DEMO_URL = original


# ── Test: run_experiment demo bridge ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_experiment_demo_success():
    """run_experiment returns ok:True when DMF backend accepts the plan."""
    import rivulet.mcp_server as srv
    from rivulet.mcp_server import run_experiment
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    orig_url, orig_token = srv._DEMO_URL, srv._DEMO_TOKEN
    try:
        srv._DEMO_URL = "http://localhost:8000"
        srv._DEMO_TOKEN = ""
        with patch("rivulet.mcp_server.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await run_experiment(plan=_drug_screen_plan().model_dump())
        assert result["ok"] is True
        assert "simulation" in result["message"]
    finally:
        srv._DEMO_URL, srv._DEMO_TOKEN = orig_url, orig_token


@pytest.mark.asyncio
async def test_run_experiment_connect_error():
    """run_experiment raises RuntimeError when DMF backend is unreachable."""
    import rivulet.mcp_server as srv
    from rivulet.mcp_server import run_experiment
    from unittest.mock import AsyncMock, patch
    import httpx as _httpx

    orig_url = srv._DEMO_URL
    try:
        srv._DEMO_URL = "http://localhost:8000"
        with patch("rivulet.mcp_server.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=_httpx.ConnectError("refused"))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            with pytest.raises(RuntimeError, match="unreachable"):
                await run_experiment(plan=_drug_screen_plan().model_dump())
    finally:
        srv._DEMO_URL = orig_url


@pytest.mark.asyncio
async def test_run_experiment_http_status_error():
    """run_experiment raises RuntimeError on 4xx/5xx from DMF backend."""
    import rivulet.mcp_server as srv
    from rivulet.mcp_server import run_experiment
    from unittest.mock import AsyncMock, MagicMock, patch
    import httpx as _httpx

    orig_url = srv._DEMO_URL
    try:
        srv._DEMO_URL = "http://localhost:8000"
        with patch("rivulet.mcp_server.httpx.AsyncClient") as MockClient:
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=_httpx.HTTPStatusError("401", request=MagicMock(), response=mock_response)
            )
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            with pytest.raises(RuntimeError, match="401"):
                await run_experiment(plan=_drug_screen_plan().model_dump())
    finally:
        srv._DEMO_URL = orig_url


@pytest.mark.asyncio
async def test_run_experiment_no_auth_header_when_token_unset():
    """run_experiment sends no Authorization header when DEMO_TOKEN is unset."""
    import rivulet.mcp_server as srv
    from rivulet.mcp_server import run_experiment
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    orig_url, orig_token = srv._DEMO_URL, srv._DEMO_TOKEN
    try:
        srv._DEMO_URL = "http://localhost:8000"
        srv._DEMO_TOKEN = ""
        with patch("rivulet.mcp_server.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            await run_experiment(plan=_drug_screen_plan().model_dump())
        _, kwargs = mock_client.post.call_args
        assert "Authorization" not in kwargs.get("headers", {})
    finally:
        srv._DEMO_URL, srv._DEMO_TOKEN = orig_url, orig_token


@pytest.mark.asyncio
async def test_run_experiment_bearer_header_when_token_set():
    """run_experiment sends Authorization: Bearer header when DEMO_TOKEN is set."""
    import rivulet.mcp_server as srv
    from rivulet.mcp_server import run_experiment
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    orig_url, orig_token = srv._DEMO_URL, srv._DEMO_TOKEN
    try:
        srv._DEMO_URL = "http://localhost:8000"
        srv._DEMO_TOKEN = "demo-secret"
        with patch("rivulet.mcp_server.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            await run_experiment(plan=_drug_screen_plan().model_dump())
        _, kwargs = mock_client.post.call_args
        assert kwargs.get("headers", {}).get("Authorization") == "Bearer demo-secret"
    finally:
        srv._DEMO_URL, srv._DEMO_TOKEN = orig_url, orig_token


# ── Test: missing API key ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_startup_missing_api_key():
    """design_experiment should raise ValueError (not crash) when API key is missing."""
    env_without_key = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    with patch.dict(os.environ, env_without_key, clear=True):
        from rivulet.mcp_server import design_experiment
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY not set"):
            await design_experiment(prompt="screen 5 drugs")


# ── Test: list_presets ────────────────────────────────────────────────────────

def test_list_presets_returns_five():
    """list_presets returns exactly 5 presets."""
    from rivulet.mcp_server import list_presets
    result = list_presets()
    assert len(result) == 5


def test_list_presets_modes():
    """All expected modes are present in presets."""
    from rivulet.mcp_server import list_presets
    modes = {p["mode"] for p in list_presets()}
    assert modes == {"drug_screen", "tcell_screen", "combo_screen", "mixed_sort", "protocol"}


def test_list_presets_json_format():
    """Each preset has required fields."""
    from rivulet.mcp_server import list_presets
    for preset in list_presets():
        assert "id" in preset
        assert "name" in preset
        assert "mode" in preset
        assert "description" in preset
        assert "prompt" in preset
