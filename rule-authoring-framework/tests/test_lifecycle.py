import copy
import itertools

import pytest
import yaml

from agip_shared.contracts import KNOWLEDGE_TRANSITIONS
from rule_authoring import approval as ap
from rule_authoring import compile as cc

STATES = ["DRAFT", "IN_REVIEW", "APPROVED", "REJECTED", "DEPRECATED"]


def ctl(status="DRAFT", **kw):
    return {"control_id": "C1", "status": status, "version": 1, **kw}


def risk(status="DRAFT", **kw):
    return {"risk_id": "R1", "status": status, "version": 1, "likelihood": 3, "impact": 4, **kw}


def step(e, target):
    ap.transition(e, target, "alice", "reviewer", "because")


@pytest.mark.parametrize("src,dst", list(itertools.product(STATES, STATES)))
def test_every_transition(src, dst):
    e = ctl(src)
    if dst in KNOWLEDGE_TRANSITIONS[src]:
        step(e, dst)
        assert e["status"] == dst and e["history"][-1]["from"] == src and e["history"][-1]["to"] == dst
    else:
        with pytest.raises(ap.ApprovalError):
            step(e, dst)
        assert e["status"] == src and "history" not in e


def test_history_record_fields_and_append_only():
    e = ctl()
    step(e, "IN_REVIEW")
    before = copy.deepcopy(e["history"])
    step(e, "APPROVED")
    h = e["history"][-1]
    assert {"by", "role", "rationale", "at", "version"} <= set(h) and h["by"] == "alice"
    assert ap.history_is_append_only(before, e["history"])
    assert not ap.history_is_append_only(e["history"], before)
    assert e["approved_by"] == "alice"


def test_failed_transition_leaves_history_untouched():
    e = ctl("APPROVED", history=[{"x": 1}])
    with pytest.raises(ap.ApprovalError):
        step(e, "IN_REVIEW")
    assert e["history"] == [{"x": 1}]


@pytest.mark.parametrize("by,role,rat", [("", "r", "x"), ("a", "", "x"), ("a", "r", " ")])
def test_requires_reviewer_role_rationale(by, role, rat):
    with pytest.raises(ap.ApprovalError):
        ap.transition(ctl(), "IN_REVIEW", by, role, rat)


def test_supersession_recorded_on_deprecate():
    e = ctl("APPROVED")
    ap.transition(e, "DEPRECATED", "a", "r", "replaced", superseded_by="C1@2")
    assert e["superseded_by"] == "C1@2" and e["history"][-1]["superseded_by"] == "C1@2"


def test_rejected_can_return_to_draft():
    e = ctl("IN_REVIEW")
    step(e, "REJECTED")
    step(e, "DRAFT")
    assert e["status"] == "DRAFT" and len(e["history"]) == 2


def test_unconfirmed_risk_refused_then_approved_after_confirmation():
    e = risk("IN_REVIEW")
    with pytest.raises(ap.ApprovalError, match="not confirmed"):
        step(e, "APPROVED")
    assert e["status"] == "IN_REVIEW"
    ap.confirm_risk(e, "bob", "risk-owner", "ok")
    step(e, "APPROVED")
    assert e["status"] == "APPROVED" and "severity" not in e


def test_changed_score_invalidates_confirmation():
    e = risk("IN_REVIEW")
    ap.confirm_risk(e, "bob", "risk-owner")
    e["impact"] = 5
    with pytest.raises(ap.ApprovalError, match="impact"):
        step(e, "APPROVED")


def test_confirm_needs_reviewer_and_risk():
    with pytest.raises(ap.ApprovalError):
        ap.confirm_risk(risk(), "", "r")
    with pytest.raises(ap.ApprovalError):
        ap.confirm_risk(ctl(), "a", "r")


def test_legacy_approve_goes_through_review_and_checks_risk():
    class S:
        def __init__(s, i): s.i = i
        def get_catalog_item(s, x, v=None): return s.i
        def upsert_catalog_item(s, i): s.i = i; return i
    out = ap.approve(S(ctl()), "C1", "zed")
    assert [h["to"] for h in out["history"]] == ["IN_REVIEW", "APPROVED"]
    with pytest.raises(ap.ApprovalError):
        ap.approve(S(risk()), "R1", "zed")


RULE = {"R-1": {"description": "d", "message": "m", "severity": "error", "given": "$.x",
                "then": {"field": "f", "function": "truthy"}}}


@pytest.mark.parametrize("status", STATES)
def test_only_approved_compiles(status):
    cat = {"catalog": "controls", "version": 1, "items": [ctl(status, rule_codes=["R-1"], spectral_rules=RULE)]}
    out = cc.compile_catalog(cat, "controls")
    assert (out.rule_codes == ("R-1",)) == (status == "APPROVED")
    assert (out.skipped_unapproved == ("C1",)) == (status != "APPROVED")


def test_cli_lifecycle(tmp_path, capsys):
    f = tmp_path / "risks.catalog.yaml"
    f.write_text(yaml.safe_dump({"items": [risk()]}), encoding="utf-8")
    base = ["--by", "bob", "--role", "owner", "--rationale", "why", "--catalog", str(f)]
    assert ap.main(["submit", "R1", *base]) == 0
    assert ap.main(["approve", "R1", *base]) == 1          # unconfirmed
    assert ap.main(["confirm", "R1", "--by", "bob", "--role", "owner", "--catalog", str(f)]) == 0
    assert ap.main(["approve", "R1", *base]) == 0
    assert ap.main(["deprecate", "R1", *base, "--superseded-by", "R1@2"]) == 0
    assert ap.main(["reject", "R1", *base]) == 1
    d = yaml.safe_load(f.read_text(encoding="utf-8"))["items"][0]
    assert d["status"] == "DEPRECATED" and len(d["history"]) == 3


def test_seed_catalogs_have_history_and_confirmed_risks():
    docs = yaml.safe_load((cc.CATALOG_DIR / "risks.catalog.yaml").read_text(encoding="utf-8"))
    for it in docs["items"]:
        assert it["status"] == "APPROVED" and it["history"][-1]["to"] == "APPROVED"
        assert it["confirmation"]["by"] == "seed-import"
        ap._check_confirmed(it, it["risk_id"])


def test_legacy_approve_confirm_scores_opt_in(tmp_path):
    f = tmp_path / "risks.catalog.yaml"
    f.write_text(yaml.safe_dump({"items": [risk()]}), encoding="utf-8")
    with pytest.raises(ap.ApprovalError, match="not confirmed"):
        ap.approve_in_catalog(f, "R1", "ann")
    e = ap.approve_in_catalog(f, "R1", "ann", confirm_scores=True)
    assert e["status"] == "APPROVED" and e["confirmation"]["by"] == "ann"
    with pytest.raises(ap.ApprovalError):
        ap.approve_in_catalog(f, "R1", "ann", confirm_scores=True)   # already approved
