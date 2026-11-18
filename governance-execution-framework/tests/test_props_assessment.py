"""Property tests 10.3, 10.5, 10.7, 10.8, 10.9 (assessment and decision)."""
import itertools

import pytest
from hypothesis import given, settings, strategies as st

from agip_shared.contracts import ControlGapAssessment, ControlResult, RiskProfile, SpectralResult, SpectralRun
from governance_execution.core import catalogs, decision, facts as fx, gap, gates
from governance_execution.units import control_assessment as ca, risk_assessment as ra

CTL, RSK = catalogs.load("controls"), catalogs.load("risks")
GAP, SCORE, GATES, MATRIX = gap.load_gap_rule(), ra.load_scoring(), gates.load_gates(), decision.load_matrix()
TAX = fx.load_taxonomy()
APP = {"nodes": [
    {"unique-id": "pay", "node-type": "ai:agent", "metadata": {"autonomy": "supervised", "privilege": "restricted-write",
                                                              "can_execute_payment": True, "payment_approval_path": "via-human-approval",
                                                              "credential_storage": "vault", "decision_impact": "financial"}},
    {"unique-id": "tool", "node-type": "ai:tool", "metadata": {}},
    {"unique-id": "db", "node-type": "database", "metadata": {"data_classification": "confidential"}},
    {"unique-id": "gw", "node-type": "service", "metadata": {"exposure": "external", "mediation": "gateway"}},
]}
CTL_CODES = sorted({c for i in catalogs.approved(CTL) for cfg in i.get("configurations") or [] for c in cfg.get("rule_codes") or []})
RISK_CODES = sorted({c for i in catalogs.approved(RSK) for c in i.get("rule_codes") or []})
RISK_NAMES = ["Low", "Medium", "High", "Critical"]


def run(codes=(), status="OK"):
    return SpectralRun(status=status, results=[SpectralResult(code=c, path=["nodes", "0", "metadata"]) for c in codes],
                       error=None if status == "OK" else "boom")


# Feature: governance-as-code-mvp, Property 14: Spectral pass is design-level only
@settings(max_examples=100)
@given(codes=st.sets(st.sampled_from(CTL_CODES)))
def test_property_14_pass_is_design_level(codes):
    g = ca.assess(run(sorted(codes)), CTL, APP, GAP)
    for c in g.controls:
        if c.status == "NOT_APPLICABLE":
            continue
        hit = bool(set(c.rule_codes) & codes)
        assert (c.status == "FAIL") == hit and (c.status == "PASS") == (not hit)
        if c.status == "PASS":
            assert c.evidence == ca.DESIGN_ONLY and not c.findings


@settings(max_examples=100)
@given(codes=st.sets(st.sampled_from(CTL_CODES)), app=st.sampled_from([APP, {"nodes": []}]))
def test_property_14_error_run_is_never_pass(codes, app):
    g = ca.assess(run(sorted(codes), status="ERROR"), CTL, app, GAP)
    assert all(c.status in ("ERROR", "NOT_APPLICABLE") and c.status != "PASS" for c in g.controls)
    assert g.gap_level == "INDETERMINATE_INPUT" or all(c.status == "NOT_APPLICABLE" for c in g.controls)


# Feature: governance-as-code-mvp, Property 15: Severity is a matrix lookup
@settings(max_examples=100)
@given(codes=st.sets(st.sampled_from(RISK_CODES)), autonomy=st.sampled_from(["supervised", "semi-autonomous", "autonomous"]),
       privilege=st.sampled_from(["read-only", "restricted-write", "unrestricted-write"]))
def test_property_15_severity_is_matrix_lookup(codes, autonomy, privilege):
    app = {"nodes": [dict(APP["nodes"][0], metadata={**APP["nodes"][0]["metadata"], "autonomy": autonomy, "privilege": privilege}),
                     *APP["nodes"][1:]]}
    p = ra.assess(run(sorted(codes)), RSK, fx.extract(app, TAX), app, SCORE)
    base = ra.assess(run(sorted(codes)), RSK, fx.extract(APP, TAX), APP, SCORE)
    expected_ids = {i["risk_id"] for i in catalogs.approved(RSK) if set(i.get("rule_codes") or []) & codes}
    assert {r.risk_id for r in p.risks} == expected_ids
    for r in p.risks:
        assert r.severity == SCORE["severity_matrix"][r.likelihood][r.impact - 1]
    assert {r.risk_id: r.severity for r in p.risks} == {r.risk_id: r.severity for r in base.risks}  # tier-independent
    want = max((r.severity for r in p.risks), key=RISK_NAMES.index) if p.risks else "Low"
    assert p.profile_level == want


