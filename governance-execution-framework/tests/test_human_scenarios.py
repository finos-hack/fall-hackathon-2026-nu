"""Task 24.4: one test per human-in-the-loop scenario, all through the shared HumanTask contract.

The decision always comes from ``agip_shared.humantasks.HumanTaskStore`` (server-side role check, no self-approval).
This test imports the three frameworks; the frameworks do not import each other.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from agip_shared.humantasks import HumanTaskStore, NotAuthorized
from calm_generation import lifecycle, pattern_library
from governance_execution.core import evidence as ev_core
from governance_execution.core import risk_acceptance as ra
from governance_execution.exec import factory
from governance_execution.store.repository import MemoryRepository
from governance_execution.units import decision_remediation, risk_assessment
from rule_authoring import approval
sys.path.insert(0, str(Path(__file__).parent))
from test_human_resume import SETTINGS, TPL, TEXT, FORM, _build, _start

from agip_shared.hashing import canonical_hash
from governance_execution.units.calm_builder import instantiate

ROOT = Path(__file__).resolve().parents[2]


def decide(store, tid, actor, role, action="COMPLETE", why="reviewed", value=None):
    store.act(tid, actor, role, "CLAIM", "claim")
    return store.act(tid, actor, role, action, why, outcome_artifact_id=value)


@pytest.fixture
def store(tmp_path):
    return HumanTaskStore(tmp_path / "data")


# ---- 1. rule review (RULE_REVIEW) -----------------------------------------------------------------------------
def test_rule_review_approves_and_rejects_through_task(tmp_path, store):
    cat = tmp_path / "controls.catalog.yaml"
    cat.write_text(yaml.safe_dump({"items": [{"control_id": "C1", "status": "DRAFT", "version": 1},
                                             {"control_id": "C2", "status": "DRAFT", "version": 1},
                                             {"control_id": "C3", "status": "DRAFT", "version": 1}]}), encoding="utf-8")
    for cid in ("C1", "C2", "C3"):
        approval.transition_in_catalog(cat, cid, "IN_REVIEW", "author", "author", "submit")
        approval.request_review(store, cid, "author")
    with pytest.raises(NotAuthorized):                       # wrong role
        store.act("rule-review-C1", "eve", "developer", "CLAIM", "x")
    with pytest.raises(NotAuthorized):                       # the author may not approve their own rule
        decide(store, "rule-review-C3", "author", "rule_reviewer")
    decide(store, "rule-review-C1", "rita", "rule_reviewer", why="rule is sound")
    decide(store, "rule-review-C2", "rita", "rule_reviewer", "REJECT", "rule too broad")
    approval.apply_review(store, "rule-review-C1", cat)
    approval.apply_review(store, "rule-review-C2", cat)
    items = {i["control_id"]: i for i in yaml.safe_load(cat.read_text(encoding="utf-8"))["items"]}
    assert items["C1"]["status"] == "APPROVED" and items["C1"]["history"][-1]["by"] == "rita"
    assert items["C2"]["status"] == "REJECTED" and items["C2"]["history"][-1]["rationale"] == "rule too broad"


# ---- 2. risk likelihood/impact confirmation (RISK_LI_CONFIRMATION) --------------------------------------------
def test_risk_li_confirmation_gates_approval(tmp_path, store):
    cat = tmp_path / "risks.catalog.yaml"
    cat.write_text(yaml.safe_dump({"items": [{"risk_id": "R1", "type": "risk", "status": "DRAFT", "version": 1,
                                              "likelihood": 3, "impact": 4}]}), encoding="utf-8")
    approval.transition_in_catalog(cat, "R1", "IN_REVIEW", "author", "author", "submit")
    approval.request_review(store, "R1", "author", "RISK_LI_CONFIRMATION")
    with pytest.raises(approval.ApprovalError):               # not confirmed yet: approval refused
        approval.transition_in_catalog(cat, "R1", "APPROVED", "rita", "rule_reviewer", "ok")
    decide(store, "risk-li-confirmation-R1", "ana", "risk_analyst", why="3x4 is right")
    entry = approval.apply_review(store, "risk-li-confirmation-R1", cat)
    assert entry["confirmation"]["by"] == "ana" and (entry["confirmation"]["likelihood"], entry["confirmation"]["impact"]) == (3, 4)
    assert approval.transition_in_catalog(cat, "R1", "APPROVED", "rita", "rule_reviewer", "ok")["status"] == "APPROVED"


# ---- 3. pattern approval and 4. RA approval -------------------------------------------------------------------
def _registry(tmp_path, key, **entry):
    reg = tmp_path / "lifecycle.yaml"
    seed = lifecycle.load()
    entries = {key: {**seed["entries"].get(key, {}), "state": "IN_REVIEW", **entry}} if key in seed["entries"] else {key: {"state": "IN_REVIEW", **entry}}
    lifecycle.save({"entries": entries}, reg)
    return reg


def test_pattern_approval_through_task(tmp_path, store):
    reg = _registry(tmp_path, "P02")
    lifecycle.request_approval(store, "P02", "author", reg)
    decide(store, "pattern-approval-P02", "ada", "architect", why="fits the reference architecture")
    e = lifecycle.apply_approval(store, "pattern-approval-P02", reg, patterns=pattern_library.load_patterns())
    assert e["state"] == "APPROVED" and e["history"][-1]["by"] == "ada" and e["history"][-1]["role"] == "architect"


def test_ra_approval_through_task(tmp_path, store):
    reg = _registry(tmp_path, "RA-T", kind="ra", version=1, history=[])
    lifecycle.request_approval(store, "RA-T", "author", reg)
    with pytest.raises(NotAuthorized):                        # architect may not approve an RA
        store.act("ra-approval-RA-T", "ada", "architect", "CLAIM", "x")
    decide(store, "ra-approval-RA-T", "rob", "risk_approver", "REJECT", "template incomplete")
    e = lifecycle.apply_approval(store, "ra-approval-RA-T", reg)
    assert e["state"] == "REJECTED" and e["history"][-1]["by"] == "rob"


# ---- 5. Decider classification review: stop, decide, resume (see test_human_resume for restart/CLI) ------------
def test_decider_classification_review_resumes_to_decision(tmp_path):
    out = _start(tmp_path)
    assert out.status == "WAITING_FOR_HUMAN" and out.decision is None
    tid = out.pending_human_tasks[0]
    store = HumanTaskStore(tmp_path)
    decide(store, tid, "ana", "risk_analyst", value=store.get(tid).context["allowed_values"][0])
    coord, ex = _build(tmp_path)
    done = coord.resume(out.trace_id, executor=ex)
    assert done.status == "COMPLETED" and done.decision and "evidence" in done.artifacts


# ---- 6. evidence review (EVIDENCE_REVIEW) ---------------------------------------------------------------------
def test_evidence_review_enables_residual_reduction_only_after_pass(store):
    controls = yaml.safe_load((ROOT / "rule-authoring-framework" / "catalogs" / "controls.catalog.yaml").read_text(encoding="utf-8"))
    reqs = ev_core.build_requirements(controls, extra_maturities=("IMPLEMENTATION",))
    req = next(r for r in reqs if r.required_maturity == "IMPLEMENTATION")
    run = risk_assessment.SpectralRun(status="OK", results=[])
    ev = next(e for e in ev_core.build_evidence(reqs, run, "app") if e.requirement_id == req.requirement_id)
    item = {"linked_controls": [req.control_id]}
    assert ev.evaluation_status == "NOT_VERIFIED"
    assert risk_assessment.residual_severity(item, "High", [ev], reqs) == "High"
    tid = ev_core.request_evidence_review(store, ev, "author").task_id
    decide(store, tid, "erin", "evidence_reviewer", why="pen-test report checked", value="PASS")
    reviewed = ev_core.apply_evidence_review(store, tid, ev)
    assert reviewed.evaluation_status == "PASS" and reviewed.reviewer == "erin"
    assert risk_assessment.residual_severity(item, "High", [reviewed], reqs) == "Medium"


# ---- 7. remediation review (REMEDIATION_REVIEW): recorded, never changes the decision -------------------------
def test_remediation_review_records_outcome_and_keeps_decision(tmp_path):
    coord, ex = factory.build("no-llm", settings=SETTINGS, repo=MemoryRepository(tmp_path), data_dir=tmp_path, cli="replay")
    r = instantiate(FORM, template=TPL, template_text=TEXT, template_status="PUBLISHED", calm=coord.ctx.calm)
    out = coord.run(r.app_model, executor=ex, template_id="RA03-LITE", source={"app_id": "v1"})
    assert out.status == "COMPLETED"
    before = (out.decision, canonical_hash(coord.ctx.sink.get(out.trace_id, "decision", "result")))
    store = HumanTaskStore(tmp_path)
    decision_remediation.request_remediation_review(store, out.trace_id, "system")
    tid = f"remediation-review-{out.trace_id}"
    decide(store, tid, "ana", "risk_analyst", why="fix guidance is clear")
    rec = decision_remediation.remediation_review_outcome(store, tid)
    coord.ctx.sink.put(out.trace_id, "remediation_review", "result", rec)
    assert rec["status"] == "COMPLETED" and rec["reviewer"] == "ana" and "decision" not in rec
    assert (out.decision, canonical_hash(coord.ctx.sink.get(out.trace_id, "decision", "result"))) == before


# ---- 8. risk acceptance (RISK_ACCEPTANCE) feeds record() ------------------------------------------------------
def test_risk_acceptance_task_feeds_record(store):
    future = datetime.now(timezone.utc) + timedelta(days=30)
    ra.request_acceptance(store, "R1", "app1", "trace1", "author", "High")
    with pytest.raises(NotAuthorized):
        store.act("risk-acceptance-trace1-R1", "mallory", "developer", "CLAIM", "x")
    decide(store, "risk-acceptance-trace1-R1", "bob", "risk_approver", why="compensating control in place")
    reg = ra.RiskAcceptanceRegister()
    rec = ra.record_from_task(store, "risk-acceptance-trace1-R1", "app1 until fix", future, register=reg)
    assert rec.actor == "bob" and rec.role == "risk_approver" and rec.severity == "High" and reg.history[-1]["event"] == "ACCEPTED"

    ra.request_acceptance(store, "R2", "app1", "trace1", "author", "Critical")        # above this role's ceiling
    decide(store, "risk-acceptance-trace1-R2", "bob", "risk_approver")
    with pytest.raises(ra.RiskAcceptanceError):
        ra.record_from_task(store, "risk-acceptance-trace1-R2", "s", future, register=reg)

    ra.request_acceptance(store, "R3", "app1", "trace1", "author", "Low")             # rejected task: nothing recorded
    decide(store, "risk-acceptance-trace1-R3", "bob", "risk_approver", "REJECT", "no")
    with pytest.raises(ra.RiskAcceptanceError):
        ra.record_from_task(store, "risk-acceptance-trace1-R3", "s", future, register=reg)
    assert len(reg.records) == 1
