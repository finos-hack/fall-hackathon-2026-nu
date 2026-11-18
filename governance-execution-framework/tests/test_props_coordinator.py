"""Task 20.2 (C2): Properties 19, 20, 21 and the Coordinator/Strands unit checks (11.2, 11.5, 14.6, 14.7).

CALM and Spectral run from recorded CLI outputs (offline); LLM and Decider use recordings. End-to-end runs cost
about a second each, so the e2e properties sample over V1-V4 x modes with a small max_examples (the input space
is only 4 variants x 3 modes, so a few examples cover it); pure properties use max_examples=100.
"""
import ast
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from hypothesis import HealthCheck, given, settings, strategies as st

from agip_shared.contracts import Decision
from agip_shared.gateway import ModelUnavailableError, RecordingMissingError
from agip_shared.hashing import canonical_json, sha256_hex
from agip_shared.settings import Settings
from governance_execution.exec import factory
from governance_execution.obs.replay import replay
from governance_execution.store.repository import MemoryRepository
from governance_execution.units import decision_remediation, registry
from governance_execution.units.calm_builder import instantiate, load_template

ROOT = Path(__file__).resolve().parents[2]
FORMS = ROOT / "governance-execution-framework" / "forms"
VARIANTS = ROOT / "calm-app-generation-framework" / "fixtures" / "variants"
EXPECTED = yaml.safe_load((VARIANTS / "expected.yaml").read_text(encoding="utf-8"))
SETTINGS = Settings(_env_file=None, decider_provider="fixture", model_provider="replay")
TPL, TEXT = load_template("RA03-LITE")
E2E = settings(max_examples=6, deadline=None, suppress_health_check=list(HealthCheck))


def form(v):
    return yaml.safe_load((FORMS / f"{v}.attributes.yaml").read_text(encoding="utf-8"))


def build(d, mode="normal", repo=None):
    return factory.build(mode, settings=SETTINGS, repo=repo or MemoryRepository(d), data_dir=d, cli="replay")


def assess(coord, ex, v):
    r = instantiate(form(v), template=TPL, template_text=TEXT, template_status="PUBLISHED", calm=coord.ctx.calm)
    assert r.app_model is not None, r.errors
    return coord.run(r.app_model, executor=ex, template_id="RA03-LITE", source={"app_id": form(v)["app"]["id"]})


def art(coord, out, kind, aid="result"):
    return coord.ctx.sink.get(out.trace_id, kind, aid)


@pytest.fixture(scope="module")
def baselines(tmp_path_factory):
    """V1-V4 normal-mode runs, computed once; tests read them and never mutate them."""
    res = {}
    for v in ("v1", "v2", "v3", "v4"):
        d = tmp_path_factory.mktemp(v)
        coord, ex = build(d)
        out = assess(coord, ex, v)
        res[v] = SimpleNamespace(coord=coord, out=out, decision=Decision.model_validate(art(coord, out, "decision")) if out.decision else None,
                                 items=art(coord, out, "remediation")["items"])
    return res


# ---- Property 19 (11.2) -------------------------------------------------------------------------
class Stub:
    """ModelGateway stand-in returning an arbitrary (possibly adversarial) Remediation_Agent output."""
    provider, model = "stub", "stub"

    def __init__(self, output=None, exc=None):
        self.output, self.exc = output, exc

    def complete(self, *a, **k):
        if self.exc:
            raise self.exc
        return SimpleNamespace(output=self.output, model="stub", input_hash="0" * 64)


JSON = st.recursive(st.none() | st.booleans() | st.integers() | st.text(max_size=40),
                    lambda c: st.lists(c, max_size=3) | st.dictionaries(st.text(max_size=10), c, max_size=4), max_leaves=8)