@settings(max_examples=100)
@given(l=st.integers(1, 5), i=st.integers(1, 5))
def test_property_15_matrix_lookup_function(l, i):
    assert ra.matrix_lookup(SCORE, l, i) == SCORE["severity_matrix"][l][i - 1]


# Feature: governance-as-code-mvp, Property 16: Gate precedence and decision determinism
GAPS, RISKS = MATRIX["rows"]["gap"], MATRIX["rows"]["risk"]


def _gap(level, mi024):
    return ControlGapAssessment(controls=[ControlResult(control_id="AIGF-MI-024", status=mi024)], gap_level=level)


def _expected(calm, mi024, trig, level, risk):
    if mi024 == "FAIL":
        return "REJECTED"
    if trig == "UNEVALUABLE":
        return "INDETERMINATE"
    res = MATRIX["cells"][level][RISKS.index(risk)]
    return MATRIX["design_only_cap"]["to"] if res == MATRIX["design_only_cap"]["from"] else res


inputs = st.tuples(st.just("VALID"), st.sampled_from(["PASS", "FAIL", "NOT_APPLICABLE"]),
                   st.sampled_from([None, "UNEVALUABLE"]), st.sampled_from(GAPS), st.sampled_from(RISKS))


@pytest.mark.parametrize("calm", ["INVALID", "ERROR"])
def test_invalid_calm_has_no_decision(calm):
    with pytest.raises(ValueError):
        decision.decide(calm, _gap("none", "PASS"), RiskProfile(profile_level="Low"), GATES, MATRIX)


@settings(max_examples=100)
@given(x=inputs)
def test_property_16_gate_precedence_and_determinism(x):
    calm, mi024, trig, level, risk = x
    g, p = _gap(level, mi024), RiskProfile(profile_level=risk, mandatory_trigger=trig)
    d = decision.decide(calm, g, p, GATES, MATRIX)
    assert d.decision == _expected(*x)
    assert d == decision.decide(calm, g, p, GATES, MATRIX)
    assert [r["id"] for r in d.gates_evaluated] == [g_["id"] for g_ in GATES["order"]]
    fired = [r["id"] for r in d.gates_evaluated if r["fired"]]
    if fired:
        assert d.matrix_cell["evaluated"] is False
        assert [r["id"] for r in d.gates_evaluated if r["fired"] and not r["overridden"]] == fired[:1]
    else:
        assert d.matrix_cell["evaluated"] is True and d.matrix_cell["result"] == MATRIX["cells"][level][RISKS.index(risk)]


# Feature: governance-as-code-mvp, Property 17: Clean design result is conditional
APPROVED_CELLS = [(g_, r) for g_, r in itertools.product(GAPS, RISKS) if MATRIX["cells"][g_][RISKS.index(r)] == "APPROVED"]


@settings(max_examples=100)
@given(cell=st.sampled_from(APPROVED_CELLS))
def test_property_17_clean_result_is_conditional(cell):
    level, risk = cell
    d = decision.decide("VALID", _gap(level, "PASS"), RiskProfile(profile_level=risk), GATES, MATRIX)
    assert d.decision == "APPROVED_WITH_CONDITIONS" and d.conditions == [MATRIX["design_only_cap"]["condition"]]
    assert d.matrix_cell["result"] == "APPROVED"


# Feature: governance-as-code-mvp, Property 18: INDETERMINATE on unevaluable mandatory trigger
KNOWN = {str(k).lower() for k in TAX["attributes"]["autonomy"]["values"]}


@settings(max_examples=100)
@given(bad=st.one_of(st.none(), st.text(max_size=20).filter(lambda s: s.strip().lower() not in KNOWN)),
       codes=st.sets(st.sampled_from(RISK_CODES)))
def test_property_18_indeterminate_on_unevaluable(bad, codes):
    meta = {k: v for k, v in APP["nodes"][0]["metadata"].items() if k != "autonomy"}
    if bad is not None:
        meta["autonomy"] = bad  # UNMAPPED; absent means UNKNOWN
    app = {"nodes": [dict(APP["nodes"][0], metadata=meta)]}
    r = run([])  # no findings, so no control FAIL (no G2) and calm is VALID (no G1)
    p = ra.assess(run(sorted(codes)), RSK, fx.extract(app, TAX), app, SCORE)
    assert p.mandatory_trigger == "UNEVALUABLE"
    d = decision.decide("VALID", ca.assess(r, CTL, app, GAP), p, GATES, MATRIX)
    assert d.decision == "INDETERMINATE"
