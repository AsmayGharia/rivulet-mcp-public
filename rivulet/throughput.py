"""
Throughput estimation for ExperimentPlan.

Constants are pre-validation estimates — NOT benchmarked numbers.
Do not share these as hard commitments with paying customers until
validated against actual chip throughput data.
"""
from rivulet.models import ExperimentPlan

# Rivulet throughput estimate: 50,000 combinations per hour
_RIVULET_COMBINATIONS_PER_HOUR = 50_000

# Traditional plate-based lab: ~2 days per compound (plate assay, readout, analysis)
# Validated against: 15 compounds → run_time_min 0.018 → speedup 2,400,000
_TRADITIONAL_DAYS_PER_COMPOUND = 2.0

_WARNING = "Pre-validation estimate. Contact team for benchmarked numbers."


def estimate_throughput(plan: ExperimentPlan) -> dict:
    """
    Calculate runtime and throughput estimates for an ExperimentPlan.

    Returns a dict with run_time_min, compound_count, rivulet_speedup_x,
    and a WARNING field. For protocol mode, returns incubation_time_min instead.

    Guard: if compound_count == 0 (e.g. drug_count not set), returns a WARNING dict
    rather than raising ZeroDivisionError.
    """
    mode = plan.mode

    if mode in ("drug_screen", "combo_screen", "tcell_screen"):
        drug_count = plan.drug_count or 0
        compound_count = drug_count  # single cell type; cell_type_count = 1
        if compound_count == 0:
            return {
                "compound_count": 0,
                "WARNING": f"compound_count is 0 — check drug_count in plan. {_WARNING}",
            }
        run_time_min = compound_count / _RIVULET_COMBINATIONS_PER_HOUR * 60
        traditional_time_min = compound_count * _TRADITIONAL_DAYS_PER_COMPOUND * 24 * 60
        rivulet_speedup_x = round(traditional_time_min / run_time_min)
        return {
            "run_time_min": round(run_time_min, 3),
            "compound_count": compound_count,
            "rivulet_speedup_x": rivulet_speedup_x,
            "WARNING": _WARNING,
        }

    elif mode == "mixed_sort":
        compound_count = plan.drug_count or 1000
        if compound_count == 0:
            return {
                "compound_count": 0,
                "WARNING": f"compound_count is 0. {_WARNING}",
            }
        run_time_min = compound_count / _RIVULET_COMBINATIONS_PER_HOUR * 60
        traditional_time_min = compound_count * _TRADITIONAL_DAYS_PER_COMPOUND * 24 * 60
        rivulet_speedup_x = round(traditional_time_min / run_time_min)
        return {
            "run_time_min": round(run_time_min, 3),
            "compound_count": compound_count,
            "rivulet_speedup_x": rivulet_speedup_x,
            "WARNING": _WARNING,
        }

    elif mode == "protocol":
        total_real_s = 0.0
        manual_time_h = None
        if plan.protocol_plan and isinstance(plan.protocol_plan, dict):
            steps = plan.protocol_plan.get("steps", [])
            for step in steps:
                if isinstance(step, dict) and step.get("type") == "mix":
                    total_real_s += float(step.get("duration_real_s", 0) or 0)
            manual_time_h = plan.protocol_plan.get("manual_time_h")
        result: dict = {
            "incubation_time_min": round(total_real_s / 60, 1),
            "rivulet_speedup_x": "N/A",
            "WARNING": _WARNING,
        }
        if manual_time_h is not None:
            result["manual_time_h"] = manual_time_h
        return result

    else:  # default — best-effort from available fields
        compound_count = plan.drug_count
        run_time_min = None
        rivulet_speedup_x = None
        if compound_count:
            run_time_min = round(compound_count / _RIVULET_COMBINATIONS_PER_HOUR * 60, 3)
        return {
            "run_time_min": run_time_min,
            "compound_count": compound_count,
            "rivulet_speedup_x": rivulet_speedup_x,
            "WARNING": _WARNING,
        }
