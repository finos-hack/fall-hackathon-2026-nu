"""AssessmentRequirements (one per control configuration) and Evidence from Spectral results.

A Spectral PASS is design-level only: Evidence maturity DESIGN, evaluation PASS. Requirements that need
IMPLEMENTATION or OPERATING evidence are NOT_VERIFIED until such evidence is supplied; missing evidence is never PASS.
Not yet called by the coordinator; ``units/control_assessment`` or the coordinator can call ``build_evidence``.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from agip_shared.contracts import AssessmentRequirement, Evidence, SpectralRun
from agip_shared.hashing import canonical_json, sha256_hex

from . import catalogs

MATURITIES = ("DESIGN", "IMPLEMENTATION", "OPERATING")


def requirement_id(control_id: str, cfg_id: str, maturity: str = "DESIGN") -> str:
    """Stable requirement id: ``control:config`` for DESIGN, with a ``:MATURITY`` suffix for other maturities."""
    base = f"{control_id}:{cfg_id}"
    return base if maturity == "DESIGN" else f"{base}:{maturity}"


def build_requirements(controls_catalog: dict[str, Any],
                       extra_maturities: Iterable[str] = ()) -> list[AssessmentRequirement]:
    """One DESIGN requirement per control configuration; ``extra_maturities`` adds IMPLEMENTATION/OPERATING ones."""
    out: list[AssessmentRequirement] = []
    for item in sorted(catalogs.approved(controls_catalog), key=lambda i: i["control_id"]):
        for cfg in item.get("configurations") or []:
            for m in ("DESIGN", *extra_maturities):
                out.append(AssessmentRequirement(
                    requirement_id=requirement_id(item["control_id"], cfg["id"], m), control_id=item["control_id"],
                    description=f"{item.get('title', item['control_id'])} / {cfg['id']}", required_maturity=m,
                    evidence_criteria=[f"no Spectral finding for {c}" for c in cfg.get("rule_codes") or []]
                    if m == "DESIGN" else [f"{m.lower()} evidence supplied and reviewed"],
                    source={"rule_codes": list(cfg.get("rule_codes") or []), "config_id": cfg["id"],
                            "mandatory": bool(cfg.get("mandatory")), **(item.get("source") or {})}))
    return out


def build_evidence(requirements: list[AssessmentRequirement], run: SpectralRun, app_id: str,
                   app_version: str | None = None) -> list[Evidence]:
    """One Evidence per requirement. DESIGN comes from the Spectral run (ERROR/FAIL/PASS); higher maturities are always NOT_VERIFIED."""
    fired = {r.code for r in run.results}
    out: list[Evidence] = []
    for req in requirements:
        if req.required_maturity == "DESIGN":
            codes = req.source.get("rule_codes") or []
            status = "ERROR" if run.status == "ERROR" else ("FAIL" if fired & set(codes) else "PASS")
            payload = {"requirement": req.requirement_id, "status": status, "spectral_version": run.version,
                       "findings": sorted(fired & set(codes))}
            out.append(Evidence(evidence_id=f"EV-{req.requirement_id}", requirement_id=req.requirement_id,
                                evidence_type="spectral", source="spectral", app_id=app_id, app_version=app_version,
                                sha256=sha256_hex(canonical_json(payload)), maturity="DESIGN", evaluation_status=status,
                                rationale="design-level evidence only"))
        else:
            payload = {"requirement": req.requirement_id, "status": "NOT_VERIFIED"}
            out.append(Evidence(evidence_id=f"EV-{req.requirement_id}", requirement_id=req.requirement_id,
                                evidence_type="none", source="none", app_id=app_id, app_version=app_version,
                                sha256=sha256_hex(canonical_json(payload)), maturity=req.required_maturity,
                                evaluation_status="NOT_VERIFIED", rationale="no evidence supplied"))
    return out


# ---- human review of evidence (task 24.4) ---------------------------------------------------------------------
def request_evidence_review(store: Any, ev: Evidence, requested_by: str) -> Any:
    """Create an EVIDENCE_REVIEW HumanTask for ``ev`` in ``store``, assigned to the store's first evidence-review role."""
    from agip_shared.contracts import HumanTask
    return store.create(HumanTask(
        task_id="evidence-review-" + re.sub(r"[^A-Za-z0-9_.-]", "_", ev.evidence_id), framework="governance_execution", task_type="EVIDENCE_REVIEW",
        subject_refs=[f"evidence:{ev.evidence_id}"], role=store.roles["EVIDENCE_REVIEW"][0],
        context={"evidence_id": ev.evidence_id, "created_by": requested_by, "outcome_convention":
                 "outcome_artifact_id is PASS or FAIL when COMPLETED"}))


def apply_evidence_review(store: Any, task_id: str, ev: Evidence) -> Evidence:
    """COMPLETED with PASS/FAIL -> reviewed evidence; REJECTED -> INVALID evidence. Never raises a status by itself."""
    done = [o for o in store.outcomes(task_id) if o.resulting_state in ("COMPLETED", "REJECTED")]
    if not done:
        return ev
    o = done[-1]
    if o.resulting_state == "REJECTED":
        return ev.model_copy(update={"validity": "INVALID", "reviewer": o.actor, "rationale": o.rationale})
    status = o.outcome_artifact_id if o.outcome_artifact_id in ("PASS", "FAIL") else ev.evaluation_status
    return ev.model_copy(update={"evaluation_status": status, "reviewer": o.actor, "rationale": o.rationale})