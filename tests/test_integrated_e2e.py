"""Task 26.5: the 13-step integrated journey in a tmp workspace (repo files are never modified).

 1 ingest   2 extract   3 approve (risk confirm)   4 compile   5 approve patterns   6 publish RA03-LITE
 7 instantiate V1   8 assess V1-V4 (golden expectations)   9 accept a classification   10 evaluate controls/risks
11 decide   12 complete a human task and resume   13 inspect execution and lineage, then replay

Offline: LLM from recordings, Decider from fixtures (or a stub), CALM and Spectral from the recorded CLI outputs.
Steps 1-3 need the ../ai-governance-framework and ../common-cloud-controls checkouts and are skipped without them.
"""
import copy
import importlib.util
import json
import shutil
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from agip_shared.contracts import FactSet
from agip_shared.hashing import canonical_json, sha256_hex
from agip_shared.humantasks import HumanTaskStore, NotAuthorized
from agip_shared.settings import Settings
from calm_generation import cli as cg_cli, lifecycle as lc
from governance_execution.adapters.decider import DeciderGateway
from governance_execution.core import catalogs as gcatalogs
from governance_execution.dashboard import data as dash_data
from governance_execution.dashboard.app import create_app
from governance_execution.dashboard.data import ReportStore
from governance_execution.exec import factory
from governance_execution.obs.replay import replay
from governance_execution.store.repository import MemoryRepository
from governance_execution.units.calm_builder import instantiate, load_template
from rule_authoring import approval as ap, compile as cp, extraction as ex, ingest as ing
from rule_authoring.paths import FRAMEWORK_ROOT as RA

PLATFORM = RA.parent
ROOT = PLATFORM.parent
AIGF, CCC = ROOT / "ai-governance-framework", ROOT / "common-cloud-controls"
CG = PLATFORM / "calm-app-generation-framework"
GE = PLATFORM / "governance-execution-framework"
VARIANTS = CG / "fixtures" / "variants"
EXPECTED = yaml.safe_load((VARIANTS / "expected.yaml").read_text(encoding="utf-8"))
SETTINGS = Settings(_env_file=None, decider_provider="fixture", model_provider="replay")
TPL, TEXT = load_template("RA03-LITE")
HAVE_SOURCES = (AIGF / "docs").is_dir() and (CCC / "catalogs").is_dir()
REVIEW = ("--by", "dana", "--role", "architect", "--rationale", "reviewed")

_spec = importlib.util.spec_from_file_location("cg_test_cli_helpers", CG / "tests" / "test_cli.py")
cg_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cg_helpers)       # StubCalm, completed_form, write_form (calm generate/validate stub)


def _form(v):
    return yaml.safe_load((GE / "forms" / f"{v}.attributes.yaml").read_text(encoding="utf-8"))


def _dump(path, doc):
    path.write_bytes(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True).encode("utf-8"))


def _runtime(data, catalogs, rulesets, repo=None, mode="normal"):
    """Coordinator + executor bound to the workspace catalogs and compiled rulesets (frozen, like the governance CLI)."""
    coord, ex_ = factory.build(mode, settings=SETTINGS, repo=repo or MemoryRepository(data), data_dir=data, cli="replay")
    coord.ctx.config = {**coord.ctx.config, "controls": gcatalogs.load("controls", catalogs), "risks": gcatalogs.load("risks", catalogs)}
    coord.ctx.rulesets = {lane: Path(rulesets) / f"{lane}.spectral.yaml" for lane in ("controls", "risks")}
    return coord, ex_


def _low_confidence(url, body, timeout):
    q = body["questions"][0]
    c = q["choices"]
    return {"model": "m", "answers": [{"choice": c[0], "confidence": 0.3, "probabilities": {c[0]: 0.4, c[1]: 0.35}}]}


def _human_runtime(data, catalogs, rulesets, repo):
    coord, ex_ = _runtime(data, catalogs, rulesets, repo=repo, mode="no-llm")
    policy = copy.deepcopy(coord.ctx.config["decider_policy"])
    policy["tasks"]["classify_attribute"]["on_fail"] = "HUMAN_REVIEW"
    policy["block_on_pending_human"] = True
    coord.ctx.config["decider_policy"] = policy
    coord.ctx.decider = DeciderGateway(policy, "http", "http://decider.invalid", "m", 1, data, _low_confidence)
    return coord, ex_


