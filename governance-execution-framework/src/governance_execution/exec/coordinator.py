"""Coordinator: the assessment steps, run through an Executor, Units invoked only via AgentTask (Req 21.3-21.5).

Steps (BPMN external tasks in the same order): validate_calm -> extract_facts -> {spectral_controls ||
spectral_risks} -> control_gap, risk_profile -> decide -> remediate. Invalid CALM blocks the assessment
(assessment status BLOCKED, validation status INVALID, no decision) and skips the governance steps. A Unit
error gives assessment status FAILED and no decision. Assessment, validation and decision are separate values. Every run gets a new Trace_ID.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from agip_shared.contracts import (AcceptedClassification, AgentResult, AgentTask, ExecutionStep, FactSet, FrameworkExecution,
                                   WorkflowRef)
from agip_shared.hashing import canonical_json, sha256_hex

from ..obs.otel import Tracing
from ..store.sink import ArtifactSink
from ..units.registry import UnitContext, invoke, ref
from . import rulesets

MODES = ("normal", "no-llm", "replay")


@dataclass(frozen=True)
class Step:
    """One coordinator step: a Unit action with the artifact kinds it consumes; steps sharing ``parallel_group`` may run concurrently."""
    name: str
    unit: str
    action: str
    inputs: tuple[str, ...]
    parallel_group: Optional[str] = None


GOVERNANCE_STEPS = (
    Step("extract_facts", "risk_assessment", "facts", ("app_model",)),
    Step("spectral_controls", "control_assessment", "lint", ("app_model",), "spectral"),
    Step("spectral_risks", "risk_assessment", "lint", ("app_model",), "spectral"),
    Step("control_gap", "control_assessment", "assess", ("spectral_controls_parsed", "app_model")),
    Step("risk_profile", "risk_assessment", "assess", ("spectral_risks_parsed", "facts", "app_model")),
    Step("decide", "decision_remediation", "decide", ("calm_validation", "control_gap", "risk_profile")),
    Step("remediate", "decision_remediation", "remediate", ("calm_validation", "control_gap", "risk_profile", "decision")),
)
BLOCKED_STEPS = (   # no decision: remediation only reports the CALM guidance
    Step("remediate", "decision_remediation", "remediate", ("calm_validation",)),
)


@dataclass
class AssessmentOutcome:
    """Result of one assessment run: status, decision, artifact refs, executed steps and any error or pending human tasks."""
    trace_id: str
    status: str                       # assessment status: COMPLETED | BLOCKED | FAILED | WAITING_FOR_HUMAN
    decision: Optional[str]
    executor: str
    mode: str
    artifacts: dict[str, str] = field(default_factory=dict)   # kind -> ref
    steps: list[dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    validation_status: Optional[str] = None   # VALID | INVALID | INCOMPLETE | ERROR
    pending_human_tasks: list[str] = field(default_factory=list)

    @property
    def assessment_status(self) -> str:
        """Alias of ``status`` (the assessment status, distinct from the CALM validation status)."""
        return self.status


class Coordinator:
    """Runs an assessment as a sequence of AgentTask/Unit calls through an Executor, and persists versions, trace and the assessment record."""
    def __init__(self, ctx: UnitContext, tracing: Optional[Tracing] = None):
        """Use the given Tracing, or create one that appends spans to ``otel-traces.log`` in the sink's data directory (the file stays open for the process lifetime)."""
        self.ctx = ctx
        if tracing is None:
            log = ctx.sink.files.data_dir / "otel-traces.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            tracing = Tracing(out=open(log, "a", encoding="utf-8"))
        self.tracing = tracing

    # One step = one AgentTask = one Unit call. Executors call this.
    def run_step(self, step: Step, trace_id: str, refs: dict[str, str], params: Optional[dict[str, Any]] = None) -> AgentResult:
        """Invoke one Unit action for ``step``. Returns an ERROR AgentResult if a required input ref is missing (control_gap and risk_profile are exempt)."""
        task = AgentTask(task_id=f"{trace_id[:8]}-{step.name}", unit=step.unit, trace_id=trace_id,
                         artifact_ids=[refs[k] for k in step.inputs if k in refs],
                         params={"action": step.action, **(params or {})})
        # control_gap and risk_profile are optional inputs: later steps tolerate their absence
        missing = [k for k in step.inputs if k not in refs and k not in ("control_gap", "risk_profile")]
        if missing:
            return AgentResult(task_id=task.task_id, status="ERROR", error=f"missing inputs: {missing}")
        with self.tracing.stage(step.name, unit=step.unit, action=step.action, trace_id=trace_id):
            return invoke(task, self.ctx)

    def run(self, app_model: dict[str, Any], *, executor: Any, template_id: Optional[str] = None,
            source: Optional[dict[str, Any]] = None, versions: Optional[dict[str, Any]] = None) -> AssessmentOutcome:
        """Validate CALM, then run the governance steps through ``executor`` and persist the outcome. Invalid CALM gives BLOCKED with no decision; a failing step gives FAILED; pending human review pauses with WAITING_FOR_HUMAN. Raises ValueError for an unknown mode."""
        mode = self.ctx.mode
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        sink: ArtifactSink = self.ctx.sink
        started = datetime.now(timezone.utc).isoformat()
        with self.tracing.assessment("assessment", mode=mode, executor=executor.label) as trace_id:
            out = AssessmentOutcome(trace_id, "FAILED", None, executor.label, mode)
            refs: dict[str, str] = {}
            sink.put(trace_id, "app_model", "app", app_model)
            refs["app_model"] = ref("app_model", "app")
            res = self.run_step(Step("validate_calm", "calm_builder", "validate", ("app_model",)), trace_id, refs,
                                {"template_id": template_id})
            out.steps.append({"step": "validate_calm", "status": res.status, "error": res.error})
            if res.status == "OK":
                refs.update({r.partition(":")[0]: r for r in res.artifact_ids})
                calm_status = sink.get(trace_id, "calm_validation", "result")["status"]
                out.validation_status = calm_status if calm_status in ("VALID", "INVALID", "INCOMPLETE") else "ERROR"
                if out.validation_status == "ERROR":      # the validator could not run: a failure, not a verdict on the CALM
                    out.error = "CALM validation error"
                else:
                    steps = GOVERNANCE_STEPS if calm_status == "VALID" else BLOCKED_STEPS
                    block = calm_status == "VALID" and self._blocks_on_human()
                    waiting = False
                    if block:   # stop right after facts when a Decider answer needs a human (task 24.3)
                        ok, err = executor.execute(self, steps[:1], trace_id, refs, out.steps)
                        pend = _pending_tasks(sink, trace_id) if ok else []
                        if ok and pend:
                            waiting = True
                            out.status, out.pending_human_tasks = "WAITING_FOR_HUMAN", pend
                            self._persist_waiting(trace_id, out, refs, template_id, source, versions, started, executor)
                        elif ok:
                            ok, err = executor.execute(self, steps[1:], trace_id, refs, out.steps)
                    else:
                        ok, err = executor.execute(self, steps, trace_id, refs, out.steps)
                    if waiting:
                        pass
                    elif ok and calm_status == "VALID":
                        out.decision = sink.get(trace_id, "decision", "result")["decision"]
                        out.status = "COMPLETED"
                        out.pending_human_tasks = _pending_tasks(sink, trace_id)
                    elif ok:
                        out.status = "BLOCKED"            # invalid CALM: no decision
                        out.error = "CALM validation " + str(calm_status)
                    else:
                        out.error = err
            else:
                out.validation_status = "ERROR"
                out.error = res.error
            self._finalize(trace_id, out, refs, executor, app_model, source, versions, template_id, started)
        return out

    # ---- shared tail of run() and resume(): config snapshot, versions, trace, assessment record --------------
    def _finalize(self, trace_id: str, out: AssessmentOutcome, refs: dict[str, str], executor: Any, app_model: dict[str, Any],
                  source: Optional[dict[str, Any]], versions: Optional[dict[str, Any]], template_id: Optional[str],
                  started: str, resumed: bool = False) -> None:
        """Persist the config snapshot (not on resume), versions, trace and assessment record. On resume the artifacts get id ``0-resumed`` because the first exported artifacts are immutable."""
        sink, mode = self.ctx.sink, self.ctx.mode
        aid = lambda default: "0-resumed" if resumed else default   # noqa: E731  sorts first: readers take ids[0]
        if out.status == "FAILED":
            sink.put(trace_id, "unit_error", aid("error"), {"error": out.error, "steps": out.steps})
            refs["unit_error"] = ref("unit_error", aid("error"))
        if not resumed:
            sink.put(trace_id, "config_snapshot", "snapshot", config_snapshot(self.ctx))
            refs["config_snapshot"] = ref("config_snapshot", "snapshot")
        vers = collect_versions(self.ctx, sink, trace_id, refs)
        vers.update(versions or {})
        vers.update({"mode": mode, "executor": executor.label, "executor_note": executor.note, "template_id": template_id,
                     "source": source or {}, "decision": out.decision, "status": out.status,
                     "assessment_status": out.status, "validation_status": out.validation_status,
                     "pending_human_tasks": out.pending_human_tasks,
                     "app_model_sha256": sha256_hex(canonical_json(app_model)), "trace_id": trace_id})
        vers["stage_outputs"] = {f"{a.kind}/{a.id}": a.sha256 for a in sink.list(trace_id)
                                 if a.kind not in ("versions", "trace")}
        sink.put(trace_id, "versions", aid("versions"), vers)
        refs["versions"] = ref("versions", aid("versions"))
        sink.put(trace_id, "trace", aid("steps"), {"steps": out.steps})
        refs["trace"] = ref("trace", aid("steps"))
        out.artifacts = refs
        record = {"trace_id": trace_id, "app_model_id": (source or {}).get("app_id"), "executor": executor.label,
                  "executor_note": executor.note, "mode": mode, "decision": out.decision, "status": out.status,
                  "assessment_status": out.status, "validation_status": out.validation_status,
                  "pending_human_tasks": out.pending_human_tasks, "error": out.error, "versions": vers, "source": source or {}, "artifacts": refs,
                  "started": started, "finished": datetime.now(timezone.utc).isoformat()}
        record = json.loads(json.dumps(record))
        sink.repo.save_assessment(record)
        if resumed:   # the first exported record (WAITING_FOR_HUMAN) is immutable; the final one is a second artifact
            sink.put(trace_id, "assessment_record", "0-resumed", record)

    # ---- human-in-the-loop: stop after facts, resume after the HumanTasks are decided (task 24.3) ------------
    def _blocks_on_human(self) -> bool:
        """True when the Decider policy asks to stop after fact extraction until human tasks are decided."""
        return bool(self.ctx.config.get("decider_policy", {}).get("block_on_pending_human"))

    def _persist_waiting(self, trace_id: str, out: AssessmentOutcome, refs: dict[str, str], template_id: Optional[str],
                         source: Optional[dict[str, Any]], versions: Optional[dict[str, Any]], started: str,
                         executor: Any) -> None:
        """Save the framework execution and resume state needed by ``resume`` when the run stops for human review."""
        wf = WorkflowRef(executor=executor.label, development_only=True) if executor.label in ("Direct_Adapter", "Fluxnova") else None
        fx = FrameworkExecution(execution_id=trace_id, framework="governance_execution", trace_id=trace_id, workflow=wf).start()
        for s in out.steps:
            fx = fx.step(ExecutionStep(name=s["step"], status="OK" if s.get("status") == "OK" else "ERROR",
                                       output_ids=list(s.get("outputs") or []), error=s.get("error")))
        fx = fx.wait(out.pending_human_tasks[0])
        sink = self.ctx.sink
        sink.put(trace_id, "framework_execution", "state", json.loads(fx.model_dump_json()))
        sink.put(trace_id, "resume_state", "state", {
            "refs": dict(refs), "steps": out.steps, "template_id": template_id, "source": source or {},
            "versions": versions or {}, "started": started, "mode": self.ctx.mode, "pending": list(out.pending_human_tasks)})

    def resume(self, trace_id: str, *, executor: Any = None, store: Any = None) -> AssessmentOutcome:
        """Continue a WAITING_FOR_HUMAN assessment once its HumanTasks are decided. Works from persisted files only."""
        from agip_shared.humantasks import HumanTaskStore
        if executor is None:
            from .direct_adapter import DirectAdapter
            executor = DirectAdapter()
        sink = self.ctx.sink
        for a in sink.files.list(trace_id):    # a new process starts with an empty repository index
            sink.repo.record_artifact(a)
        try:
            state = sink.files.get(trace_id, "resume_state", "state")
            fx = FrameworkExecution.model_validate(sink.files.get(trace_id, "framework_execution", "state"))
        except (KeyError, FileNotFoundError) as exc:
            raise ResumeError(f"{trace_id}: no waiting assessment to resume") from exc
        if any(a.kind == "framework_execution" and a.id == "0-resumed" for a in sink.files.list(trace_id)):
            raise ResumeError(f"{trace_id}: already resumed")
        store = store or HumanTaskStore(sink.files.data_dir)
        refs: dict[str, str] = dict(state["refs"])
        out = AssessmentOutcome(trace_id, "WAITING_FOR_HUMAN", None, executor.label, self.ctx.mode,
                                artifacts=refs, steps=list(state["steps"]), validation_status="VALID")
        tasks = [store.get(t) for t in state["pending"]]
        open_ids = [t.task_id for t in tasks if t.status not in ("COMPLETED", "REJECTED", "CANCELLED")]
        if open_ids:
            out.pending_human_tasks = open_ids
            return out
        fs = FactSet.model_validate(sink.files.get(trace_id, "facts", "result"))
        fs = apply_human_outcomes(fs, tasks, store, self.ctx.config["taxonomy"], trace_id)
        sink.put(trace_id, "facts", "0-resolved", json.loads(fs.model_dump_json()))
        refs["facts"] = ref("facts", "0-resolved")
        app_model = sink.files.get(trace_id, "app_model", "app")
        fx = fx.resume()
        with self.tracing.assessment("assessment-resume", mode=self.ctx.mode, executor=executor.label):
            ok, err = executor.execute(self, GOVERNANCE_STEPS[1:], trace_id, refs, out.steps)
        done = {s["step"] for s in out.steps}
        for s in out.steps:
            if s["step"] not in {x.name for x in fx.steps}:
                fx = fx.step(ExecutionStep(name=s["step"], status="OK" if s.get("status") == "OK" else "ERROR",
                                           output_ids=list(s.get("outputs") or []), error=s.get("error")))
        if ok:
            out.decision = sink.get(trace_id, "decision", "result")["decision"]
            out.status, out.pending_human_tasks = "COMPLETED", []
            fx = fx.complete()
        else:
            out.status, out.error, out.pending_human_tasks = "FAILED", err, []
            fx = fx.fail(err or "failed")
        sink.put(trace_id, "framework_execution", "0-resumed", json.loads(fx.model_dump_json()))
        self._finalize(trace_id, out, refs, executor, app_model, state["source"], dict(state["versions"], resumed_from="WAITING_FOR_HUMAN",
                       resolved_human_tasks=[t.task_id for t in tasks]), state["template_id"], state["started"], resumed=True)
        return out


