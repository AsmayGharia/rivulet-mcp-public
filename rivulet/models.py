"""
Data models for Rivulet experiment plans.
Copied from DMF-sandbox-3/backend/models.py at v0.1.0.
Mirror changes from backend manually until rivulet-core is extracted.
"""
from pydantic import BaseModel, Field
from typing import Any, Literal, Optional


class PlanRequest(BaseModel):
    prompt: str


class ChecklistStep(BaseModel):
    id: str
    label: str
    state: Literal['pending', 'active', 'complete'] = 'pending'


class ChecklistPhase(BaseModel):
    id: str
    label: str
    state: Literal['pending', 'active', 'completed'] = 'pending'
    steps: list[ChecklistStep] = []


class CombinationSpec(BaseModel):
    id: str
    particleTypes: list[str]     # e.g. ['myeloid', 'droplet_cell']
    inletLanes: list[int]        # one lane index per particle
    stagingCol: int
    stagingRow: int
    rendezvousCol: int
    rendezvousRow: int


class ControlSpec(BaseModel):
    negative: Optional[int] = None
    positive: Optional[int] = None


class ExperimentPlan(BaseModel):
    mode: Literal['default', 'tcell_screen', 'drug_screen', 'combo_screen', 'mixed_sort', 'protocol'] = 'drug_screen'
    cell_type: Optional[str] = None
    drug_count: Optional[int] = None
    input_gate: Optional[int] = None
    steps: list[ChecklistPhase] = []
    combinations: list[CombinationSpec] = []
    controls: Optional[ControlSpec] = None
    total_combinations: Optional[int] = None
    output_routes: Optional[list] = None  # list of {gate, condition, label?, particle_type?}
    protocol_plan: Optional[Any] = None  # ProtocolPlan dict — passed through as-is to frontend
    raw: str = ''
