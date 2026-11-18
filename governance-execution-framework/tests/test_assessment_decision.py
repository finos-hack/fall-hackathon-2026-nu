import pytest

from agip_shared.contracts import SpectralResult, SpectralRun
from governance_execution.core import catalogs, decision, facts as fx, gap, gates
from governance_execution.units import control_assessment as ca, risk_assessment as ra

CTL, RSK = catalogs.load("controls"), catalogs.load("risks")
GAP, SCORE, GATES, MATRIX = gap.load_gap_rule(), ra.load_scoring(), gates.load_gates(), decision.load_matrix()
APP = {"nodes": [
    {"unique-id": "pay", "node-type": "ai:agent", "metadata": {"autonomy": "supervised", "privilege": "restricted-write",
                                                              "can_execute_payment": True, "payment_approval_path": "via-human-approval",
                                                              "credential_storage": "vault", "decision_impact": "financial"}},
    {"unique-id": "tool", "node-type": "ai:tool", "metadata": {}},
    {"unique-id": "db", "node-type": "database", "metadata": {"data_classification": "confidential"}},
    {"unique-id": "gw", "node-type": "service", "metadata": {"exposure": "external", "mediation": "gateway"}},
]}


def run(*codes, status="OK"):
    return SpectralRun(status=status, results=[SpectralResult(code=c, path=["nodes", "0", "metadata"]) for c in codes],
                       error=None if status == "OK" else "boom")


def test_control_statuses_and_gap():
    g = ca.assess(run("ctl-audit-service-present"), CTL, APP, GAP)
    by = {c.control_id: c for c in g.controls}
    assert by["AIGF-MI-021"].status == "FAIL" and by["AIGF-MI-021"].remediation and by["AIGF-MI-021"].findings[0]["path"] == "$.nodes[0].metadata"
    assert by["AIGF-MI-024"].status == "PASS" and by["AIGF-MI-024"].evidence == "design-level evidence only"
    assert g.gap_level == "minor"
    assert ca.assess(run(status="ERROR"), CTL, APP, GAP).gap_level == "INDETERMINATE_INPUT"
    assert all(c.status != "PASS" for c in ca.assess(run(status="ERROR"), CTL, APP, GAP).controls)
    no_agents = ca.assess(run(), CTL, {"nodes": []}, GAP)
    assert {c.status for c in no_agents.controls} == {"NOT_APPLICABLE"}


def test_risk_severity_is_matrix_lookup_and_worst_level():
    p = ra.assess(run("risk-agent-autonomous-execution", "risk-model-version-floating"), RSK, fx.extract(APP, fx.load_taxonomy()), APP, SCORE)
    sev = {r.risk_id: r.severity for r in p.risks}
    assert sev == {"AIGF-RI-018": SCORE["severity_matrix"][4][3], "AIGF-RI-005": SCORE["severity_matrix"][2][2]}
    assert p.profile_level == "High" and p.tier and p.mandatory_trigger is None
    assert "illustrative" in p.label


def test_unevaluable_mandatory_trigger_is_indeterminate():
    app = {"nodes": [dict(APP["nodes"][0], metadata={**APP["nodes"][0]["metadata"], "autonomy": "auto-pilot"})]}
    p = ra.assess(run(), RSK, fx.extract(app, fx.load_taxonomy()), app, SCORE)
    assert p.mandatory_trigger == "UNEVALUABLE" and "auto-pilot" not in p.unevaluable[0] and "UNMAPPED" in p.unevaluable[0]
    d = decision.decide("VALID", ca.assess(run(), CTL, app, GAP), p, GATES, MATRIX)
    assert d.decision == "INDETERMINATE" and d.gates_evaluated[1]["fired"]


def test_gate_precedence_and_matrix():
    g_fail = ca.assess(run("ctl-payment-requires-human-approval"), CTL, APP, GAP)
    p = ra.assess(run(), RSK, fx.extract(APP, fx.load_taxonomy()), APP, SCORE)
    with pytest.raises(ValueError, match="BLOCKED"):    # invalid CALM has no decision
        decision.decide("INVALID", g_fail, p, GATES, MATRIX)
    d = decision.decide("VALID", g_fail, p, GATES, MATRIX)
    assert d.decision == "REJECTED" and [x["id"] for x in d.gates_evaluated if x["fired"]] == ["G2-PAYMENT-AUTH"]
    clean = decision.decide("VALID", ca.assess(run(), CTL, APP, GAP), p, GATES, MATRIX)
    assert clean.decision == "APPROVED_WITH_CONDITIONS" and clean.conditions == [MATRIX["design_only_cap"]["condition"]]
    assert clean.matrix_cell["result"] == "APPROVED" and clean == decision.decide("VALID", ca.assess(run(), CTL, APP, GAP), p, GATES, MATRIX)
