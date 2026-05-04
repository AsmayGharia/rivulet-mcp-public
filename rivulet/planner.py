"""
NL experiment planner — calls Anthropic API, returns structured ExperimentPlan.
"""
import json
import re
from typing import AsyncGenerator

import anthropic

from rivulet.models import ExperimentPlan, ChecklistPhase, ChecklistStep, CombinationSpec, ControlSpec

SYSTEM_PROMPT = """You are an experiment planner for a digital microfluidics platform.

Given a natural-language experiment description, return a structured JSON experiment plan.
The JSON must conform to the ExperimentPlan schema (see rivulet/models.py).

Available experiment modes: drug_screen, combo_screen, mixed_sort, tcell_screen, protocol, default

Respond with a JSON object ONLY. No explanation, no markdown fences.

# ─────────────────────────────────────────────────────────────────────────────
# PLACEHOLDER — replace with your hardware-specific system prompt.
#
# Your prompt should include:
#   - Field-by-field instructions for each ExperimentPlan field
#   - Example JSON outputs for each experiment mode
#   - Rules for mapping natural language to structured fields (drug counts,
#     cell types, output gate assignments, combination layouts, etc.)
#   - Any hardware- or simulation-specific constraints for your platform
#
# See rivulet/models.py for the full ExperimentPlan schema.
# ─────────────────────────────────────────────────────────────────────────────
"""


def _parse_mode(prompt: str) -> str:
    p = prompt.lower()
    # Priority order: mixed_sort > combo_screen > protocol > drug_screen > tcell_screen > default
    if 'sort' in p or 'mixed' in p:
        return 'mixed_sort'
    if 'combo' in p or '4-arm' in p or 'combinatorial' in p:
        return 'combo_screen'
    if any(kw in p for kw in ('protocol', 'prep', 'lysis', 'lyse', 'digest', 'reagent', 'wash', 'incubate', 'incubation')):
        return 'protocol'
    if 'tcell' in p or 't-cell' in p or 't cell' in p:
        return 'tcell_screen'
    if 'drug' in p or 'compound' in p:
        return 'drug_screen'
    return 'default'


def _parse_drug_count(prompt: str) -> int:
    # Match frontend extractCount: take the largest number in the prompt.
    # "500 myeloid cells" → 500, "10 million droplets" → 10_000_000.
    nums = []
    for m in re.finditer(r'([\d,]+)\s*(million|billion|thousand|k)?', prompt, re.IGNORECASE):
        base = int(m.group(1).replace(',', ''))
        mul = {'million': 1_000_000, 'billion': 1_000_000_000, 'thousand': 1_000, 'k': 1_000}.get(
            (m.group(2) or '').lower(), 1)
        nums.append(base * mul)
    return max(nums) if nums else 200


def _parse_input_gate(prompt: str) -> int:
    m = re.search(r'(?:input|gate)\s*(?:number\s*)?(\d+)', prompt, re.IGNORECASE)
    return int(m.group(1)) if m else 5


async def stream_plan(prompt: str, client: anthropic.AsyncAnthropic) -> AsyncGenerator[str, None]:
    """
    Stream SSE events from the Anthropic API.
    Yields SSE-formatted strings.

    Event types:
      data: {"type": "token", "text": "..."}     — streaming text chunk
      data: {"type": "done", "plan": {...}}        — final structured plan
      data: {"type": "error", "message": "..."}   — error
    """
    full_text = ''

    try:
        async with client.messages.stream(
            model='claude-haiku-4-5-20251001',
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{'role': 'user', 'content': prompt}],
        ) as stream:
            async for text in stream.text_stream:
                full_text += text
                yield f'data: {json.dumps({"type": "token", "text": text})}\n\n'

        # Parse the JSON plan from the full response
        plan = _build_plan(prompt, full_text)
        yield f'data: {json.dumps({"type": "done", "plan": plan.model_dump()})}\n\n'

    except anthropic.APIError as e:
        yield f'data: {json.dumps({"type": "error", "message": str(e)})}\n\n'
    except Exception as e:
        yield f'data: {json.dumps({"type": "error", "message": f"Unexpected error: {e}"})}\n\n'


def _build_plan(prompt: str, llm_response: str) -> ExperimentPlan:
    """Parse LLM JSON response into ExperimentPlan, with fallback."""
    # Try to extract JSON from response
    raw = llm_response.strip()

    # Strip markdown code fences if present
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)

    try:
        data = json.loads(raw)
        if data.get('mode') == 'protocol':
            return _build_protocol_plan(data, llm_response)
        # Validate and coerce into Pydantic model
        plan = ExperimentPlan(**{k: v for k, v in data.items() if k in ExperimentPlan.model_fields})
        plan.raw = llm_response
        return plan
    except Exception:
        # Fallback: use regex-derived metadata + default steps
        mode = _parse_mode(prompt)
        if mode == 'protocol':
            return _fallback_protocol_plan(prompt, llm_response)
        return _fallback_plan(prompt, llm_response)


