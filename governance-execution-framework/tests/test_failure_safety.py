"""Task 20.3: failure safety. No failure path yields VALID/PASS; a failed mandatory stage yields no normal decision.

Complements test_adapters_failure.py (CALM/Spectral CLI failures), test_props_facts_decider.py (Property 10) and
test_props_coordinator.py (Unit error -> no decision). This file adds ModelGateway, artifact store/persistence and
per-stage coordinator failure coverage.
"""
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from agip_shared.contracts import Decision, SpectralRun
from agip_shared.gateway import ModelGateway, ModelUnavailableError, RecordingMissingError
from agip_shared.gateway.recorder import Recorder
from agip_shared.settings import Settings
from governance_execution.adapters.calm import CalmAdapter
from governance_execution.adapters.spectral import SpectralAdapter
from governance_execution.exec import factory
from governance_execution.store import artifacts as art_mod
from governance_execution.store.artifacts import (ArtifactImmutableError, ArtifactIntegrityError, ArtifactNotFound,
                                                  FileArtifactStore)
from governance_execution.store.repository import MemoryRepository
from governance_execution.store.sink import ArtifactSink
from governance_execution.units import control_assessment, decision_remediation, registry
from governance_execution.units.calm_builder import instantiate, load_template

ROOT = Path(__file__).resolve().parents[2]
FORMS = ROOT / "governance-execution-framework" / "forms"
SETTINGS = Settings(_env_file=None, decider_provider="fixture", model_provider="replay")
TPL, TEXT = load_template("RA03-LITE")
NORMAL = {"APPROVED", "APPROVED_WITH_CONDITIONS", "RESTRICTED", "REJECTED"}
TID = "a" * 32


def build(d, mode="normal"):
    return factory.build(mode, settings=SETTINGS, repo=MemoryRepository(d), data_dir=d, cli="replay")


def assess(coord, ex, v="v1"):
    form = yaml.safe_load((FORMS / f"{v}.attributes.yaml").read_text(encoding="utf-8"))
    r = instantiate(form, template=TPL, template_text=TEXT, template_status="PUBLISHED", calm=coord.ctx.calm)
    assert r.app_model is not None, r.errors
    return coord.run(r.app_model, executor=ex, template_id="RA03-LITE", source={"app_id": form["app"]["id"]})


def kinds(coord, out):
    return {a.kind for a in coord.ctx.sink.list(out.trace_id)}


def assert_no_normal_decision(coord, out):
    assert out.status == "FAILED" and out.decision is None and out.error
    assert "decision" not in out.artifacts and "remediation" not in out.artifacts
    assert not ({"decision", "remediation"} & kinds(coord, out))
    assert coord.ctx.sink.repo.get_assessment(out.trace_id)["decision"] is None


@pytest.fixture(scope="module")
def baseline(tmp_path_factory):
    coord, ex = build(tmp_path_factory.mktemp("base"))
    out = assess(coord, ex)
    items = coord.ctx.sink.get(out.trace_id, "remediation", "result")["items"]
    dec = Decision.model_validate(coord.ctx.sink.get(out.trace_id, "decision", "result"))
    return SimpleNamespace(out=out, items=items, decision=dec)


# ---- 1. ModelGateway ------------------------------------------------------------------------------
class Rt:
    def __init__(self, out=None, exc=None):
        self.out, self.exc, self.calls = out, exc, 0

    def complete(self, prompt, model, region):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.out


RT_ERRORS = [RuntimeError("bedrock ThrottlingException"), TimeoutError("read timeout"),
             subprocess.TimeoutExpired("x", 1), ConnectionError("down"), OSError("socket"), KeyError("k")]


@pytest.mark.parametrize("exc", RT_ERRORS, ids=lambda e: type(e).__name__)
def test_gateway_runtime_failure_is_encoded_and_not_recorded(tmp_path, exc):
    rec = Recorder(tmp_path / "rec")
    gw = ModelGateway("bedrock", "m", "r", rec, Rt(exc=exc))
    with pytest.raises(ModelUnavailableError, match=type(exc).__name__):
        gw.complete("remediation", "v1", {"a": 1})
    assert rec.list_records() == []


