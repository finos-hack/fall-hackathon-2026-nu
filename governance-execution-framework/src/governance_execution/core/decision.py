"""Governance_Decision: gates, then Decision_Matrix, then the design-only cap (Req 19). Pure; no LLM or Decider input."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

from agip_shared.contracts import ControlGapAssessment, Decision, RiskProfile

from . import gates as gates_mod

CONFIG = Path(__file__).resolve().parents[3] / "config" / "decision_matrix.yaml"


def load_matrix(path: Path = CONFIG) -> dict[str, Any]:
    """Load the Decision_Matrix YAML (default ``config/decision_matrix.yaml``)."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def decide(calm_status: str, gap: Optional[ControlGapAssessment], profile: Optional[RiskProfile],
           gates: dict[str, Any], matrix: dict[str, Any]) -> Decision:
    """Evaluate gates first, then the gap x risk matrix cell, then the design-only cap. Raises ValueError unless ``calm_status`` is VALID."""
    if calm_status != "VALID":
        raise ValueError(f"no decision for CALM validation status {calm_status}: the assessment is BLOCKED")
    inputs = {"calm_status": calm_status,
              "control_status": {c.control_id: c.status for c in (gap.controls if gap else [])},
              "mandatory_trigger": profile.mandatory_trigger if profile else None}
    winner, record = gates_mod.evaluate(gates, inputs)
    versions = {"gates_version": gates.get("version"), "matrix_version": matrix.get("version")}
    if winner is not None:
        return Decision(decision=winner["outcome"], gates_evaluated=record,
                        matrix_cell={"evaluated": False, "reason": f"gate {winner['id']} fired", **versions})
    if gap is None or profile is None or gap.gap_level == "INDETERMINATE_INPUT" or profile.profile_level is None:
        return Decision(decision="INDETERMINATE", gates_evaluated=record,
                        matrix_cell={"evaluated": False, "reason": "gap or risk input indeterminate", **versions})
    risks = matrix["rows"]["risk"]
    result = matrix["cells"][gap.gap_level][risks.index(profile.profile_level)]
    cell = {"evaluated": True, "gap": gap.gap_level, "risk": profile.profile_level, "result": result, **versions}
    conditions: list[str] = []
    cap = matrix.get("design_only_cap") or {}
    # a design-only assessment cannot grant the top outcome; cap it down
    if result == cap.get("from"):
        cell["design_only_cap"] = f"{cap['from']} -> {cap['to']}"
        result = cap["to"]
    if result == "APPROVED_WITH_CONDITIONS":
        conditions.append(cap.get("condition", "design approved; build-time and runtime evidence required"))
    return Decision(decision=result, gates_evaluated=record, matrix_cell=cell, conditions=conditions)