ADVERSARIAL = st.one_of(
    JSON,
    st.fixed_dictionaries({"fix_prompt": st.text(max_size=80), "summary": st.text(max_size=40)},
                          optional={"decision": st.sampled_from(["APPROVED", "REJECTED", "RESTRICTED"]),
                                    "conditions": st.lists(st.text(max_size=20), max_size=3),
                                    "app_model": JSON, "status": st.just("PASS")}))
FAILURES = st.sampled_from([RecordingMissingError("x"), ModelUnavailableError("down")])


# Feature: governance-as-code-mvp, Property 19: Remediation agent cannot change outcome
@settings(max_examples=100, deadline=None, suppress_health_check=list(HealthCheck))
@given(v=st.sampled_from(["v1", "v2", "v3", "v4"]), output=ADVERSARIAL, mode=st.sampled_from(["normal", "no-llm"]),
       fail=st.none() | FAILURES)
def test_p19_remediate_never_changes_decision(baselines, v, output, mode, fail):
    b = baselines[v]
    if b.decision is None:   # blocked run (V4): no decision exists and the remediation agent cannot create one
        rem = decision_remediation.remediate(None, [dict(i) for i in b.items], Stub(output), mode)
        assert rem["decision"] is None and rem["conditions"] == [] and rem["source"] == "deterministic"
        return
    before = b.decision.model_dump_json()
    gw = Stub(exc=fail) if fail else Stub(output)
    rem = decision_remediation.remediate(b.decision, [dict(i) for i in b.items], gw, mode)
    assert rem["decision"] == b.decision.decision and rem["conditions"] == list(b.decision.conditions)
    assert b.decision.model_dump_json() == before
    rem["conditions"].append("tamper")
    assert b.decision.model_dump_json() == before


# Feature: governance-as-code-mvp, Property 19: Remediation agent cannot change outcome (end-to-end)
@E2E
@given(v=st.sampled_from(["v1", "v2", "v3", "v4"]), output=ADVERSARIAL)
def test_p19_e2e_adversarial_agent_keeps_decision_and_calm_hash(baselines, v, output):
    b = baselines[v]
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        coord, ex = build(Path(d))
        coord.ctx.gateway = Stub(output)
        out = assess(coord, ex, v)
        assert out.decision == b.out.decision and out.status == b.out.status
        assert art(coord, out, "decision")["conditions"] == list(b.decision.conditions) if b.decision else out.decision is None
        h = sha256_hex(canonical_json(coord.ctx.sink.get(out.trace_id, "app_model", "app")))
        assert art(coord, out, "versions", "versions")["app_model_sha256"] == h
        assert h == art(b.coord, b.out, "versions", "versions")["app_model_sha256"]


# ---- 11.5 Unit error yields no decision; Strands import isolation -------------------------------
def _boom(task, ctx):
    raise RuntimeError("boom")


@pytest.mark.parametrize("unit,step", [("control_assessment", "spectral_controls"), ("risk_assessment", "extract_facts"),
                                       ("risk_assessment", "spectral_risks"), ("calm_builder", "validate_calm")])
def test_unit_error_yields_no_decision(tmp_path, monkeypatch, unit, step):
    coord, ex = build(tmp_path)
    monkeypatch.setitem(registry.UNITS, unit, _boom)
    out = assess(coord, ex, "v1")
    assert out.status == "FAILED" and out.decision is None and "boom" in (out.error or "")
    assert "decision" not in out.artifacts and "unit_error" in out.artifacts
    kinds = {a.kind for a in coord.ctx.sink.list(out.trace_id)}
    assert "decision" not in kinds and "remediation" not in kinds
    assert coord.ctx.sink.repo.get_assessment(out.trace_id)["decision"] is None


def test_invoke_turns_exception_into_error_result(tmp_path, monkeypatch):
    from agip_shared.contracts import AgentTask
    coord, _ = build(tmp_path)
    monkeypatch.setitem(registry.UNITS, "decision_remediation", _boom)
    res = registry.invoke(AgentTask(task_id="t", unit="decision_remediation", trace_id="a" * 32, artifact_ids=[], params={}),
                          coord.ctx)
    assert res.status == "ERROR" and res.artifact_ids == []