def test_gateway_error_message_is_scrubbed_and_bounded():
    gw = ModelGateway("bedrock", "m", "r", None, Rt(exc=RuntimeError("token=abc123 at C:\\secret\\x " + "z" * 500)))
    with pytest.raises(ModelUnavailableError) as ei:
        gw.complete("p", "v1", {})
    assert "abc123" not in str(ei.value) and "C:\\secret" not in str(ei.value) and len(str(ei.value)) < 300


@pytest.mark.parametrize("gw", [ModelGateway("none"), ModelGateway("bedrock", "m", "r", None, None)],
                         ids=["none", "no-runtime"])
def test_gateway_unconfigured_is_unavailable(gw):
    with pytest.raises(ModelUnavailableError):
        gw.complete("p", "v1", {})


def test_gateway_replay_missing_record_is_encoded(tmp_path):
    gw = ModelGateway("replay", "m", "r", Recorder(tmp_path / "empty"))
    with pytest.raises(RecordingMissingError, match=r"missing recording: p/v1/[0-9a-f]{64}"):
        gw.complete("p", "v1", {"a": 1})
    with pytest.raises(RecordingMissingError):
        ModelGateway("replay").complete("p", "v1", {"a": 1})  # no recorder at all


def test_gateway_replay_corrupt_record_is_encoded(tmp_path):
    rec = Recorder(tmp_path / "rec")
    h = ModelGateway.input_hash("p", "v1", {"a": 1})
    rec.path_for("p", "v1", h).parent.mkdir(parents=True, exist_ok=True)
    rec.path_for("p", "v1", h).write_text("{not json", encoding="utf-8")
    with pytest.raises(RecordingMissingError):
        ModelGateway("replay", "m", "r", rec).complete("p", "v1", {"a": 1})


def test_gateway_recording_write_failure_is_encoded(tmp_path, monkeypatch):
    rec = Recorder(tmp_path / "rec")
    monkeypatch.setattr(Recorder, "save", lambda self, r: (_ for _ in ()).throw(PermissionError("read-only")))
    with pytest.raises(ModelUnavailableError):
        ModelGateway("bedrock", "m", "r", rec, Rt(out='{"fix_prompt": "x"}')).complete("p", "v1", {})


@pytest.mark.parametrize("text", ["not json at all", "", "[1, 2, 3]", "null", "```json\n{broken\n```", '"just a string"'])
def test_gateway_invalid_output_never_changes_decision(baseline, text):
    gw = ModelGateway("bedrock", "m", "r", None, Rt(out=text))
    rem = decision_remediation.remediate(baseline.decision, [dict(i) for i in baseline.items], gw, "normal")
    assert rem["decision"] == baseline.decision.decision and rem["conditions"] == list(baseline.decision.conditions)
    assert [i["text"] for i in rem["items"]] == [i["text"] for i in baseline.items]


@pytest.mark.parametrize("gw", [
    ModelGateway("bedrock", "m", "r", None, Rt(exc=TimeoutError("t"))),
    ModelGateway("bedrock", "m", "r", None, Rt(exc=RuntimeError("provider error"))),
    ModelGateway("none"),
    ModelGateway("replay", "m", "r", Recorder("does-not-exist-dir")),
], ids=["timeout", "provider-error", "none", "replay-missing"])
def test_remediate_falls_back_to_deterministic_list(baseline, gw, tmp_path):
    if gw.provider == "replay":
        gw.recorder = Recorder(tmp_path / "empty")
    rem = decision_remediation.remediate(baseline.decision, [dict(i) for i in baseline.items], gw, "normal")
    assert rem["source"] == "deterministic" and rem["fix_prompt"] is None and rem["reason"]
    assert rem["deterministic_list"] == decision_remediation.deterministic_list(baseline.items)
    assert rem["decision"] == baseline.decision.decision


def test_remediate_replay_mode_raises_on_missing_recording(baseline, tmp_path):
    gw = ModelGateway("replay", "m", "r", Recorder(tmp_path / "empty"))
    items = [{"id": "C1", "kind": "control", "text": "fix it"}]
    with pytest.raises(RecordingMissingError):
        decision_remediation.remediate(baseline.decision, items, gw, "replay")