class ResumeError(Exception):
    """Raised when an assessment cannot be resumed: nothing waiting, or already resumed."""
    pass


def apply_human_outcomes(fs: FactSet, tasks: list[Any], store: Any, taxonomy: dict[str, Any], trace_id: str) -> FactSet:
    """COMPLETED review with a valid taxonomy value -> accepted classification (human provenance); otherwise UNMAPPED stays."""
    by_key = {(t.context.get("element_id"), t.context.get("attribute")): t for t in tasks}
    facts, accepted = [], list(fs.accepted_classifications)
    for f in fs.facts:
        t = by_key.get((f.element_id, f.attribute))
        if t is None or f.mapping_status != "UNMAPPED":
            facts.append(f)
            continue
        done = [o for o in store.outcomes(t.task_id) if o.resulting_state == "COMPLETED"]
        choices = sorted(set(((taxonomy.get("attributes") or {}).get(f.attribute) or {}).get("values", {}).values()))
        value = done[-1].outcome_artifact_id if done else None
        if t.status == "COMPLETED" and done and value in choices:
            o = done[-1]
            fid = f"{f.element_id}.{f.attribute}"
            accepted.append(AcceptedClassification(
                fact_id=fid, original_raw=f.raw, normalized=value, question_type="choice", model=f"human:{o.actor}",
                input_hash=t.context.get("input_hash") or "human", answer={"choice": value}, policy_version="human_review",
                timestamp=o.timestamp,
                provenance={"trace_id": trace_id, "reviewer": o.actor, "role": o.role, "rationale": o.rationale,
                            "task_id": t.task_id, "source": "human_reviewer", "json_path": f.json_path,
                            "element_id": f.element_id, "attribute": f.attribute}))
            facts.append(f.model_copy(update={"decider_label": value, "decider_outcome": "HUMAN_ACCEPTED", "mapping_status": "INFERRED",
                                              "normalized": value, "extraction_method": "human_review", "classification_ref": fid}))
        else:
            facts.append(f.model_copy(update={"decider_outcome": "HUMAN_REJECTED"}))
    return fs.model_copy(update={"facts": facts, "accepted_classifications": accepted, "pending_human_tasks": []})

