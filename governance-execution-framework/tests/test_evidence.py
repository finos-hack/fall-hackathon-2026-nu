"""Task 23.6: AssessmentRequirements per control configuration; Spectral PASS is DESIGN-level only."""
from agip_shared.contracts import SpectralResult, SpectralRun
from governance_execution.core import catalogs, evidence as ev

CTL = catalogs.load("controls")


def test_one_requirement_per_configuration():
    reqs = ev.build_requirements(CTL)
    n = sum(len(i.get("configurations") or []) for i in catalogs.approved(CTL))
    assert len(reqs) == n and len({r.requirement_id for r in reqs}) == n
    assert all(r.required_maturity == "DESIGN" and r.control_id for r in reqs)


def test_spectral_pass_is_design_and_higher_maturity_not_verified():
    reqs = ev.build_requirements(CTL, extra_maturities=("IMPLEMENTATION", "OPERATING"))
    code = next(c for r in reqs for c in r.source["rule_codes"])
    run = SpectralRun(status="OK", results=[SpectralResult(code=code, path=["nodes", "0"])])
    out = {e.requirement_id: e for e in ev.build_evidence(reqs, run, "app1", "1")}
    assert len(out) == len(reqs)
    for r in reqs:
        e = out[r.requirement_id]
        assert e.maturity == r.required_maturity
        if r.required_maturity != "DESIGN":
            assert e.evaluation_status == "NOT_VERIFIED"
        elif code in r.source["rule_codes"]:
            assert e.evaluation_status == "FAIL"
        else:
            assert e.evaluation_status == "PASS"
    assert any(e.evaluation_status == "PASS" and e.maturity == "DESIGN" for e in out.values())


def test_error_run_never_pass():
    reqs = ev.build_requirements(CTL)
    out = ev.build_evidence(reqs, SpectralRun(status="ERROR", error="boom"), "app1")
    assert all(e.evaluation_status == "ERROR" for e in out)
