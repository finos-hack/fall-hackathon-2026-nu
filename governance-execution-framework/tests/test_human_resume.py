"""Task 24.3: Decider HUMAN_REVIEW creates a real HumanTask; the assessment stops after facts (WAITING_FOR_HUMAN)
and resumes after the task is decided, also in a new process (new coordinator, new store, empty repository)."""
import copy
import json
from pathlib import Path

import pytest
import yaml

from agip_shared.contracts import FactSet
from agip_shared.humantasks import HumanTaskStore, NotAuthorized
from agip_shared.settings import Settings
from governance_execution import cli
from governance_execution.adapters.decider import DeciderGateway
from governance_execution.exec import factory
from governance_execution.exec.coordinator import ResumeError
from governance_execution.store.repository import MemoryRepository
from governance_execution.units.calm_builder import instantiate, load_template

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = Settings(_env_file=None, decider_provider="fixture", model_provider="replay")
TPL, TEXT = load_template("RA03-LITE")
FORM = yaml.safe_load((ROOT / "governance-execution-framework" / "forms" / "v1.attributes.yaml").read_text(encoding="utf-8"))


def _low_confidence(url, body, timeout):
    q = body["questions"][0]
    c = q["choices"]
    return {"model": "m", "answers": [{"choice": c[0], "confidence": 0.3, "probabilities": {c[0]: 0.4, c[1]: 0.35}}]}


def _build(data_dir):
    coord, ex = factory.build("no-llm", settings=SETTINGS, repo=MemoryRepository(data_dir), data_dir=data_dir, cli="replay")
    cfg = coord.ctx.config
    policy = copy.deepcopy(cfg["decider_policy"])
    policy["tasks"]["classify_attribute"]["on_fail"] = "HUMAN_REVIEW"
    policy["block_on_pending_human"] = True
    cfg["decider_policy"] = policy
    coord.ctx.decider = DeciderGateway(policy, "http", "http://decider.invalid", "m", 1, data_dir, _low_confidence)
    return coord, ex


def _start(data_dir):
    coord, ex = _build(data_dir)
    r = instantiate(FORM, template=TPL, template_text=TEXT, template_status="PUBLISHED", calm=coord.ctx.calm)
    assert r.app_model is not None
    return coord.run(r.app_model, executor=ex, template_id="RA03-LITE", source={"app_id": "v1"})


def _classification(coord, out):
    fs = FactSet.model_validate(coord.ctx.sink.files.get(out.trace_id, "facts", "0-resolved"))
    return next(f for f in fs.facts if f.attribute == "data_classification"), fs


def test_waiting_task_created_and_resume_after_restart_gets_decision(tmp_path):
    out = _start(tmp_path)
    assert out.status == "WAITING_FOR_HUMAN" and out.decision is None and out.pending_human_tasks
    assert [s["step"] for s in out.steps] == ["validate_calm", "extract_facts"]
    tid = out.pending_human_tasks[0]
    store = HumanTaskStore(tmp_path)                       # restart: nothing is shared with the first run
    task = store.get(tid)
    assert task.task_type == "DECIDER_CLASSIFICATION_REVIEW" and task.status == "OPEN" and task.trace_id == out.trace_id

    coord2, ex2 = _build(tmp_path)                          # NEW coordinator + repository
    still = coord2.resume(out.trace_id, executor=ex2)       # not decided yet: stays waiting
    assert still.status == "WAITING_FOR_HUMAN" and still.pending_human_tasks == [tid]

    with pytest.raises(NotAuthorized):
        store.act(tid, "mallory", "developer", "CLAIM", "no")
    store.act(tid, "alice", "risk_analyst", "CLAIM", "taking it")
    value = task.context["allowed_values"][0]
    store.act(tid, "alice", "risk_analyst", "COMPLETE", "classified by hand", outcome_artifact_id=value)

    done = coord2.resume(out.trace_id, executor=ex2)
    assert done.status == "COMPLETED" and done.decision
    f, fs = _classification(coord2, done)
    assert f.mapping_status == "INFERRED" and f.normalized == value and f.raw == "supplier-financial"
    cls = next(c for c in fs.accepted_classifications if c.fact_id == f.classification_ref)
    assert cls.provenance["reviewer"] == "alice" and cls.provenance["source"] == "human_reviewer"
    with pytest.raises(ResumeError):
        coord2.resume(out.trace_id, executor=ex2)           # already resumed
    fx = coord2.ctx.sink.files.get(out.trace_id, "framework_execution", "0-resumed")
    assert fx["status"] == "COMPLETED" and fx["waiting_on"] is None
    assert coord2.ctx.sink.repo.get_assessment(out.trace_id)["status"] == "COMPLETED"


def test_rejected_task_keeps_fact_unmapped_and_still_decides(tmp_path):
    out = _start(tmp_path)
    tid = out.pending_human_tasks[0]
    store = HumanTaskStore(tmp_path)
    store.act(tid, "alice", "risk_analyst", "CLAIM", "x")
    store.act(tid, "alice", "risk_analyst", "REJECT", "cannot tell")
    coord2, ex2 = _build(tmp_path)
    done = coord2.resume(out.trace_id, executor=ex2)
    f, _ = _classification(coord2, done)
    assert done.status == "COMPLETED" and f.mapping_status == "UNMAPPED" and f.normalized is None


def test_cli_resume(tmp_path, capsys):
    out = _start(tmp_path)
    store = HumanTaskStore(tmp_path)
    tid = out.pending_human_tasks[0]
    store.act(tid, "alice", "risk_analyst", "CLAIM", "x")
    store.act(tid, "alice", "risk_analyst", "REJECT", "no")

    def builder(mode, **kw):
        return _build(Path(kw["data_dir"]))

    code = cli.main(["resume", out.trace_id, "--data-dir", str(tmp_path), "--cli", "replay"], builder=builder)
    res = json.loads(capsys.readouterr().out)
    assert code == 0 and res["assessment_status"] == "COMPLETED" and res["decision"]
