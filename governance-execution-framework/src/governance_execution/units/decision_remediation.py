"""Decision & Remediation unit (Req 19, 20.2, 20.3, 20.5).

``decide`` is pure and uses no LLM or Decider input. ``remediate`` collects catalog remediation text from
failed controls and triggered risks and asks the ModelGateway for a Fix Prompt; with no LLM (mode
``no-llm`` or model unavailable) it returns the deterministic list. It never edits CALM and never
changes the decision: the decision is copied into the output for display only.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from agip_shared.contracts import ControlGapAssessment, Decision, RiskProfile
from agip_shared.gateway import ModelGateway, ModelUnavailableError, RecordingMissingError

from ..core import decision as decision_core

PROMPT_ID, PROMPT_VERSION = "remediation", "v1"
PROMPT_FILE = Path(__file__).resolve().parents[3] / "prompts" / "remediation.v1.md"

decide = decision_core.decide


def collect(gap: Optional[ControlGapAssessment], profile: Optional[RiskProfile],
            calm_guidance: Optional[list[str]] = None) -> list[dict[str, Any]]:
    """Gather remediation items from CALM guidance, failed controls and triggered risks, in that order."""
    items: list[dict[str, Any]] = []
    for g in calm_guidance or []:
        items.append({"id": "CALM", "kind": "calm_validation", "text": g})
    for c in (gap.controls if gap else []):
        if c.status == "FAIL" and c.remediation:
            items.append({"id": c.control_id, "kind": "control", "text": c.remediation, "rule_codes": c.rule_codes})
    for r in (profile.risks if profile else []):
        if r.remediation:
            items.append({"id": r.risk_id, "kind": "risk", "text": r.remediation, "rule_codes": r.triggered_by})
    return items


def deterministic_list(items: list[dict[str, Any]]) -> list[str]:
    """Number the items as plain-text lines; the fallback when no LLM output is available."""
    return [f"{i + 1}. {it['text']} [{it['id']}]" for i, it in enumerate(items)]


def remediate(decision: Optional[Decision], items: list[dict[str, Any]], gateway: Optional[ModelGateway],
              mode: str = "normal") -> dict[str, Any]:
    """Raises RecordingMissingError only in replay mode (replay must name the missing record)."""
    out: dict[str, Any] = {"decision": decision.decision if decision else None,
                           "conditions": list(decision.conditions) if decision else [], "items": items,
                           "deterministic_list": deterministic_list(items), "fix_prompt": None, "summary": None,
                           "source": "deterministic", "prompt_version": PROMPT_VERSION, "model": None, "reason": None}
    if not items:
        out["reason"] = "nothing to remediate"
        return out
    if decision is None:   # blocked run: only the deterministic CALM correction list, no model call
        out["reason"] = "assessment blocked: CALM correction list only"
        return out
    if mode == "no-llm" or gateway is None:
        out["reason"] = "no-LLM mode"
        return out
    try:
        rec = gateway.complete(PROMPT_ID, PROMPT_VERSION,
                               {"decision": {"decision": decision.decision if decision else None,
                                             "conditions": decision.conditions if decision else []},
                                "items": [{"id": i["id"], "text": i["text"]} for i in items]},
                               prompt=PROMPT_FILE.read_text(encoding="utf-8"))
    except RecordingMissingError:
        if mode == "replay":
            raise
        out["reason"] = "no recorded remediation output"
        return out
    except ModelUnavailableError as exc:
        out["reason"] = f"LLM unavailable: {exc}"
        return out
    o = rec.output if isinstance(rec.output, dict) else {"fix_prompt": str(rec.output)}
    out.update(fix_prompt=o.get("fix_prompt"), summary=o.get("summary"), source="llm", model=rec.model,
               input_hash=rec.input_hash)
    return out


# ---- human review of the remediation (task 24.4): recorded, never changes the decision -------------------------
def request_remediation_review(store: Any, trace_id: str, requested_by: str) -> Any:
    """Create a REMEDIATION_REVIEW human task for the trace and return it. Raises whatever ``store.create`` raises (e.g. if the task already exists)."""
    from agip_shared.contracts import HumanTask
    return store.create(HumanTask(
        task_id=f"remediation-review-{trace_id}", framework="governance_execution", task_type="REMEDIATION_REVIEW",
        subject_refs=["remediation:result", "decision:result"], trace_id=trace_id, role=store.roles["REMEDIATION_REVIEW"][0],
        context={"trace_id": trace_id, "created_by": requested_by}))


def remediation_review_outcome(store: Any, task_id: str) -> dict[str, Any]:
    """The reviewer's verdict as a record. It carries no decision field: the decision artifact is the only source."""
    task = store.get(task_id)
    done = [o for o in store.outcomes(task_id) if o.resulting_state in ("COMPLETED", "REJECTED")]
    o = done[-1] if done else None
    return {"task_id": task_id, "trace_id": task.trace_id, "status": task.status, "reviewer": o.actor if o else None,
            "role": o.role if o else None, "rationale": o.rationale if o else None}