"""Task 23.9: standalone governance CLI on an external CALM file, plus task 23.7 status separation.

CALM and Spectral run from recorded outputs (``--cli replay``) or from stub runners; the LLM and the Decider use
recordings, fixtures or stubs. Nothing here calls Bedrock or a Decider endpoint.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from governance_execution import cli
from governance_execution.adapters.calm import CalmAdapter
from governance_execution.adapters.decider import DeciderGateway
from governance_execution.adapters.spectral import SpectralAdapter
from governance_execution.exec import coordinator as coord_mod

ROOT = Path(__file__).resolve().parents[2]
VARIANTS = ROOT / "calm-app-generation-framework" / "fixtures" / "variants"
EXPECTED = yaml.safe_load((VARIANTS / "expected.yaml").read_text(encoding="utf-8"))
VALID_CALM_OUT = json.dumps({"jsonSchemaValidationOutputs": [], "spectralSchemaValidationOutputs": [],
                             "hasErrors": False, "hasWarnings": False})
REPLAY_ARGS = ["--mode", "replay", "--cli", "replay", "--template", "RA03-LITE"]


pytestmark = pytest.mark.acceptance

def external(tmp_path, v="v1"):
    """A CALM file outside the repo (copy of a variant)."""
    dst = tmp_path / "ext" / f"{v}-arch.json"
    dst.parent.mkdir(exist_ok=True)
    dst.write_text((VARIANTS / f"invoice-lite-{v}.json").read_text(encoding="utf-8"), encoding="utf-8")
    return dst


def run_cli(capsys, *argv, builder=None):
    code = cli.main([str(a) for a in argv], **({"builder": builder} if builder else {}))
    return code, json.loads(capsys.readouterr().out)


def assess(capsys, tmp_path, v, extra=REPLAY_ARGS):
    data = tmp_path / "data"
    code, out = run_cli(capsys, "assess", external(tmp_path, v), "--data-dir", data, *extra)
    return code, out, data


def stub_builder(*, spectral, calm_out=VALID_CALM_OUT, mutate=None):
    """Builder with stub CALM/Spectral runners. ``spectral``: lane -> list of rule codes that fire."""
    def calm_runner(args, timeout_s, cwd):
        return (0, "1.0.0\n", "") if args[1:] == ["--version"] else (0, calm_out, "")

    def spectral_runner(args, timeout_s, cwd):
        if args[1:] == ["--version"]:
            return 0, "6.0.0\n", ""
        lane = "controls" if "controls.spectral" in args[3] else "risks"
        res = [{"code": c, "path": ["nodes"], "message": c, "severity": 0} for c in spectral.get(lane, [])]
        return (1 if res else 0), json.dumps(res), ""

    def build(mode, **kw):
        coord, ex = cli.build_runtime(mode, **kw)
        coord.ctx.calm = CalmAdapter(runner=calm_runner)
        coord.ctx.spectral = SpectralAdapter(runner=spectral_runner)
        if mutate:
            mutate(coord)
        return coord, ex
    return build


def autopilot_app(tmp_path):
    app = json.loads((VARIANTS / "invoice-lite-v1.json").read_text(encoding="utf-8"))
    for n in app["nodes"]:
        if "autonomy" in (n.get("metadata") or {}):
            n["metadata"]["autonomy"] = "auto-pilot"       # not in the taxonomy: mandatory trigger cannot be evaluated
    f = tmp_path / "ext" / "autopilot.json"
    f.parent.mkdir(exist_ok=True)
    f.write_text(json.dumps(app), encoding="utf-8")
    return f


# ---- scenarios on an external CALM file -------------------------------------------------------------------
def test_valid_calm_completes_with_decision(capsys, tmp_path):
    code, out, data = assess(capsys, tmp_path, "v1")
    assert code == 0
    assert (out["assessment_status"], out["validation_status"], out["decision"]) == ("COMPLETED", "VALID", EXPECTED["v1"]["decision"])
    assert len(out["trace_id"]) == 32 and out["executor"] == "Direct_Adapter"


def test_invalid_calm_is_blocked_with_no_decision(capsys, tmp_path):
    code, out, data = assess(capsys, tmp_path, "v4")
    assert code == 3
    assert (out["assessment_status"], out["validation_status"], out["decision"]) == ("BLOCKED", "INVALID", None)
    _, shown = run_cli(capsys, "show", out["trace_id"], "--data-dir", data)
    assert "decision" not in shown["artifacts"] and "control_gap" not in shown["artifacts"]
    assert shown["assessment_status"] == "BLOCKED" and shown["decision"] is None
    assert EXPECTED["v4"]["status"] == "BLOCKED" and EXPECTED["v4"]["decision"] is None


def test_triggered_risk(capsys, tmp_path):
    _, out, data = assess(capsys, tmp_path, "v3")
    assert out["decision"] == EXPECTED["v3"]["decision"] and out["assessment_status"] == "COMPLETED"
    _, shown = run_cli(capsys, "show", out["trace_id"], "--data-dir", data)
    prof = json.loads((data / "artifacts" / out["trace_id"] / "risk_profile" / "result.json").read_text(encoding="utf-8"))
    assert sorted(r["risk_id"] for r in prof["risks"]) == EXPECTED["v3"]["triggered_risks"]
    assert shown["gates_fired"] == []


def test_failed_mandatory_control_rejects_via_gate(capsys, tmp_path):
    _, out, data = assess(capsys, tmp_path, "v2")
    assert out["decision"] == "REJECTED"
    _, shown = run_cli(capsys, "show", out["trace_id"], "--data-dir", data)
    assert shown["gates_fired"] == [EXPECTED["v2"]["gate"]]


def test_provider_failure_decider_stub_still_completes(capsys, tmp_path):
    def decider_down(coord):
        def post(url, body, timeout_s):
            raise ConnectionError("endpoint unreachable")
        coord.ctx.decider = DeciderGateway(coord.ctx.config["decider_policy"], "http", "http://decider.invalid", "", 1, post=post)

    code, out = run_cli(capsys, "assess", external(tmp_path), "--data-dir", tmp_path / "d", "--mode", "no-llm",
                        "--cli", "replay", "--template", "RA03-LITE",
                        builder=stub_builder(spectral={}, mutate=decider_down))
    assert code == 0 and out["assessment_status"] == "COMPLETED" and out["decision"] is not None   # Decider is advisory


def test_provider_failure_missing_llm_recording_fails_without_decision(capsys, tmp_path):
    def no_recordings(coord):
        coord.ctx.gateway.recorder.root = tmp_path / "empty"

    code, out = run_cli(capsys, "assess", external(tmp_path, "v2"), "--data-dir", tmp_path / "d", *REPLAY_ARGS,
                        builder=lambda mode, **kw: _with(cli.build_runtime(mode, **kw), no_recordings))
    assert code == 2 and out["assessment_status"] == "FAILED" and out["decision"] is None
    assert "missing" in (out["error"] or "").lower() or "recording" in (out["error"] or "").lower()


def _with(pair, fn):
    fn(pair[0])
    return pair


def test_gate_precedence_payment_gate_overrides_unevaluable(capsys, tmp_path):
    spectral = {"controls": ["ctl-payment-requires-human-approval"]}
    code, out = run_cli(capsys, "assess", autopilot_app(tmp_path), "--data-dir", tmp_path / "d", "--mode", "no-llm",
                        "--decider", "fixture", "--cli", "replay", builder=stub_builder(spectral=spectral))
    assert out["decision"] == "REJECTED" and out["assessment_status"] == "COMPLETED"
    _, shown = run_cli(capsys, "show", out["trace_id"], "--data-dir", tmp_path / "d")
    assert shown["gates_fired"] == ["G2-PAYMENT-AUTH", "G3-UNEVALUABLE"]   # both fire; the first in order wins


def test_unevaluable_mandatory_trigger_is_completed_indeterminate(capsys, tmp_path):
    code, out = run_cli(capsys, "assess", autopilot_app(tmp_path), "--data-dir", tmp_path / "d", "--mode", "no-llm",
                        "--decider", "fixture", "--cli", "replay", builder=stub_builder(spectral={}))
    assert (code, out["assessment_status"], out["decision"]) == (0, "COMPLETED", "INDETERMINATE")


def test_unit_error_is_failed_with_no_decision(capsys, tmp_path):
    def boom(args, timeout_s, cwd):
        raise RuntimeError("boom")
    _, out = run_cli(capsys, "assess", external(tmp_path), "--data-dir", tmp_path / "d", "--mode", "no-llm", "--cli", "replay",
                     builder=lambda mode, **kw: _with(cli.build_runtime(mode, **kw), lambda c: setattr(c.ctx, "spectral", _Raises())))
    assert out["assessment_status"] == "FAILED" and out["decision"] is None


class _Raises:
    def lint(self, *a, **k):
        raise RuntimeError("boom")


def test_unreadable_file_fails(capsys, tmp_path):
    code, out = run_cli(capsys, "assess", tmp_path / "missing.json")
    assert code == 2 and out["assessment_status"] == "FAILED" and out["decision"] is None


# ---- WAITING_FOR_HUMAN is policy driven; default continues and lists the tasks ----------------------------------
@pytest.mark.parametrize("block, status", [(False, "COMPLETED"), (True, "WAITING_FOR_HUMAN")])
def test_pending_human_tasks_status(capsys, tmp_path, monkeypatch, block, status):
    monkeypatch.setattr(coord_mod, "_pending_tasks", lambda sink, trace: ["decider-review-x"])

    def policy(coord):
        coord.ctx.config["decider_policy"] = {**coord.ctx.config["decider_policy"], "block_on_pending_human": block}
    code, out = run_cli(capsys, "assess", external(tmp_path), "--data-dir", tmp_path / "d", *REPLAY_ARGS,
                        builder=lambda mode, **kw: _with(cli.build_runtime(mode, **kw), policy))
    assert out["assessment_status"] == status and out["pending_human_tasks"] == ["decider-review-x"]
    # blocking policy: the run stops after facts, so there is no decision until the human tasks are resolved (24.3)
    assert out["decision"] == (None if block else EXPECTED["v1"]["decision"])


# ---- stored record, replay, show ------------------------------------------------------------------------------
def test_assessment_record_stores_separate_statuses(capsys, tmp_path):
    _, out, data = assess(capsys, tmp_path, "v4")
    rec = json.loads((data / "artifacts" / out["trace_id"] / "assessment_record" / "assessment.json").read_text(encoding="utf-8"))
    assert (rec["assessment_status"], rec["validation_status"], rec["decision"]) == ("BLOCKED", "INVALID", None)


@pytest.mark.parametrize("v", ["v1", "v2", "v4"])
def test_replay_command_is_identical(capsys, tmp_path, v):
    _, out, data = assess(capsys, tmp_path, v)
    code, rep = run_cli(capsys, "replay", out["trace_id"], "--data-dir", data, "--cli", "replay")
    assert code == 0 and rep["identical"] is True and rep["replay_trace"] != out["trace_id"]
    assert rep["decision_original"] == rep["decision_replay"] == out["decision"]


def test_replay_unknown_trace(capsys, tmp_path):
    code, rep = run_cli(capsys, "replay", "f" * 32, "--data-dir", tmp_path / "d", "--cli", "replay")
    assert code == 2 and "not found" in rep["error"]


def test_show_unknown_trace(capsys, tmp_path):
    code, out = run_cli(capsys, "show", "f" * 32, "--data-dir", tmp_path / "d")
    assert code == 2 and out["error"] == "assessment not found"


# ---- separation from the generation and authoring frameworks ----------------------------------------------------
def test_cli_subprocess_does_not_load_generation_or_authoring(tmp_path):
    f = external(tmp_path, "v2")
    data = tmp_path / "data"
    base = [sys.executable, "-m", "governance_execution"]
    p = subprocess.run([*base, "assess", str(f), "--data-dir", str(data), "--debug-modules", *REPLAY_ARGS],
                       capture_output=True, text=True, cwd=tmp_path, timeout=120)
    out = json.loads(p.stdout)
    assert p.returncode == 0, p.stderr
    assert out["decision"] == "REJECTED" and out["loaded_forbidden_modules"] == []
    p2 = subprocess.run([*base, "replay", out["trace_id"], "--data-dir", str(data), "--cli", "replay"],
                        capture_output=True, text=True, cwd=tmp_path, timeout=120)
    assert p2.returncode == 0 and json.loads(p2.stdout)["identical"] is True, p2.stderr
    p3 = subprocess.run([*base, "show", out["trace_id"], "--data-dir", str(data)], capture_output=True, text=True,
                        cwd=tmp_path, timeout=60)
    assert json.loads(p3.stdout)["decision"] == "REJECTED"