def _build_protocol_plan(data: dict, raw: str) -> ExperimentPlan:
    """Build an ExperimentPlan wrapping a ProtocolPlan for protocol mode."""
    protocol_plan = {
        'protocol_name': data.get('protocol_name', 'Protocol'),
        'reagents': data.get('reagents', []),
        'steps': data.get('steps', []),
        'manual_time_h': data.get('manual_time_h'),
    }
    return ExperimentPlan(
        mode='protocol',
        protocol_plan=protocol_plan,
        combinations=[],
        raw=raw,
    )


def _fallback_protocol_plan(prompt: str, raw: str) -> ExperimentPlan:
    """Fallback protocol plan when Claude returns malformed JSON for protocol mode."""
    protocol_plan = {
        'protocol_name': 'Proteomics Sample Prep',
        'reagents': [
            {'id': 'r0', 'label': 'PBS + Cells', 'color_hex': '#4FC3F7', 'volume_nL': 55},
            {'id': 'r1', 'label': 'Lysis Buffer', 'color_hex': '#FFB74D', 'volume_nL': 25},
            {'id': 'r2', 'label': 'Reducing Agent', 'color_hex': '#CE93D8', 'volume_nL': 50},
            {'id': 'r3', 'label': 'Digest Solution', 'color_hex': '#A5D6A7', 'volume_nL': 20},
            {'id': 'r4', 'label': 'Acidic Quench', 'color_hex': '#EF9A9A', 'volume_nL': 300},
        ],
        'steps': [
            {'id': 's0', 'type': 'add', 'reagent_id': 'r0', 'label': 'Load PBS + Cells'},
            {'id': 's1', 'type': 'add', 'reagent_id': 'r1', 'label': 'Add lysis buffer'},
            {
                'id': 's2', 'type': 'mix',
                'input_ids': ['r0', 'r1'],
                'product_id': 'p0', 'product_name': 'Cell Lysate', 'product_color_hex': '#FF8A65',
                'duration_real_s': 300, 'duration_compressed_s': 5,
                'label': 'Lyse cells (5 min)', 'mix_col': 35, 'mix_row': 8,
            },
            {'id': 's3', 'type': 'add', 'reagent_id': 'r2', 'label': 'Add reducing agent'},
            {
                'id': 's4', 'type': 'mix',
                'input_ids': ['p0', 'r2'],
                'product_id': 'p1', 'product_name': 'Denatured Sample', 'product_color_hex': '#BA68C8',
                'duration_real_s': 1200, 'duration_compressed_s': 8,
                'label': 'Denature proteins (20 min)', 'mix_col': 55, 'mix_row': 14,
            },
            {'id': 's5', 'type': 'add', 'reagent_id': 'r3', 'label': 'Add digest solution'},
            {
                'id': 's6', 'type': 'mix',
                'input_ids': ['p1', 'r3'],
                'product_id': 'p2', 'product_name': 'Digested Peptides', 'product_color_hex': '#66BB6A',
                'duration_real_s': 5400, 'duration_compressed_s': 12,
                'label': 'Trypsin digest (90 min)', 'mix_col': 70, 'mix_row': 20,
            },
            {'id': 's7', 'type': 'add', 'reagent_id': 'r4', 'label': 'Add acidic quench'},
            {
                'id': 's8', 'type': 'mix',
                'input_ids': ['p2', 'r4'],
                'product_id': 'p3', 'product_name': 'Quenched Sample', 'product_color_hex': '#EF5350',
                'duration_real_s': 60, 'duration_compressed_s': 3,
                'label': 'Quench reaction (1 min)', 'mix_col': 82, 'mix_row': 14,
            },
        ],
        'manual_time_h': 8.5,
    }
    return ExperimentPlan(
        mode='protocol',
        protocol_plan=protocol_plan,
        combinations=[],
        raw=raw,
    )


def _fallback_plan(prompt: str, raw: str) -> ExperimentPlan:
    mode = _parse_mode(prompt)
    return ExperimentPlan(
        mode=mode,
        drug_count=_parse_drug_count(prompt),
        input_gate=_parse_input_gate(prompt),
        steps=[
            ChecklistPhase(id='loading', label='Loading', state='pending', steps=[
                ChecklistStep(id='load-sample', label='Load biological sample', state='pending'),
                ChecklistStep(id='load-drug', label='Load drug compounds', state='pending'),
                ChecklistStep(id='calibrate', label='Calibrate impedance array', state='pending'),
            ]),
            ChecklistPhase(id='reacting', label='Reacting', state='pending', steps=[
                ChecklistStep(id='route', label='Route particles to reaction zone', state='pending'),
                ChecklistStep(id='merge', label='Initiate DEP-driven merge', state='pending'),
            ]),
            ChecklistPhase(id='measuring', label='Measuring', state='pending', steps=[
                ChecklistStep(id='impedance', label='Multi-frequency impedance scan', state='pending'),
                ChecklistStep(id='fluorescence', label='Fluorescence readout', state='pending'),
            ]),
            ChecklistPhase(id='complete', label='Complete', state='pending', steps=[
                ChecklistStep(id='collect', label='Collect sorted outputs', state='pending'),
                ChecklistStep(id='report', label='Generate assay report', state='pending'),
            ]),
        ],
        raw=raw,
    )