@pytest.mark.parametrize("exc", [RuntimeError("provider"), TimeoutError("t")], ids=["provider-error", "timeout"])
def test_coordinator_survives_gateway_failure_with_same_decision(tmp_path, baseline, exc):
    coord, ex = build(tmp_path)
    coord.ctx.gateway = ModelGateway("bedrock", "m", "r", Recorder(tmp_path / "rec"), Rt(exc=exc))
    out = assess(coord, ex)
    assert out.status == baseline.out.status == "COMPLETED" and out.decision == baseline.out.decision
    rem = coord.ctx.sink.get(out.trace_id, "remediation", "result")
    assert rem["source"] == "deterministic" and rem["decision"] == baseline.decision.decision


def test_coordinator_survives_recording_write_failure(tmp_path, baseline, monkeypatch):
    coord, ex = build(tmp_path)
    coord.ctx.gateway = ModelGateway("bedrock", "m", "r", Recorder(tmp_path / "rec"), Rt(out='{"fix_prompt": "x"}'))
    monkeypatch.setattr(Recorder, "save", lambda self, r: (_ for _ in ()).throw(OSError("disk full")))
    out = assess(coord, ex)
    assert out.status == "COMPLETED" and out.decision == baseline.out.decision


# ---- 2. Artifact store ----------------------------------------------------------------------------
def test_store_write_failure_is_surfaced_and_not_recorded(tmp_path, monkeypatch):
    repo = MemoryRepository(tmp_path)
    sink = ArtifactSink(repo, tmp_path)
    monkeypatch.setattr(Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(PermissionError("denied")))
    with pytest.raises(PermissionError):
        sink.put(TID, "k", "i", {"a": 1})
    monkeypatch.undo()
    assert repo.list_artifacts(TID) == []


def test_store_fsync_failure_is_surfaced(tmp_path, monkeypatch):
    monkeypatch.setattr(art_mod.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("I/O error")))
    with pytest.raises(OSError):
        FileArtifactStore(tmp_path).put(TID, "k", "i", {"a": 1})


def test_store_repo_record_failure_is_surfaced(tmp_path, monkeypatch):
    repo = MemoryRepository(tmp_path)
    monkeypatch.setattr(repo, "record_artifact", lambda a: (_ for _ in ()).throw(RuntimeError("db down")))
    with pytest.raises(RuntimeError, match="db down"):
        ArtifactSink(repo, tmp_path).put(TID, "k", "i", {"a": 1})


def test_store_existing_artifact_is_immutable(tmp_path):
    s = FileArtifactStore(tmp_path)
    a = s.put(TID, "k", "i", {"a": 1})
    assert s.put(TID, "k", "i", {"a": 1}).sha256 == a.sha256  # identical content: no-op
    before = (tmp_path / a.path).read_bytes()
    with pytest.raises(ArtifactImmutableError):
        s.put(TID, "k", "i", {"a": 2})
    assert (tmp_path / a.path).read_bytes() == before


def test_store_hash_mismatch_and_missing_are_errors(tmp_path):
    s = FileArtifactStore(tmp_path)
    a = s.put(TID, "k", "i", {"a": 1})
    assert s.verify(a) and s.get(TID, "k", "i", a.sha256) == {"a": 1}
    (tmp_path / a.path).write_bytes(b'{"a": 99}')
    assert not s.verify(a)
    with pytest.raises(ArtifactIntegrityError):
        s.get(TID, "k", "i", a.sha256)
    with pytest.raises(ArtifactNotFound):
        s.get(TID, "k", "absent")
    assert not s.verify(a.model_copy(update={"path": "../escape.json"}))


def test_sink_get_detects_tampered_artifact(tmp_path):
    sink = ArtifactSink(MemoryRepository(tmp_path), tmp_path)
    a = sink.put(TID, "k", "i", {"a": 1})
    (tmp_path / a.path).write_bytes(b'{"a": 2}')
    with pytest.raises(ArtifactIntegrityError):
        sink.get(TID, "k", "i")


