"""Task 20.4: immutable assessment artifacts and replay from the versions frozen at assessment time.

A catalog, the scoring profile and the rulesets are changed after an assessment (temp copies only, repo files
are never written). The stored assessment stays byte-identical and its replay gives the same decision and stage
artifacts, because replay reads the stored ``config_snapshot`` instead of the live files.
"""
import copy
import shutil
from pathlib import Path

import pytest
import yaml
from rule_authoring import compile as cp

from agip_shared.hashing import sha256_hex
from agip_shared.settings import Settings
from governance_execution.core import spectral_runs
from governance_execution.exec import factory
from governance_execution.obs.replay import fingerprint, replay
from governance_execution.store.repository import MemoryRepository
from governance_execution.units.calm_builder import instantiate, load_template
from governance_execution.units.registry import UnitContext

ROOT = Path(__file__).resolve().parents[2]
FORMS = ROOT / "governance-execution-framework" / "forms"
EXPECTED = yaml.safe_load((ROOT / "calm-app-generation-framework" / "fixtures" / "variants" / "expected.yaml")
                          .read_text(encoding="utf-8"))
SETTINGS = Settings(_env_file=None, decider_provider="fixture", model_provider="replay")
TPL, TEXT = load_template("RA03-LITE")
REQUIRED = ("trace_id", "input_artifacts", "framework_versions", "catalogs", "rulesets", "config_sha256", "taxonomy",
            "scoring_profile", "decision", "decider_policy", "decider", "evaluators", "calm_cli", "spectral_cli", "mode",
            "stage_outputs")