def _pending_tasks(sink: ArtifactSink, trace_id: str) -> list[str]:
    """Human task ids recorded in the facts artifact; empty when no facts artifact exists."""
    try:
        return list(sink.get(trace_id, "facts", "result").get("pending_human_tasks") or [])
    except Exception:  # noqa: BLE001  (no facts artifact)
        return []


CONFIG_KEYS = ("controls", "risks", "taxonomy", "gap_rule", "scoring", "gates", "matrix", "decider_policy")


def _ruleset_path(ctx: UnitContext, lane: str) -> Path:
    """Path of the lane's ruleset: the context override if set, else the default file in RULESET_DIR."""
    return Path(ctx.rulesets.get(lane) or rulesets.RULESET_DIR / f"{lane}.spectral.yaml")


def config_snapshot(ctx: UnitContext) -> dict[str, Any]:
    """Frozen copy of the catalogs, scoring profile, taxonomy, policies and ruleset files used by this run.
    Replay reads this instead of the live files."""
    cfg = {k: ctx.config[k] for k in CONFIG_KEYS if k in ctx.config}
    # YAML text keeps non-string keys (e.g. integer scoring levels) that JSON would turn into strings.
    return {"config_yaml": yaml.safe_dump(cfg, sort_keys=True), "rulesets": {lane: _ruleset_path(ctx, lane).read_bytes().decode("utf-8") for lane in ("controls", "risks")}}


