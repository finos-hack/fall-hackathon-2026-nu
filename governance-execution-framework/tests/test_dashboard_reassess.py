"""Re-assess flow: eligibility, upload of a corrected model, run linking, and removal of the Replay buttons."""
import json

import pytest
from fastapi.testclient import TestClient

from governance_execution.dashboard.data import reassessable
from pathlib import Path

import yaml

from agip_shared.settings import Settings
from governance_execution.dashboard.app import create_app
from governance_execution.exec import factory
from governance_execution.units.calm_builder import instantiate, load_template

ROOT = Path(__file__).resolve().parents[2]
FORMS = ROOT / "governance-execution-framework" / "forms"
SETTINGS = Settings(_env_file=None, decider_provider="fixture", model_provider="replay")


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    d = tmp_path_factory.mktemp("reassess")
    holder = {}

    def build(mode):
        return factory.build(mode, settings=SETTINGS, repo=holder["app"].state.sink.repo, data_dir=d, cli="replay")

    app = holder["app"] = create_app(SETTINGS, d, build=build)
    client = TestClient(app)
    tpl, text = load_template("RA03-LITE")
    form = yaml.safe_load((FORMS / "v2.attributes.yaml").read_text(encoding="utf-8"))
    coord, _ = build("no-llm")
    model = instantiate(form, template=tpl, template_text=text, template_status="PUBLISHED", calm=coord.ctx.calm).app_model
    ref = client.post("/api/upload", content=json.dumps(model)).json()["app_model_ref"]
    r = client.post("/api/assess", json={"app_model_ref": ref, "mode": "normal", "template_id": "RA03-LITE"})
    assert r.status_code == 200 and r.json()["status"] == "COMPLETED", r.text
    return client, app, r.json()["trace_id"]


@pytest.mark.parametrize("status,decision,expected", [
    ("BLOCKED", None, True), ("FAILED", None, True), ("COMPLETED", "REJECTED", True), ("COMPLETED", "RESTRICTED", True),
    ("COMPLETED", "INDETERMINATE", True), ("COMPLETED", "APPROVED_WITH_CONDITIONS", False),
    ("WAITING_FOR_HUMAN", None, False), (None, None, False)])
def test_reassessable(status, decision, expected):
    assert reassessable({"status": status, "decision": decision}) is expected


def _failed_run(app, trace="a1" * 16, status="BLOCKED", decision=None, template="RA03-LITE"):
    app.state.sink.put(trace, "versions", "v", {"assessment_status": status, "decision": decision, "source": {"app_id": "demo-app"},
                                                "template_id": template, "mode": "normal"})
    return trace


def test_successful_assessment_has_no_reassess_and_no_replay_button(env):
    client, app, _ = env
    ok = _failed_run(app, "c3" * 16, "COMPLETED", "APPROVED_WITH_CONDITIONS")
    for url in (f"/assessments/{ok}", f"/assessments/{ok}?partial=1"):
        html = client.get(url).text
        assert "Fix and re-assess" not in html and "/api/replay/" not in html
    assert client.get(f"/assessments/{ok}/reassess").status_code == 409
    assert client.post(f"/assessments/{ok}/reassess", content="{}").status_code == 409


def test_reassess_page_and_upload_links_runs(env):
    client, app, ok_trace = env
    model = app.state.reports.get(ok_trace, "app_model")
    bad = _failed_run(app)
    assert "Fix and re-assess" in client.get(f"/assessments/{bad}").text
    page = client.get(f"/assessments/{bad}/reassess")
    assert page.status_code == 200 and "Upload and re-assess" in page.text and ">replay<" not in page.text

    assert client.post(f"/assessments/{bad}/reassess?mode=replay", content=json.dumps(model)).status_code == 400
    assert client.post(f"/assessments/{bad}/reassess", content=json.dumps({"x": 1})).status_code == 422

    r = client.post(f"/assessments/{bad}/reassess?mode=normal", content=json.dumps(model))
    assert r.status_code == 200, r.text
    new = r.json()["trace_id"]
    assert new != bad and r.json()["report"] == f"/assessments/{new}"
    assert app.state.reports.summary(new)["supersedes"] == bad
    assert new in app.state.reports.superseded_by(bad)
    assert f"/assessments/{bad}" in client.get(f"/assessments/{new}").text          # "Re-assessment of" link
    assert new[:12] in client.get(f"/assessments/{bad}").text                       # "Re-assessed in" link
    assert app.state.reports.summary(bad)["status"] == "BLOCKED"                    # original untouched


def test_identical_model_is_rejected(env):
    client, app, ok_trace = env
    model = app.state.reports.get(ok_trace, "app_model")
    bad = _failed_run(app, "b2" * 16, "FAILED")
    app.state.sink.put(bad, "app_model", "upload", model)
    r = client.post(f"/assessments/{bad}/reassess?mode=normal", content=json.dumps(model))
    assert r.status_code == 422 and "identical" in r.json()["detail"]


def test_unknown_trace_is_404(env):
    client, _, _ = env
    assert client.get("/assessments/nope-trace/reassess").status_code == 404


