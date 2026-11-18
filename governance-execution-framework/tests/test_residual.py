"""Task 23.5: residual severity equals inherent unless IMPLEMENTATION/OPERATING PASS evidence exists for a linked control."""
import copy

from agip_shared.contracts import Evidence, SpectralResult, SpectralRun
from governance_execution.core import catalogs, evidence as ev, facts as fx
from governance_execution.units import risk_assessment as ra

CTL, RSK = catalogs.load("controls"), catalogs.load("risks")
SCORE = ra.load_scoring()
APP = {"nodes": [{"unique-id": "pay", "node-type": "ai:agent", "metadata": {"autonomy": "autonomous"}}]}
RUN = SpectralRun(status="OK", results=[SpectralResult(code="risk-agent-autonomous-execution", path=["nodes", "0", "metadata"])])
LINKED = "AIGF-MI-024"


def _cat():
    c = copy.deepcopy(RSK)
    for i in c["items"]:
        if i["risk_id"] == "AIGF-RI-018":
            i["linked_controls"] = [LINKED]
    return c


def _assess(evidence, reqs):
    return ra.assess(RUN, _cat(), fx.extract(APP, fx.load_taxonomy()), APP, SCORE, evidence, reqs)


def _risk(p):
    return next(r for r in p.risks if r.risk_id == "AIGF-RI-018")


def _evi(reqs, maturity, status):
    r = next(r for r in reqs if r.control_id == LINKED)
    return [Evidence(evidence_id="e", requirement_id=r.requirement_id, evidence_type="t", source="s", app_id="a", sha256="0" * 64,
                     maturity=maturity, evaluation_status=status)]


def test_residual_equals_inherent_without_or_with_design_only_evidence():
    reqs = ev.build_requirements(CTL)
    base = ra.assess(RUN, RSK, fx.extract(APP, fx.load_taxonomy()), APP, SCORE)
    r0 = _risk(base)
    assert r0.inherent_severity == r0.severity == r0.residual_severity
    for evidence in (None, [], _evi(reqs, "DESIGN", "PASS"), _evi(reqs, "IMPLEMENTATION", "NOT_VERIFIED"),
                     _evi(reqs, "OPERATING", "FAIL")):
        r = _risk(_assess(evidence, reqs))
        assert r.residual_severity == r.inherent_severity == r0.severity


def test_residual_drops_one_level_only_with_implementation_pass():
    reqs = ev.build_requirements(CTL)
    r = _risk(_assess(_evi(reqs, "IMPLEMENTATION", "PASS"), reqs))
    assert r.severity == r.inherent_severity and r.residual_severity != r.inherent_severity
    assert ra.LEVELS.index(r.residual_severity) == ra.LEVELS.index(r.inherent_severity) - 1