def collect_versions(ctx: UnitContext, sink: ArtifactSink, trace_id: str, refs: dict[str, str]) -> dict[str, Any]:
    """Every versioned input of the assessment (Req 6.6, 23.4)."""
    from ..units import decision_remediation
    cfg = ctx.config
    v: dict[str, Any] = {
        "rulesets": {lane: rulesets.ruleset_info(_ruleset_path(ctx, lane)) for lane in ("controls", "risks")},
        "catalogs": {"controls": cfg["controls"].get("version"), "risks": cfg["risks"].get("version")},
        "scoring_profile": cfg["scoring"].get("version"), "gap_rule": cfg["gap_rule"].get("version"),
        "gates": cfg["gates"].get("version"), "decision_matrix": cfg["matrix"].get("version"),
        "taxonomy": cfg["taxonomy"].get("version"), "decider_policy": cfg["decider_policy"].get("version"),
        "prompts": {"extraction": rulesets.extraction_prompt_version(), "remediation": decision_remediation.PROMPT_VERSION},
        "config_sha256": {k: sha256_hex(canonical_json(cfg[k])) for k in CONFIG_KEYS if k in cfg},
        "framework_versions": _framework_versions(),
        "input_artifacts": {k: {"ref": refs[k], "sha256": _art_hash(sink, trace_id, refs[k])} for k in ("app_model",) if k in refs},
        "model": {"provider": getattr(ctx.gateway, "provider", None), "model": getattr(ctx.gateway, "model", None)},
        "decider": {"provider": getattr(ctx.decider, "provider", None), "model": getattr(ctx.decider, "model", None)},
    }
    if "calm_validation" in refs:
        v["calm_cli"] = sink.get(trace_id, "calm_validation", "result").get("calm_cli_version")
    if "spectral_controls_parsed" in refs:
        v["spectral_cli"] = sink.get(trace_id, "spectral_controls_parsed", "run").get("version")
    v["evaluators"] = {"calm": v.get("calm_cli"), "spectral": v.get("spectral_cli")}
    return v

def _art_hash(sink: ArtifactSink, trace_id: str, reference: str) -> Optional[str]:
    """SHA-256 of the artifact behind ``kind:id`` reference, or None if it is not in the repository."""
    kind, _, aid = reference.partition(":")
    rec = sink.repo.get_artifact(trace_id, kind, aid)
    return rec.sha256 if rec else None


def _framework_versions() -> dict[str, Optional[str]]:
    """Installed version of each framework distribution, or None when it is not installed."""
    from importlib import metadata
    out: dict[str, Optional[str]] = {}
    for dist in ("governance-execution-framework", "rule-authoring-framework", "calm-app-generation-framework", "agip-shared"):
        try:
            out[dist] = metadata.version(dist)
        except metadata.PackageNotFoundError:
            out[dist] = None
    return out
