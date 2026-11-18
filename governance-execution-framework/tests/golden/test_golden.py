"""Golden E2E, no-LLM, replay and most-favourable-Decider tests for V1-V4 (Req 24, 26).

CALM and Spectral run from recorded outputs (fixtures/recordings/cli). Set AGIP_REAL_TOOLS=1 to run the
real `calm` and `spectral` CLIs when they are installed. LLM and Decider always use recordings.
"""
import json
import os
from pathlib import Path

import pytest
import yaml

from agip_shared.settings import Settings
from governance_execution.exec import factory
from governance_execution.obs.replay import replay
from governance_execution.store.repository import MemoryRepository
from governance_execution.units.calm_builder import instantiate, load_template

ROOT = Path(__file__).resolve().parents[3]
FORMS = ROOT / "governance-execution-framework" / "forms"
VARIANTS = ROOT / "calm-app-generation-framework" / "fixtures" / "variants"
EXPECTED = yaml.safe_load((VARIANTS / "expected.yaml").read_text(encoding="utf-8"))
SETTINGS = Settings(_env_file=None, decider_provider="fixture", model_provider="replay")
CLI = "real" if os.environ.get("AGIP_REAL_TOOLS") == "1" and factory.tools_available(SETTINGS) else "replay"
TPL, TEXT = load_template("RA03-LITE")


def form(v):
    return yaml.safe_load((FORMS / f"{v}.attributes.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def env(tmp_path):
    repo = MemoryRepository(tmp_path)

    def build(mode="normal", **kw):
        return factory.build(mode, settings=SETTINGS, repo=repo, data_dir=tmp_path, cli=CLI, **kw)
    return build


def assess(coord, ex, v):
    r = instantiate(form(v), template=TPL, template_text=TEXT, template_status="PUBLISHED", calm=coord.ctx.calm)
    assert r.app_model is not None, r.errors
    out = coord.run(r.app_model, executor=ex, template_id="RA03-LITE", source={"app_id": form(v)["app"]["id"]})
    return r, out


def art(coord, out, kind, aid="result"):
    return coord.ctx.sink.get(out.trace_id, kind, aid)


@pytest.mark.parametrize("v", ["v1", "v2", "v3", "v4"])
def test_golden_variant(env, v):
    coord, ex = env()
    exp = EXPECTED[v]
    inst, out = assess(coord, ex, v)
    assert inst.status == exp["calm"]
    assert out.decision == exp["decision"] and out.executor == "Direct_Adapter"
    assert out.status == exp["status"] and out.validation_status == exp["calm"]
    rec = coord.ctx.sink.repo.get_assessment(out.trace_id)
    assert rec["assessment_status"] == exp["status"] and rec["validation_status"] == exp["calm"]
    stored = VARIANTS / f"{form(v)['app']['id']}.json"
    assert json.loads(stored.read_text(encoding="utf-8")) == inst.app_model
    if v == "v4":
        assert "decision" not in out.artifacts       # invalid CALM: BLOCKED, no decision
        assert exp["calm_error_path"] in json.dumps(art(coord, out, "calm_validation"))
        assert "spectral_controls_parsed" not in out.artifacts
        assert "payment_limit" in art(coord, out, "remediation")["deterministic_list"][0]
        return
    d = art(coord, out, "decision")
    fired = [g["id"] for g in d["gates_evaluated"] if g["fired"]]
    if "gate" in exp:
        assert fired[0] == exp["gate"]
    gap, prof = art(coord, out, "control_gap"), art(coord, out, "risk_profile")
    assert sorted(c["control_id"] for c in gap["controls"] if c["status"] == "FAIL") == exp["failed_controls"]
    assert sorted(r["risk_id"] for r in prof["risks"]) == exp["triggered_risks"]
    if "gap_level" in exp:
        assert gap["gap_level"] == exp["gap_level"] and prof["profile_level"] == exp["profile_level"]
    assert all(c["evidence"] == "design-level evidence only" for c in gap["controls"] if c["status"] == "PASS")
    assert prof["label"] == "illustrative, not approved policy"
    facts = art(coord, out, "facts")["facts"]
    inferred = sorted(f"{f['element_id']}.{f['attribute']}" for f in facts if f["mapping_status"] == "INFERRED")
    assert inferred == ["invoice-db.data_classification"]  # Option B: recorded Decider answer accepted by policy
    vers = art(coord, out, "versions", "versions")
    assert vers["rulesets"]["controls"]["sha256"] and vers["executor"] == "Direct_Adapter"


@pytest.mark.parametrize("v", ["v1", "v2", "v3"])
def test_no_llm_completes_with_deterministic_list(env, v):
    coord, ex = env("no-llm")
    _, out = assess(coord, ex, v)
    assert out.status == "COMPLETED" and out.decision == EXPECTED[v]["decision"]
    rem = art(coord, out, "remediation")
    assert rem["source"] == "deterministic" and rem["fix_prompt"] is None
    assert len(rem["deterministic_list"]) == len(rem["items"])


@pytest.mark.parametrize("v", ["v1", "v2", "v3", "v4"])
def test_replay_is_identical(env, v):
    coord, ex = env()
    _, out = assess(coord, ex, v)
    rcoord, rex = env("replay")
    report = replay(out.trace_id, rcoord, rex)
    assert report.replay_trace != out.trace_id
    assert report.identical, report.differences
    assert report.decision_replay == EXPECTED[v]["decision"]


def test_replay_names_missing_record(env, tmp_path, monkeypatch):
    coord, ex = env()
    _, out = assess(coord, ex, "v2")
    rcoord, rex = env("replay")
    rcoord.ctx.gateway.recorder.root = tmp_path / "empty"
    from governance_execution.obs.replay import ReplayFailed
    with pytest.raises(ReplayFailed, match=r"missing recording: remediation/v1/[0-9a-f]{64}"):
        replay(out.trace_id, rcoord, rex)


class Favourable:
    """Decider stub that answers every question with the most favourable label at full confidence."""

    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, k):
        return getattr(self.inner, k)

    def _call(self, h, state, q):
        best = sorted(q.get("choices") or ["public"])[0] if "public" not in (q.get("choices") or []) else "public"
        return {"model": "favourable", "answers": [{"choice": best, "confidence": 1.0, "probabilities": {best: 1.0}}]}


@pytest.mark.parametrize("v", ["v1", "v2", "v3"])
def test_most_favourable_decider_changes_nothing(env, v):
    # Option B: the favourable answer is now ACCEPTED (fact INFERRED) but still cannot move risks, controls or the decision.
    coord, ex = env()
    _, base = assess(coord, ex, v)
    fcoord, fex = env()
    fcoord.ctx.decider._call = Favourable(fcoord.ctx.decider)._call
    _, fav = assess(fcoord, fex, v)
    labels = [f["decider_label"] for f in art(fcoord, fav, "facts")["facts"] if f["decider_label"]]
    assert labels == ["public"]
    assert fav.decision == base.decision
    assert art(fcoord, fav, "risk_profile")["risks"] == art(coord, base, "risk_profile")["risks"]
    assert art(fcoord, fav, "control_gap")["controls"] == art(coord, base, "control_gap")["controls"]
