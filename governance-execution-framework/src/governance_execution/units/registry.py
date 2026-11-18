"""The five Units behind AgentTask/AgentResult (Req 21.1-21.3). Artifact IDs only cross the boundary.

An artifact reference is ``"<kind>:<id>"`` inside the task's trace. Each handler reads its inputs from the
ArtifactSink, writes its outputs, and returns their references. Handlers never raise: failures become
``AgentResult(status="ERROR")``. No runtime (Strands) types appear here.
"""
from __future__ import annotations

import json
import re
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from agip_shared.contracts import (AcceptedClassification, HumanTask, AgentResult, AgentTask, ControlGapAssessment, Decision, FactSet, RiskProfile,
                                   SpectralRun)
from agip_shared.gateway import ModelGateway, RecordingMissingError
from agip_shared.humantasks import HumanTaskStore, TaskExists

from ..adapters.decider import DeciderGateway, classify_unmapped
from ..core import catalogs, evidence as evidence_core, facts as facts_core, gap as gap_core, gates as gates_core, spectral_runs
from ..store.sink import ArtifactSink
from . import calm_builder, control_assessment, decision_remediation, risk_assessment


@dataclass
class UnitContext:
    """Dependencies shared by all unit handlers: artifact sink, CALM and Spectral runners, optional Decider and model gateway, run mode and loaded config."""
    sink: ArtifactSink
    calm: Any
    spectral: Any
    decider: Optional[DeciderGateway] = None
    gateway: Optional[ModelGateway] = None
    mode: str = "normal"
    config: dict[str, Any] = field(default_factory=dict)
    rulesets: dict[str, Any] = field(default_factory=dict)   # lane -> ruleset path override (replay uses frozen copies)

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        """Load the catalogs, taxonomy, gap rule, scoring profile, gates, decision matrix and Decider policy from their default files."""
        from ..core import acceptance, decision
        return {"controls": catalogs.load("controls"), "risks": catalogs.load("risks"),
                "taxonomy": facts_core.load_taxonomy(), "gap_rule": gap_core.load_gap_rule(),
                "scoring": risk_assessment.load_scoring(), "gates": gates_core.load_gates(),
                "matrix": decision.load_matrix(), "decider_policy": acceptance.load_policy()}


def ref(kind: str, artifact_id: str) -> str:
    """Format an artifact reference ``kind:id``."""
    return f"{kind}:{artifact_id}"


def _get(ctx: UnitContext, task: AgentTask, kind: str) -> Any:
    """Load the task's input artifact of ``kind``. Raises KeyError if the task lists none."""
    for r in task.artifact_ids:
        k, _, i = r.partition(":")
        if k == kind:
            return ctx.sink.get(task.trace_id, k, i)
    raise KeyError(f"task {task.task_id} has no input artifact of kind {kind}")


def _put(ctx: UnitContext, task: AgentTask, kind: str, content: Any, aid: str = "result") -> str:
    """Write an output artifact within the task's trace and return its reference."""
    ctx.sink.put(task.trace_id, kind, aid, content)
    return ref(kind, aid)


def _task_store(ctx: UnitContext) -> HumanTaskStore:
    """Human-task store shared across runs, rooted at the sink's data directory."""
    return HumanTaskStore(ctx.sink.files.data_dir)   # <data_dir>/human_tasks (shared service, server-side authorization)


def _allowed(ctx: UnitContext, attribute: str) -> list[str]:
    """Sorted distinct normalized values the taxonomy allows for ``attribute``."""
    return sorted(set(((ctx.config["taxonomy"].get("attributes") or {}).get(attribute) or {}).get("values", {}).values()))


def _dump(model: Any) -> Any:
    """Convert a pydantic model to plain JSON-compatible data."""
    return json.loads(model.model_dump_json())


# ---- Unit 1: Rule Authoring --------------------------------------------------------------------
def rule_authoring(task: AgentTask, ctx: UnitContext) -> list[str]:
    """Unit 1: report ruleset info for each lane (action ``ruleset_info`` only). Raises ValueError for other actions."""
    from rule_authoring import compile as cp
    if task.params.get("action") != "ruleset_info":
        raise ValueError(f"unsupported rule_authoring action {task.params.get('action')}")
    info = {lane: cp.ruleset_info(cp.RULESET_DIR / f"{lane}.spectral.yaml") for lane in spectral_runs.LANES}
    return [_put(ctx, task, "rulesets", info)]