def test_strands_imported_only_in_runtime_strands():
    allowed = (ROOT / "shared" / "src" / "agip_shared" / "gateway" / "runtime_strands.py").resolve()
    skip = {".venv", "node_modules", ".tools", "__pycache__", ".git", ".hypothesis", ".pytest_cache", "site-packages"}
    offenders, scanned = [], 0
    for p in ROOT.rglob("*.py"):
        if skip & set(p.relative_to(ROOT).parts):
            continue
        scanned += 1
        if "spike" in p.parts:  # throwaway Bedrock spike script (scripts/spike), not product code
            continue
        if p.resolve() == allowed or p.resolve() == Path(__file__).resolve():
            continue
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            mods = [a.name for a in n.names] if isinstance(n, ast.Import) else \
                [n.module or ""] if isinstance(n, ast.ImportFrom) and not n.level else []
            if any(m == "strands" or m.startswith("strands.") for m in mods):
                offenders.append(str(p.relative_to(ROOT)))
    assert scanned > 20 and allowed.is_file()
    assert not offenders, offenders


# ---- Property 20 (14.6) -------------------------------------------------------------------------
# Feature: governance-as-code-mvp, Property 20: No-LLM mode completes
@E2E
@given(v=st.sampled_from(["v1", "v2", "v3"]))
def test_p20_no_llm_completes_with_deterministic_list(baselines, v):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        coord, ex = build(Path(d), "no-llm")
        assert coord.ctx.gateway is None
        out = assess(coord, ex, v)
        assert out.status == "COMPLETED" and out.decision == EXPECTED[v]["decision"] == baselines[v].out.decision
        rem = art(coord, out, "remediation")
        texts = [c["remediation"] for c in art(coord, out, "control_gap")["controls"] if c["status"] == "FAIL" and c["remediation"]]
        texts += [r["remediation"] for r in art(coord, out, "risk_profile")["risks"] if r["remediation"]]
        assert [i["text"] for i in rem["items"]] == texts
        assert [s.split(". ", 1)[1].rsplit(" [", 1)[0] for s in rem["deterministic_list"]] == texts
        assert rem["source"] == "deterministic" and rem["fix_prompt"] is None


# ---- Property 21 (14.7) -------------------------------------------------------------------------
# Feature: governance-as-code-mvp, Property 21: Replay is identical
@E2E
@given(v=st.sampled_from(["v1", "v2", "v3", "v4"]))
def test_p21_replay_is_identical_with_zero_model_calls(v):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        d = Path(d)
        repo = MemoryRepository(d)
        coord, ex = build(d, repo=repo)
        out = assess(coord, ex, v)
        rcoord, rex = build(d, "replay", repo=repo)
        assert rcoord.ctx.gateway.provider == "replay" and rcoord.ctx.decider.provider == "fixture"
        rep = replay(out.trace_id, rcoord, rex)
        assert rep.replay_trace != out.trace_id and rep.identical and not rep.differences
        assert rep.decision_replay == rep.decision_original == EXPECTED[v]["decision"]


# Feature: governance-as-code-mvp, Property 21: Replay is identical (missing recording fails naming the record)
@E2E
@given(v=st.sampled_from(["v2", "v3"]))  # V1 needs no recorded LLM output
def test_p21_missing_recording_fails_replay_naming_record(v):
    from governance_execution.obs.replay import ReplayFailed
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        d = Path(d)
        repo = MemoryRepository(d)
        coord, ex = build(d, repo=repo)
        out = assess(coord, ex, v)
        rcoord, rex = build(d, "replay", repo=repo)
        rcoord.ctx.gateway.recorder.root = d / "empty"
        with pytest.raises(ReplayFailed, match=r"missing recording: remediation/v1/[0-9a-f]{64}"):
            replay(out.trace_id, rcoord, rex)