def _fail_kind(monkeypatch, bad):
    orig = FileArtifactStore.put

    def put(self, trace_id, kind, artifact_id, content, versions=None):
        if kind == bad:
            raise OSError(f"disk full writing {kind}")
        return orig(self, trace_id, kind, artifact_id, content, versions)
    monkeypatch.setattr(FileArtifactStore, "put", put)


MANDATORY_KINDS = ["calm_validation", "spectral_controls_parsed", "spectral_risks_parsed", "facts", "control_gap",
                   "risk_profile", "decision"]


@pytest.mark.parametrize("kind", MANDATORY_KINDS)
def test_persistence_failure_on_mandatory_stage_yields_no_decision(tmp_path, monkeypatch, kind):
    coord, ex = build(tmp_path)
    _fail_kind(monkeypatch, kind)
    out = assess(coord, ex)
    assert_no_normal_decision(coord, out)
    assert "disk full" in out.error


@pytest.mark.parametrize("kind", ["app_model", "versions", "trace"])
def test_persistence_failure_in_coordinator_bookkeeping_raises_no_decision(tmp_path, monkeypatch, kind):
    coord, ex = build(tmp_path)
    _fail_kind(monkeypatch, kind)
    with pytest.raises(OSError):
        assess(coord, ex)


# ---- 3. Forced failure of each mandatory stage ----------------------------------------------------
STAGES = [  # (unit, action, label, kinds that must NOT exist because they derive from the failed stage)
    ("calm_builder", "validate", "calm", {"calm_validation", "control_gap", "risk_profile", "decision"}),
    ("control_assessment", "lint", "spectral_controls", {"control_gap", "risk_profile", "decision"}),
    ("risk_assessment", "lint", "spectral_risks", {"risk_profile", "decision"}),
    ("risk_assessment", "facts", "facts", {"facts", "risk_profile", "decision"}),
    ("control_assessment", "assess", "control_assessment", {"control_gap", "decision"}),
    ("risk_assessment", "assess", "risk_assessment", {"risk_profile", "decision"}),
]


def _fail_stage(monkeypatch, unit, action, exc):
    orig = registry.UNITS[unit]

    def handler(task, ctx):
        if task.params.get("action") == action:
            raise exc
        return orig(task, ctx)
    monkeypatch.setitem(registry.UNITS, unit, handler)


@pytest.mark.parametrize("exc", [RuntimeError("stage exploded"), RecordingMissingError("rec"), KeyError("k")],
                         ids=["runtime", "recording-missing", "keyerror"])
@pytest.mark.parametrize("unit,action,label,absent", STAGES, ids=[s[2] for s in STAGES])
def test_failed_mandatory_stage_yields_no_decision_pass_or_valid(tmp_path, monkeypatch, unit, action, label, absent, exc):
    coord, ex = build(tmp_path)
    _fail_stage(monkeypatch, unit, action, exc)
    out = assess(coord, ex)
    assert_no_normal_decision(coord, out)
    present = kinds(coord, out)
    assert not (absent & present), absent & present
    assert "unit_error" in present
    if "control_gap" in present:  # e.g. only the risk lane failed: control results exist but no decision came of them
        assert out.decision is None
    if "calm_validation" in present:
        assert coord.ctx.sink.get(out.trace_id, "calm_validation", "result")["status"] != "VALID" or label != "calm"


def test_incomplete_stage_that_returns_ok_without_output_yields_no_decision(tmp_path, monkeypatch):
    """A stage that reports OK but wrote nothing must not be turned into a decision."""
    orig = registry.UNITS["control_assessment"]
    monkeypatch.setitem(registry.UNITS, "control_assessment",
                        lambda t, c: [] if t.params.get("action") == "assess" else orig(t, c))
    coord, ex = build(tmp_path)
    out = assess(coord, ex)
    assert "control_gap" not in kinds(coord, out)
    assert out.decision not in NORMAL  # fail-safe INDETERMINATE


