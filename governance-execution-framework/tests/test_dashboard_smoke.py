"""Task 13.7 (20.2 C2): FastAPI TestClient smoke tests for the Dashboard. Offline (recorded CLI/LLM/Decider outputs)."""
import json
import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from agip_shared.settings import Settings
from governance_execution.dashboard.app import LABEL_SCORING, LABEL_SPECTRAL, create_app
from governance_execution.exec import factory
from governance_execution.units.calm_builder import instantiate, load_template

ROOT = Path(__file__).resolve().parents[2]
FORMS = ROOT / "governance-execution-framework" / "forms"
SETTINGS = Settings(_env_file=None, decider_provider="fixture", model_provider="replay")
EXTERNAL = re.compile(r"""(?:src|href)\s*=\s*["']\s*(?:https?:)?//|url\(\s*["']?\s*https?://|@import\s+["']?https?://""", re.I)
SKIP_ROUTES = ("/api/docs", "/api/openapi.json", "/docs/oauth2-redirect", "/redoc", "/static",
               "/overview", "/review", "/workbench", "/registry", "/source-registry", "/lineage", "/assessments/{trace}/execution")  # covered by test_dashboard_mvp.py


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    d = tmp_path_factory.mktemp("dash")
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


def urls(trace, app):
    kinds = app.state.reports.kinds(trace)
    return {
        "/": "/", "/assessments": "/assessments", "/assessments/{trace}": f"/assessments/{trace}", "/assessments/{trace}/flow": f"/assessments/{trace}/flow",
        "/assessments/{trace}/architecture": f"/assessments/{trace}/architecture",
        "/assessments/{trace}/risk-matrix": f"/assessments/{trace}/risk-matrix",
        "/assessments/{trace}/decider": f"/assessments/{trace}/decider",
        "/assessments/{trace}/trace": f"/assessments/{trace}/trace",
        "/assessments/{trace}/export": f"/assessments/{trace}/export",
        "/artifacts/{trace}/{kind}/{aid}": f"/artifacts/{trace}/decision/{kinds['decision'][0]}",
        "/catalogs/{kind}": "/catalogs/controls", "/versions": "/versions", "/variants": "/variants", "/healthz": "/healthz",
        "/api/attributes-form/{template_id}": "/api/attributes-form/RA03-LITE",
    }


def test_all_get_routes_respond_without_cdn_refs(env):
    client, app, trace = env
    table = urls(trace, app)
    get_routes = {r.path for r in app.routes if "GET" in getattr(r, "methods", ()) and not r.path.startswith(SKIP_ROUTES)}
    assert get_routes <= set(table), f"routes without a smoke case: {sorted(get_routes - set(table))}"
    for kind in ("controls", "risks", "patterns", "templates"):
        table[f"/catalogs/{kind}"] = f"/catalogs/{kind}"
    for path, url in table.items():
        r = client.get(url)
        assert r.status_code == 200, (url, r.status_code)
        assert not EXTERNAL.search(r.text), f"external reference in {url}: {EXTERNAL.search(r.text).group(0)}"
    assert client.get("/static/mermaid.min.js").status_code == 200 and client.get("/static/app.css").status_code == 200
    assert client.get("/assessments/" + "0" * 32).status_code == 404


def test_report_labels_and_unmapped_fact(env):
    client, _, trace = env
    html = client.get(f"/assessments/{trace}").text
    assert LABEL_SCORING == "illustrative, not approved policy" and LABEL_SCORING in html
    assert LABEL_SPECTRAL == "design-level evidence only" and LABEL_SPECTRAL in html
    assert "UNMAPPED" in html and "data_classification" in html
    assert LABEL_SCORING in client.get(f"/assessments/{trace}/export").text
    assert LABEL_SPECTRAL in client.get(f"/assessments/{trace}/export").text


def test_upload_rejects_oversize(env):
    client, _, _ = env
    big = json.dumps({"nodes": [], "pad": "x" * (1024 * 1024 + 10)})
    assert client.post("/api/upload", content=big).status_code == 413


@pytest.mark.parametrize("body", [b"\xff\xfe\x00binary", b"key: [unclosed", b"a: b: c: [", b"{not json: ["])
def test_upload_rejects_non_json_yaml(env, body):
    client, _, _ = env
    assert client.post("/api/upload", content=body).status_code == 415


@pytest.mark.parametrize("body", [b"plain text", b"[1, 2]", b'{"no": "nodes"}'])
def test_upload_rejects_non_calm_documents(env, body):
    client, _, _ = env
    assert client.post("/api/upload", content=body).status_code == 422


def test_upload_accepts_yaml_and_json(env):
    client, _, _ = env
    assert client.post("/api/upload", content=b"nodes: []\n").status_code == 200
    assert client.post("/api/upload", content=b'{"nodes": []}').status_code == 200