# ---- Unit 2: CALM Builder ----------------------------------------------------------------------
def calm_builder_unit(task: AgentTask, ctx: UnitContext) -> list[str]:
    """Unit 2: validate the task's app_model with CALM (action ``validate`` only), adding correction guidance when INVALID. Raises ValueError for other actions."""
    if task.params.get("action") != "validate":
        raise ValueError(f"unsupported calm_builder action {task.params.get('action')}")
    app = _get(ctx, task, "app_model")
    tpl_id = task.params.get("template_id")
    tpl_dir = ctx.config.get("template_dir")   # set by an orchestrated run that composed its own template
    template = (calm_builder.load_template(tpl_id, Path(tpl_dir)) if tpl_dir else calm_builder.load_template(tpl_id))[0] if tpl_id else None
    v = ctx.calm.validate(app, template)
    out = calm_builder.validation_dict(v)
    out["pattern"] = tpl_id
    if v.status == "INVALID":
        out["guidance"] = calm_builder.guidance_for(v, task.params.get("form") or {})
    return [_put(ctx, task, "calm_validation", out)]


# ---- Unit 3: Control Assessment ----------------------------------------------------------------
def control_unit(task: AgentTask, ctx: UnitContext) -> list[str]:
    """Unit 3: action ``lint`` runs the controls Spectral ruleset; ``assess`` writes the control_gap and evidence artifacts. Raises ValueError for other actions."""
    action = task.params.get("action")
    if action == "lint":
        spectral_runs.run_one(ctx.spectral, _get(ctx, task, "app_model"), "controls", ctx.rulesets.get("controls"), sink=ctx.sink, trace_id=task.trace_id)
        return [ref("spectral_controls_raw", "run"), ref("spectral_controls_parsed", "run")]
    if action == "assess":
        run = SpectralRun.model_validate(_get(ctx, task, "spectral_controls_parsed"))
        g = control_assessment.assess(run, ctx.config["controls"], _get(ctx, task, "app_model"), ctx.config["gap_rule"])
        app = _get(ctx, task, "app_model")
        reqs = evidence_core.build_requirements(ctx.config["controls"])
        evid = evidence_core.build_evidence(reqs, run, str(app.get("name") or app.get("unique-id") or "app"))
        ev_ref = _put(ctx, task, "evidence", {"requirements": [_dump(r) for r in reqs], "evidence": [_dump(e) for e in evid]})
        return [_put(ctx, task, "control_gap", _dump(g.model_copy(update={"trace_id": task.trace_id}))), ev_ref]
    raise ValueError(f"unsupported control action {action}")