# ---- adapter-level failures through the full run ---------------------------------------------------
def _runner(exc=None, stdout=""):
    def run(args, timeout_s, cwd):
        if args[1:] == ["--version"]:
            return 0, "1.0.0\n", ""
        if exc:
            raise exc
        return 0, stdout, ""
    return run


TOOL_FAILURES = [dict(exc=FileNotFoundError()), dict(exc=subprocess.TimeoutExpired("x", 1)),
                 dict(stdout="not json"), dict(stdout="")]
TOOL_IDS = ["missing", "timeout", "garbage", "empty"]


@pytest.mark.parametrize("kw", TOOL_FAILURES, ids=TOOL_IDS)
def test_calm_tool_failure_in_run_is_never_valid_and_never_normal_decision(tmp_path, kw):
    coord, ex = build(tmp_path)
    coord.ctx.calm = CalmAdapter(runner=_runner(**kw))
    form = yaml.safe_load((FORMS / "v1.attributes.yaml").read_text(encoding="utf-8"))
    app = instantiate(form, template=TPL, template_text=TEXT, template_status="PUBLISHED", calm=build(tmp_path / "x")[0].ctx.calm).app_model
    out = coord.run(app, executor=ex, template_id="RA03-LITE")
    if out.status == "FAILED":
        assert_no_normal_decision(coord, out)
        return
    v = coord.ctx.sink.get(out.trace_id, "calm_validation", "result")
    assert v["status"] != "VALID"
    assert out.status == "BLOCKED" and out.decision is None and out.validation_status == "INVALID"
    assert not ({"control_gap", "risk_profile"} & kinds(coord, out))


@pytest.mark.parametrize("lane", ["controls", "risks"])
@pytest.mark.parametrize("kw", TOOL_FAILURES, ids=TOOL_IDS)
def test_spectral_tool_failure_in_run_never_passes_or_approves(tmp_path, lane, kw):
    coord, ex = build(tmp_path)
    good = coord.ctx.spectral
    bad = SpectralAdapter(runner=_runner(**kw))

    class Mixed:
        last = None

        def lint(self, text, ruleset):
            a = bad if f"{lane}.spectral" in str(ruleset) else good
            res = a.lint(text, ruleset)
            self.last = a.last
            return res
    coord.ctx.spectral = Mixed()
    out = assess(coord, ex)
    assert out.decision in (None, "INDETERMINATE") and out.decision not in NORMAL
    if lane == "controls":
        gap = coord.ctx.sink.get(out.trace_id, "control_gap", "result")
        assert gap["controls"] and all(c["status"] == "ERROR" for c in gap["controls"])
        assert gap["gap_level"] == "INDETERMINATE_INPUT"
    else:
        prof = coord.ctx.sink.get(out.trace_id, "risk_profile", "result")
        assert prof["mandatory_trigger"] == "UNEVALUABLE" and out.decision == "INDETERMINATE"  # gate G3


# ---- 4. Spectral ERROR never yields control PASS ---------------------------------------------------
def test_spectral_error_run_never_yields_control_pass_unit(tmp_path):
    coord, _ = build(tmp_path)
    cfg = coord.ctx.config
    for err in ("missing", "timeout", "invalid output"):
        run = SpectralRun(status="ERROR", error=err)
        for app in ({}, {"nodes": []}, {"nodes": [{"unique-id": "n", "node-type": "service"}]}):
            gap = control_assessment.assess(run, cfg["controls"], app, cfg["gap_rule"])
            assert gap.controls
            assert all(c.status == "ERROR" for c in gap.controls), [c.status for c in gap.controls]
            assert not any(c.status == "PASS" for c in gap.controls)
            assert gap.gap_level == "INDETERMINATE_INPUT"


def test_spectral_ok_but_empty_still_passes_only_when_run_ok(tmp_path):
    """Control: an OK run with no findings passes, so the ERROR assertions above are meaningful."""
    coord, _ = build(tmp_path)
    cfg = coord.ctx.config
    gap = control_assessment.assess(SpectralRun(status="OK"), cfg["controls"], {"nodes": []}, cfg["gap_rule"])
    assert any(c.status in ("PASS", "NOT_APPLICABLE") for c in gap.controls)