def form(v):
    return yaml.safe_load((FORMS / f"{v}.attributes.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def env(tmp_path):
    repo = MemoryRepository(tmp_path)

    def build(mode="normal"):
        return factory.build(mode, settings=SETTINGS, repo=repo, data_dir=tmp_path, cli="replay")
    return build


def assess(coord, ex, v):
    r = instantiate(form(v), template=TPL, template_text=TEXT, template_status="PUBLISHED", calm=coord.ctx.calm)
    return coord.run(r.app_model, executor=ex, template_id="RA03-LITE", source={"app_id": form(v)["app"]["id"]})


def stored_bytes(coord, trace):
    files = coord.ctx.sink.files
    return {f"{a.kind}/{a.id}": files.get_bytes(trace, a.kind, a.id) for a in coord.ctx.sink.list(trace)}


@pytest.mark.parametrize("v", ["v1", "v2"])
def test_assessment_record_has_every_version_field(env, v):
    coord, ex = env()
    out = assess(coord, ex, v)
    rec = coord.ctx.sink.repo.get_assessment(out.trace_id)
    vers = rec["versions"]
    assert vers == coord.ctx.sink.get(out.trace_id, "versions", "versions")
    missing = [k for k in REQUIRED if k not in vers]
    assert not missing, missing
    assert vers["trace_id"] == rec["trace_id"] == out.trace_id
    assert vers["input_artifacts"]["app_model"]["sha256"] == coord.ctx.sink.repo.get_artifact(out.trace_id, "app_model", "app").sha256
    assert vers["decision"] == out.decision == EXPECTED[v]["decision"] and vers["mode"] == "normal"
    for lane in ("controls", "risks"):
        assert vers["rulesets"][lane]["version"] and len(vers["rulesets"][lane]["sha256"]) == 64
        assert vers["catalogs"][lane] is not None
    assert {"controls", "risks", "taxonomy", "scoring", "decider_policy"} <= set(vers["config_sha256"])
    assert vers["evaluators"] == {"calm": vers["calm_cli"], "spectral": vers["spectral_cli"]}
    assert "governance-execution-framework" in vers["framework_versions"]
    for stage in ("calm_validation/result", "facts/result", "control_gap/result", "risk_profile/result",
                  "decision/result", "remediation/result", "config_snapshot/snapshot"):
        assert len(vers["stage_outputs"][stage]) == 64, stage
    for a in coord.ctx.sink.list(out.trace_id):
        if a.kind not in ("versions", "trace"):
            assert vers["stage_outputs"][f"{a.kind}/{a.id}"] == a.sha256


def _mutated_live_config(tmp_path, monkeypatch):
    """Change the live risks catalog, controls catalog, scoring profile and both rulesets (temp copies only)."""
    base = UnitContext.default_config()
    live = copy.deepcopy(base)
    live["risks"]["version"] = int(live["risks"].get("version", 1)) + 1
    for key in ("controls", "risks"):
        for k, val in live[key].items():
            if isinstance(val, list):
                live[key][k] = []           # drop every rule: a live run would find nothing
    live["scoring"]["version"] = f"{live['scoring'].get('version')}-changed"
    monkeypatch.setattr(UnitContext, "default_config", classmethod(lambda cls: copy.deepcopy(live)))
    rdir = tmp_path / "live-rulesets"
    shutil.copytree(cp.RULESET_DIR, rdir)
    for lane in ("controls", "risks"):
        p = rdir / f"{lane}.spectral.yaml"
        p.write_bytes(p.read_bytes() + b"\n# changed after the assessment\n")
    monkeypatch.setattr(cp, "RULESET_DIR", rdir)
    monkeypatch.setattr(spectral_runs, "RULESET_DIR", rdir)
    return base, live


@pytest.mark.parametrize("v", ["v1", "v2"])
def test_catalog_change_after_assessment_leaves_stored_run_and_replay_unchanged(env, tmp_path, monkeypatch, v):
    repo_files = {p: sha256_hex(p.read_bytes()) for p in (cp.RULESET_DIR / "controls.spectral.yaml",
                                                           cp.RULESET_DIR / "risks.spectral.yaml")}
    coord, ex = env()
    out = assess(coord, ex, v)
    before = stored_bytes(coord, out.trace_id)
    record_before = copy.deepcopy(coord.ctx.sink.repo.get_assessment(out.trace_id))

    _, live = _mutated_live_config(tmp_path, monkeypatch)

    # The live change is real: a fresh assessment against the live files differs from the stored one.
    lcoord, lex = env()
    assert lcoord.ctx.config["risks"]["version"] == live["risks"]["version"]
    lout = assess(lcoord, lex, v)
    assert fingerprint(lcoord.ctx.sink, lout.trace_id) != fingerprint(coord.ctx.sink, out.trace_id)

    rcoord, rex = env("replay")
    report = replay(out.trace_id, rcoord, rex)
    assert report.identical, report.differences
    assert report.decision_replay == report.decision_original == EXPECTED[v]["decision"]
    rvers = rcoord.ctx.sink.get(report.replay_trace, "versions", "versions")
    overs = record_before["versions"]
    assert rvers["rulesets"] == overs["rulesets"] and rvers["config_sha256"] == overs["config_sha256"]
    assert rvers["catalogs"] == overs["catalogs"] and rvers["scoring_profile"] == overs["scoring_profile"]
    assert rvers["stage_outputs"]["config_snapshot/snapshot"] == overs["stage_outputs"]["config_snapshot/snapshot"]
    ofp, rfp = fingerprint(coord.ctx.sink, out.trace_id), fingerprint(rcoord.ctx.sink, report.replay_trace)
    assert ofp == rfp   # every stage artifact identical once the Trace_ID / timing fields are removed
    for k in ("calm_validation", "facts", "control_gap", "risk_profile", "decision", "remediation"):
        assert ofp[f"{k}/result"] == rfp[f"{k}/result"], k

    # Stored assessment untouched, byte for byte; replay restored the live context afterwards.
    assert stored_bytes(coord, out.trace_id) == before
    assert coord.ctx.sink.repo.get_assessment(out.trace_id) == record_before
    assert rcoord.ctx.config["risks"]["version"] == live["risks"]["version"] and rcoord.ctx.rulesets == {}
    assert {p: sha256_hex(p.read_bytes()) for p in repo_files} == repo_files
