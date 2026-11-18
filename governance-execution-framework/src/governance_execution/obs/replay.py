"""Replay_Mode: re-run an assessment from recorded LLM and Decider outputs with zero model calls (Req 24.2-24.4).

The replay gets a new Trace_ID. Artifacts are compared after removing run-specific fields
(``trace_id``, ``created``, ``latency_ms``, ``duration_s``, ``exit_code`` is kept). A missing recording fails
the replay with the record named.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml
from agip_shared.hashing import canonical_hash

RUN_SPECIFIC = {"trace_id", "created", "latency_ms", "duration_s", "raw_artifact_id", "parsed_artifact_id", "timestamp"}
NOT_COMPARED = {"versions", "trace", "unit_error", "assessment_record"}   # run record: mode, started, finished, trace ids   # versions carries mode/executor; trace carries step timing


class ReplayFailed(RuntimeError):
    """Raised when a replay cannot run or the replayed assessment fails (for example a missing recording or unknown assessment)."""
    pass


@dataclass
class ReplayReport:
    """Outcome of a replay: both trace ids and decisions, whether they are identical, and the artifacts that differ."""
    original_trace: str
    replay_trace: str
    decision_original: Any
    decision_replay: Any
    identical: bool
    differences: list[str] = field(default_factory=list)


def normalise(obj: Any) -> Any:
    """Recursively drop run-specific keys (RUN_SPECIFIC) from dicts so artifacts of two runs can be compared."""
    if isinstance(obj, dict):
        return {k: normalise(v) for k, v in obj.items() if k not in RUN_SPECIFIC}
    if isinstance(obj, list):
        return [normalise(v) for v in obj]
    return obj


def fingerprint(sink: Any, trace_id: str) -> dict[str, str]:
    """Map ``kind/id`` to the canonical hash of the normalised artifact for every comparable artifact of a trace."""
    return {f"{a.kind}/{a.id}": canonical_hash(normalise(sink.get(trace_id, a.kind, a.id)))
            for a in sink.list(trace_id) if a.kind not in NOT_COMPARED}


def replay(original_trace: str, coordinator: Any, executor: Any) -> ReplayReport:
    """``coordinator`` must be built with mode ``replay`` (LLM replay provider, Decider fixtures)."""
    if coordinator.ctx.mode != "replay":
        raise ValueError("replay needs a coordinator built with mode='replay'")
    sink = coordinator.ctx.sink
    record = sink.repo.get_assessment(original_trace)
    if record is None:
        raise ReplayFailed(f"assessment {original_trace} not found")
    app = sink.get(original_trace, "app_model", "app")
    ctx = coordinator.ctx
    saved = (ctx.config, ctx.rulesets, getattr(ctx.decider, "policy", None))
    try:
        snap = sink.get(original_trace, "config_snapshot", "snapshot")
    except Exception:  # noqa: BLE001  (assessments stored before snapshots existed replay from live config)
        snap = None
    try:
        if snap:   # use the frozen catalogs, scoring profile, policies and rulesets, not the live files
            frozen = yaml.safe_load(snap["config_yaml"])
            ctx.config = {**ctx.config, **frozen}
            if ctx.decider is not None and "decider_policy" in frozen:
                ctx.decider.policy = frozen["decider_policy"]
            d = (sink.files.data_dir / "replay-rulesets" / original_trace).resolve()   # absolute: tools run in a temp cwd
            d.mkdir(parents=True, exist_ok=True)
            for lane, text in snap["rulesets"].items():
                (d / f"{lane}.spectral.yaml").write_text(text, encoding="utf-8", newline="")
            ctx.rulesets = {lane: d / f"{lane}.spectral.yaml" for lane in snap["rulesets"]}
        out = coordinator.run(app, executor=executor, template_id=(record.get("versions") or {}).get("template_id"),
                              source={**(record.get("source") or {}), "replay_of": original_trace})
    finally:
        ctx.config, ctx.rulesets = saved[0], saved[1]
        if ctx.decider is not None and saved[2] is not None:
            ctx.decider.policy = saved[2]
    if out.status == "FAILED":
        raise ReplayFailed(out.error or "replay failed")
    a, b = fingerprint(sink, original_trace), fingerprint(sink, out.trace_id)
    diffs = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    return ReplayReport(original_trace, out.trace_id, record.get("decision"), out.decision,
                        not diffs and record.get("decision") == out.decision, diffs)