# ---- Unit 4: Risk Assessment -------------------------------------------------------------------
def risk_unit(task: AgentTask, ctx: UnitContext) -> list[str]:
    """Unit 4: action ``facts`` extracts facts (and, with a Decider, classifies unmapped ones, opening human review tasks); ``lint`` runs the risks ruleset; ``assess`` writes the risk_profile. Raises ValueError for other actions."""
    action = task.params.get("action")
    app = _get(ctx, task, "app_model")
    if action == "facts":
        fs = facts_core.extract(app, ctx.config["taxonomy"])
        audits: list[dict[str, Any]] = []
        if ctx.decider is not None:
            desc = {n.get("unique-id"): n.get("description", "") for n in app.get("nodes") or []}
            desc |= {f"{n.get('unique-id')}#type": n.get("node-type", "") for n in app.get("nodes") or []}
            checked = catalogs.checked_fields(ctx.config["controls"], ctx.config["risks"])
            new, audits = classify_unmapped(ctx.decider, fs.facts, ctx.config["taxonomy"], checked, desc, task.trace_id)
            if ctx.mode == "replay":
                missing = [a["input_hash"] for a in audits if a.get("error") == "fixture_missing"]
                if missing:
                    raise RecordingMissingError(f"missing Decider fixture {missing[0]}.json")
            accepted = [AcceptedClassification.model_validate(a["classification"]) for a in audits if a.get("classification")]
            pending = []
            for f in new:
                if f.decider_outcome == "HUMAN_REVIEW" and f.mapping_status == "UNMAPPED":
                    tid = re.sub(r"[^A-Za-z0-9_.-]", "_", f"decider-review-{task.trace_id[:8]}-{f.element_id}-{f.attribute}")
                    call = next((a for a in audits if a["question"].get("id") == f"{f.element_id}.{f.attribute}"), {})
                    ht = HumanTask(task_id=tid, framework="governance_execution", task_type="DECIDER_CLASSIFICATION_REVIEW",
                                   subject_refs=[f"facts:result#{f.element_id}.{f.attribute}"], trace_id=task.trace_id,
                                   role="risk_analyst", context={"element_id": f.element_id, "attribute": f.attribute, "raw": f.raw,
                                                                 "input_hash": call.get("input_hash"), "value_status": "PENDING",
                                                                 "trace_id": task.trace_id, "allowed_values": _allowed(ctx, f.attribute),
                                                                 "outcome_convention": "outcome_artifact_id carries the chosen value"})
                    _put(ctx, task, "human_task", _dump(ht), tid)
                    try:
                        _task_store(ctx).create(ht)
                    except TaskExists:
                        pass
                    pending.append(tid)
            fs = fs.model_copy(update={"facts": new, "accepted_classifications": accepted, "pending_human_tasks": pending})
        return [_put(ctx, task, "facts", _dump(fs)), _put(ctx, task, "decider_calls", audits)]
    if action == "lint":
        spectral_runs.run_one(ctx.spectral, app, "risks", ctx.rulesets.get("risks"), sink=ctx.sink, trace_id=task.trace_id)
        return [ref("spectral_risks_raw", "run"), ref("spectral_risks_parsed", "run")]
    if action == "assess":
        run = SpectralRun.model_validate(_get(ctx, task, "spectral_risks_parsed"))
        fs = FactSet.model_validate(_get(ctx, task, "facts"))
        p = risk_assessment.assess(run, ctx.config["risks"], fs, app, ctx.config["scoring"])
        return [_put(ctx, task, "risk_profile", _dump(p.model_copy(update={"trace_id": task.trace_id})))]
    raise ValueError(f"unsupported risk action {action}")


# ---- Unit 5: Decision & Remediation ------------------------------------------------------------
def decision_unit(task: AgentTask, ctx: UnitContext) -> list[str]:
    """Unit 5: action ``decide`` writes the decision; ``remediate`` writes the remediation. Raises ValueError for other actions."""
    action = task.params.get("action")
    calm = _get(ctx, task, "calm_validation")
    kinds = {r.partition(":")[0] for r in task.artifact_ids}
    gap = ControlGapAssessment.model_validate(_get(ctx, task, "control_gap")) if "control_gap" in kinds else None
    profile = RiskProfile.model_validate(_get(ctx, task, "risk_profile")) if "risk_profile" in kinds else None
    if action == "decide":
        d = decision_remediation.decide(calm["status"], gap, profile, ctx.config["gates"], ctx.config["matrix"])
        return [_put(ctx, task, "decision", _dump(d.model_copy(update={"trace_id": task.trace_id})))]
    if action == "remediate":
        d = Decision.model_validate(_get(ctx, task, "decision")) if "decision" in kinds else None   # none when CALM is invalid
        items = decision_remediation.collect(gap, profile, calm.get("guidance"))
        rem = decision_remediation.remediate(d, items, ctx.gateway, ctx.mode)
        return [_put(ctx, task, "remediation", rem)]
    raise ValueError(f"unsupported decision action {action}")


UNITS: dict[str, Callable[[AgentTask, UnitContext], list[str]]] = {
    "rule_authoring": rule_authoring,
    "calm_builder": calm_builder_unit,
    "control_assessment": control_unit,
    "risk_assessment": risk_unit,
    "decision_remediation": decision_unit,
}


def invoke(task: AgentTask, ctx: UnitContext) -> AgentResult:
    """The only way the Coordinator calls a Unit."""
    try:
        return AgentResult(task_id=task.task_id, status="OK", artifact_ids=UNITS[task.unit](task, ctx))
    except RecordingMissingError as exc:
        return AgentResult(task_id=task.task_id, status="ERROR", error=f"replay failed: {exc}")
    except Exception as exc:  # noqa: BLE001
        tb = traceback.format_exception_only(type(exc), exc)[-1].strip()
        return AgentResult(task_id=task.task_id, status="ERROR", error=tb[:500])