def _assess(coord, ex_, v, template_status="PUBLISHED"):
    f = _form(v)
    r = instantiate(f, template=TPL, template_text=TEXT, template_status=template_status, calm=coord.ctx.calm)
    assert r.app_model is not None, r.errors
    return r, coord.run(r.app_model, executor=ex_, template_id="RA03-LITE", source={"app_id": f["app"]["id"]})


def _art(coord, out, kind, aid="result"):
    return coord.ctx.sink.get(out.trace_id, kind, aid)


def test_integrated_journey(tmp_path, capsys):
    ws = tmp_path / "ws"
    cats, base_cats = ws / "catalogs", ws / "catalogs-approved"
    for d in (cats, base_cats):
        d.mkdir(parents=True)
        for n in ("controls", "risks"):                      # copies; repo catalogs are never modified
            shutil.copy(RA / "catalogs" / f"{n}.catalog.yaml", d)
    data = ws / "data"
    repo = MemoryRepository(data)

    # ---- 1-3 ingest, extract, approve (needs the AIGF and CCC checkouts)
    if HAVE_SOURCES:
        srcs, drafts = cats / "sources", cats / "drafts"
        for name, src in (("aigf", AIGF), ("ccc", CCC)):
            assert ing.main(["--source", name, "--path", str(src), "--out", str(srcs / f"{name}.json")]) == 0   # 1 ingest
            assert (srcs / f"{name}.json").is_file() and not drafts.exists()
        for name, src in (("aigf", AIGF), ("ccc", CCC)):
            ing.main(["--source", name, "--path", str(src), "--out", str(srcs / f"{name}.json"), "--extract",
                      "--provider", "replay", "--recordings", str(RA / "fixtures" / "recordings" / "llm"),
                      "--drafts", str(drafts)])                                                                  # 2 extract
        cn01 = json.loads((drafts / "CCC.Core.CN01.json").read_text(encoding="utf-8"))
        assert cn01["status"] == "DRAFT" and cn01["body"]["extraction"]["inexpressible_reason"]
        ctl = ex.to_catalog_entry(json.loads((drafts / "CCC.Core.CN02.json").read_text(encoding="utf-8")))
        risk = ex.to_catalog_entry(json.loads((drafts / "CCC.Core.TH01.json").read_text(encoding="utf-8")))
        cpath, rpath = cats / "controls.catalog.yaml", cats / "risks.catalog.yaml"
        for e, path in ((ctl, cpath), (risk, rpath)):
            e["references"] = [dict(zip(("framework", "id"), r.split(":", 1))) for r in e["references"]]
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            doc["items"].append(e)
            _dump(path, doc)
        ap.transition_in_catalog(cpath, "CCC.Core.CN02", "IN_REVIEW", "alice", "reviewer", "checked")          # 3 approve
        ap.transition_in_catalog(cpath, "CCC.Core.CN02", "APPROVED", "bob", "approver", "ok")
        ap.transition_in_catalog(rpath, "CCC.Core.TH01", "IN_REVIEW", "alice", "reviewer", "checked")
        with pytest.raises(ap.ApprovalError, match="confirm"):
            ap.transition_in_catalog(rpath, "CCC.Core.TH01", "APPROVED", "bob", "approver", "ok")
        ap.confirm_in_catalog(rpath, "CCC.Core.TH01", "bob", "approver", "scores reviewed")
        ap.transition_in_catalog(rpath, "CCC.Core.TH01", "APPROVED", "bob", "approver", "ok")

    # ---- 4 compile: new approved items appear; the approved baseline compiles to the repo's rulesets, byte for byte
    rs_base = ws / "rulesets"
    cp.compile_all(base_cats, rs_base)
    for f in ("controls.spectral.yaml", "risks.spectral.yaml", "MANIFEST.yaml"):
        assert (rs_base / f).read_bytes() == (RA / "rulesets" / f).read_bytes()
    if HAVE_SOURCES:
        rs_ext, rs_ext2 = ws / "rulesets-ext", ws / "rulesets-ext2"
        cp.compile_all(cats, rs_ext)
        cp.compile_all(cats, rs_ext2)
        assert (rs_ext / "controls.spectral.yaml").read_bytes() == (rs_ext2 / "controls.spectral.yaml").read_bytes()
        assert ctl["configurations"][0]["rule_codes"][0] in yaml.safe_load((rs_ext / "controls.spectral.yaml").read_text(encoding="utf-8"))["rules"]
        assert risk["rule_codes"][0] in yaml.safe_load((rs_ext / "risks.spectral.yaml").read_text(encoding="utf-8"))["rules"]

    # ---- 5 approve patterns (calm_generation lifecycle on a copy of the registry), 6 publish RA03-LITE
    reg = ws / "lifecycle.yaml"
    shutil.copy(lc.REGISTRY, reg)
    entries = lc.load(reg)["entries"]
    pattern_ids = sorted(k for k, e in entries.items() if e["kind"] == "pattern")
    assert len(pattern_ids) == 8
    for key in (*pattern_ids, "RA03-LITE"):
        cg_helpers.set_state(str(reg), key, "DRAFT")
    for key in pattern_ids:                                                                                      # 5
        for step in ("submit", "approve", "publish"):
            assert cg_helpers.run(str(reg), step, key, *REVIEW) == 0, (key, step)
    assert cg_helpers.run(str(reg), "form", "RA03-LITE") == 1                 # no form until the template is PUBLISHED
    for step in ("submit", "approve", "publish"):                                                                # 6
        assert cg_helpers.run(str(reg), step, "RA03-LITE", *REVIEW) == 0
    final = lc.load(reg)["entries"]
    assert all(final[k]["state"] == "PUBLISHED" for k in (*pattern_ids, "RA03-LITE"))
    assert [h["to"] for h in final["P13"]["history"]][-3:] == ["IN_REVIEW", "APPROVED", "PUBLISHED"]
    capsys.readouterr()

    # ---- 7 instantiate V1: the CALM Generation CLI (stubbed `calm`), then the governance builder from recorded CLI output
    form_file = cg_helpers.write_form(ws, cg_helpers.completed_form(), "v1-form.yaml")
    out_file = ws / "v1-cli.json"
    assert cg_helpers.run(str(reg), "instantiate", "--form", form_file, "--out", str(out_file), calm=cg_helpers.StubCalm()) == 0
    assert "sha256=" in capsys.readouterr().out and out_file.is_file()
    coord, ex_ = _runtime(data, base_cats, rs_base, repo=repo)
    inst = instantiate(_form("v1"), template=TPL, template_text=TEXT, template_status="PUBLISHED", calm=coord.ctx.calm,
                       sink=coord.ctx.sink, trace_id="gen-v1")
    assert inst.status == EXPECTED["v1"]["calm"]
    assert inst.app_model == json.loads((VARIANTS / "invoice-lite-v1.json").read_text(encoding="utf-8"))
    assert inst.manifest["output_sha256"] == sha256_hex(canonical_json(inst.app_model))

    # ---- 8-11 assess V1-V4 and re-assert the golden expectations (facts, evaluation, decision)
    outs = {}
    for v in ("v1", "v2", "v3", "v4"):
        coord, ex_ = _runtime(data, base_cats, rs_base, repo=repo)
        r, out = _assess(coord, ex_, v)
        exp = EXPECTED[v]
        outs[v] = (coord, ex_, out)
        assert r.status == exp["calm"] and out.validation_status == exp["calm"] and out.status == exp["status"]
        assert out.decision == exp["decision"] and out.executor == "Direct_Adapter"
        assert r.app_model == json.loads((VARIANTS / f"{_form(v)['app']['id']}.json").read_text(encoding="utf-8"))
        if v == "v4":                                                                       # invalid CALM: BLOCKED, no decision
            assert "decision" not in out.artifacts and "spectral_controls_parsed" not in out.artifacts
            assert exp["calm_error_path"] in json.dumps(_art(coord, out, "calm_validation"))
            continue
        gap, prof, d = _art(coord, out, "control_gap"), _art(coord, out, "risk_profile"), _art(coord, out, "decision")  # 10, 11
        assert sorted(c["control_id"] for c in gap["controls"] if c["status"] == "FAIL") == exp["failed_controls"]
        assert sorted(x["risk_id"] for x in prof["risks"]) == exp["triggered_risks"]
        if "gap_level" in exp:
            assert gap["gap_level"] == exp["gap_level"] and prof["profile_level"] == exp["profile_level"]
        if "gate" in exp:
            assert [g["id"] for g in d["gates_evaluated"] if g["fired"]][0] == exp["gate"]
        assert d["decision"] == exp["decision"] and prof["label"] == "illustrative, not approved policy"
        assert all(c["evidence"] == "design-level evidence only" for c in gap["controls"] if c["status"] == "PASS")
        vers = _art(coord, out, "versions", "versions")
        assert vers["rulesets"]["controls"]["sha256"] == yaml.safe_load((rs_base / "MANIFEST.yaml").read_text(encoding="utf-8"))["rulesets"]["controls.spectral.yaml"]["sha256"]

    # ---- 9 accepted classification: the Decider fixture answer is accepted by policy and the fact becomes INFERRED
    coord, _, v1 = outs["v1"]
    fs = FactSet.model_validate(_art(coord, v1, "facts"))
    cls_fact = next(f for f in fs.facts if f.attribute == "data_classification")
    assert cls_fact.mapping_status == "INFERRED" and cls_fact.classification_ref
    assert any(c.fact_id == cls_fact.classification_ref for c in fs.accepted_classifications)
    assert sorted(f"{f.element_id}.{f.attribute}" for f in fs.facts if f.mapping_status == "INFERRED") == ["invoice-db.data_classification"]

    # ---- 12 human task, block_on_pending_human: WAITING_FOR_HUMAN -> act via HumanTaskStore -> resume -> decision
    hcoord, hex_ = _human_runtime(data, base_cats, rs_base, repo)
    r = instantiate(_form("v1"), template=TPL, template_text=TEXT, template_status="PUBLISHED", calm=hcoord.ctx.calm)
    waiting = hcoord.run(r.app_model, executor=hex_, template_id="RA03-LITE", source={"app_id": "v1-human"})
    assert waiting.status == "WAITING_FOR_HUMAN" and waiting.decision is None and waiting.pending_human_tasks
    tid = waiting.pending_human_tasks[0]
    store = HumanTaskStore(data)
    task = store.get(tid)
    assert task.status == "OPEN" and task.trace_id == waiting.trace_id
    with pytest.raises(NotAuthorized):
        store.act(tid, "mallory", "developer", "CLAIM", "no")
    store.act(tid, "alice", "risk_analyst", "CLAIM", "taking it")
    value = task.context["allowed_values"][0]
    store.act(tid, "alice", "risk_analyst", "COMPLETE", "classified by hand", outcome_artifact_id=value)
    hcoord2, hex2 = _human_runtime(data, base_cats, rs_base, repo)                  # new coordinator, as after a restart
    done = hcoord2.resume(waiting.trace_id, executor=hex2)
    assert done.status == "COMPLETED" and done.decision == EXPECTED["v1"]["decision"]
    hfs = FactSet.model_validate(hcoord2.ctx.sink.files.get(waiting.trace_id, "facts", "0-resolved"))
    hf = next(f for f in hfs.facts if f.attribute == "data_classification")
    assert hf.mapping_status == "INFERRED" and hf.normalized == value

    # ---- 13 inspect execution and lineage, then replay
    s = ReportStore(data)
    for v in ("v1", "v2", "v3", "v4"):
        g = dash_data.graph(s.bundle(outs[v][2].trace_id))
        assert "decision" in g.nodes and g.nodes["decision"]["kind"] == "decision"
    g2 = dash_data.graph(s.bundle(outs["v2"][2].trace_id))
    assert {"control:AIGF-MI-024", "risk:AIGF-RI-024"} <= set(g2.nodes)
    client = TestClient(create_app(SETTINGS, data))
    for trace in (outs["v1"][2].trace_id, outs["v2"][2].trace_id, outs["v4"][2].trace_id, waiting.trace_id):
        resp = client.get(f"/assessments/{trace}/execution")
        assert resp.status_code == 200, (trace, resp.status_code)
    assert "validate_calm" in client.get(f"/assessments/{outs['v2'][2].trace_id}/execution").text
    assert client.get("/lineage/source/AIGF:mi-24").status_code == 200
    for v in ("v1", "v2", "v3", "v4"):
        coord, _, out = outs[v]
        rcoord, rex = _runtime(data, base_cats, rs_base, repo=repo, mode="replay")
        report = replay(out.trace_id, rcoord, rex)
        assert report.replay_trace != out.trace_id and report.identical, report.differences
        assert report.decision_replay == EXPECTED[v]["decision"]
