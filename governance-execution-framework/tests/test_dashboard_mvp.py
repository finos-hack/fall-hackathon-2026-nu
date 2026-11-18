"""Tasks 24.5, 25.1-25.6, 25.8: MVP dashboard pages on a tmp data dir populated by running V1-V4 offline."""
import json
import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from agip_shared.contracts import HumanTask
from agip_shared.humantasks import HumanTaskStore
from agip_shared.settings import Settings
from governance_execution.dashboard.app import LABEL_SCORING, LABEL_SPECTRAL, create_app
from governance_execution.exec import factory
from governance_execution.store.repository import MemoryRepository
from governance_execution.units.calm_builder import instantiate, load_template

ROOT = Path(__file__).resolve().parents[2]
FORMS = ROOT / "governance-execution-framework" / "forms"
SETTINGS = Settings(_env_file=None, decider_provider="fixture", model_provider="replay")
EXTERNAL = re.compile(r"""(?:src|href)\s*=\s*["']\s*(?:https?:)?//|url\(\s*["']?\s*https?://|@import\s+["']?https?://""", re.I)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    d = tmp_path_factory.mktemp("mvp")
    repo = MemoryRepository(d)
    tpl, text = load_template("RA03-LITE")
    traces = {}
    for v in ("v1", "v2", "v3", "v4"):
        coord, ex = factory.build("normal", settings=SETTINGS, repo=repo, data_dir=d, cli="replay")
        form = yaml.safe_load((FORMS / f"{v}.attributes.yaml").read_text(encoding="utf-8"))
        r = instantiate(form, template=tpl, template_text=text, template_status="PUBLISHED", calm=coord.ctx.calm)
        traces[v] = coord.run(r.app_model, executor=ex, template_id="RA03-LITE", source={"app_id": form["app"]["id"]}).trace_id
    store = HumanTaskStore(d)
    store.create(HumanTask(task_id="t-rule-1", framework="rule_authoring", task_type="RULE_REVIEW", subject_refs=["AIGF-MI-024", "AIGF:mi-24"],
                           role="rule_reviewer", priority="HIGH", context={"app": "invoice-lite-v1", "created_by": "alice"}))
    store.create(HumanTask(task_id="t-ra-1", framework="governance_execution", task_type="RISK_ACCEPTANCE", subject_refs=[traces["v2"]],
                           trace_id=traces["v2"], role="risk_approver", context={"app": "invoice-lite-v2"}))
    return TestClient(create_app(SETTINGS, d)), traces, d


def _urls(traces):
    t = traces["v1"]
    return ["/", "/overview", "/assessments", "/review", "/review/t-rule-1", "/workbench/rule-authoring", "/workbench/calm-generation",
            "/workbench/governance", f"/assessments/{t}/execution", f"/assessments/{traces['v4']}/execution",
            "/lineage/source/AIGF:mi-24", "/lineage/source/mi-24", f"/assessments/{t}", f"/assessments/{t}/trace"] + \
        [f"/registry/{k}" for k in ("sources", "risks", "controls", "assessment-requirements", "patterns", "ras", "rulesets",
                                     "governance-config", "scoring-profiles", "evaluators", "models-prompts")]


def test_every_page_200_with_both_labels_and_no_external_refs(env):
    client, traces, _ = env
    for url in _urls(traces):
        r = client.get(url)
        assert r.status_code == 200, (url, r.status_code, r.text[:300])
        assert not EXTERNAL.search(r.text), url
    assert client.get("/registry/nope").status_code == 404
    assert client.get("/lineage/source/none").status_code == 404
    assert client.get("/review/missing").status_code == 404


def test_registry_details_and_used_by(env):
    client, traces, _ = env
    for kind, rid in (("controls", "AIGF-MI-024"), ("risks", "AIGF-RI-018"), ("patterns", "P02"), ("ras", "RA03-LITE"), ("sources", "AIGF:mi-24"),
                      ("rulesets", "controls.spectral.yaml"), ("scoring-profiles", "scoring_profile"), ("governance-config", "gates"),
                      ("evaluators", "calm:1.60.1")):
        r = client.get(f"/registry/{kind}/{rid}")
        assert r.status_code == 200, (kind, rid, r.status_code)
        assert "Used by assessments" in r.text
    ids = client.get("/registry/assessment-requirements").text
    assert "CFG-HITL-PAYMENT" in ids or "evidence artifact" in ids
    d = client.get("/registry/patterns/P02").text
    assert "/assessments/" in d and "never rewritten" in d
    assert client.get("/registry/models-prompts").text.count("extraction") >= 1


def test_overview_shows_six_centered_metrics_only(env):
    client, traces, _ = env
    html = client.get("/").text
    main = html.split("<main>")[1]
    for label in ("Controls", "Risks", "Patterns", "Reference Architectures", "Control Gaps Assessment", "Risk Assessment"):
        assert f'<span class="kpi-label">{label}</span>' in main
    assert html.count("card kpi") == 6 and "<b>3</b>" in html        # V1-V3 have gap and risk results; V4 is blocked
    for gone in ("Framework health", "Active versions", "By decision", "Recent changes"):
        assert gone not in html
    assert "illustrative, not approved policy" not in html and "MVP" not in html   # banner and footer removed from app pages

def test_review_filters(env):
    client, _, _ = env
    assert "t-rule-1" in client.get("/review").text and "t-ra-1" in client.get("/review").text
    only = client.get("/review?framework=rule_authoring").text
    assert "t-rule-1" in only and "t-ra-1" not in only
    assert "t-ra-1" in client.get("/review?type=RISK_ACCEPTANCE").text and "t-rule-1" not in client.get("/review?type=RISK_ACCEPTANCE").text
    assert "t-rule-1" not in client.get("/review?status=COMPLETED").text
    assert "t-rule-1" in client.get("/review?reviewer=rule_reviewer").text and "t-ra-1" not in client.get("/review?reviewer=rule_reviewer").text
    assert "t-rule-1" in client.get("/review?application=invoice-lite-v1").text and "t-ra-1" not in client.get("/review?application=invoice-lite-v1").text
    assert "t-rule-1" in client.get("/review?priority=HIGH").text and "t-ra-1" not in client.get("/review?priority=HIGH").text
    detail = client.get("/review/t-ra-1").text
    assert "/assessments/" in detail and "/trace" in detail


def test_review_act_authorization_and_completion(env):
    client, _, d = env
    url = "/api/review/t-rule-1/act"
    bad = client.post(url, json={"actor": "mallory", "role": "intern", "action": "CLAIM", "rationale": "let me"})
    assert bad.status_code == 403 and not bad.json()["ok"]
    assert client.post(url, json={"actor": "bob", "role": "rule_reviewer", "action": "COMPLETE", "rationale": "x"}).status_code == 409
    assert client.post(url, json={"actor": "bob", "role": "rule_reviewer", "action": "CLAIM"}).status_code == 422
    assert client.post("/api/review/none/act", json={"actor": "a", "role": "r", "action": "CLAIM", "rationale": "x"}).status_code == 404
    form = client.post(url, content=b"actor=intern&role=intern&action=CLAIM&rationale=nope", headers={"content-type": "application/x-www-form-urlencoded"})
    assert form.status_code == 403 and "Error" in form.text
    assert client.post(url, json={"actor": "bob", "role": "rule_reviewer", "action": "CLAIM", "rationale": "taking it"}).json()["resulting_state"] == "CLAIMED"
    ok = client.post(url, json={"actor": "bob", "role": "rule_reviewer", "action": "COMPLETE", "rationale": "reviewed"})
    assert ok.status_code == 200 and ok.json()["resulting_state"] == "COMPLETED"
    assert HumanTaskStore(d).get("t-rule-1").status == "COMPLETED"
    assert "COMPLETED" in client.get("/review/t-rule-1").text


def test_lineage_both_ways_and_inferred_facts(env):
    client, traces, _ = env
    fwd = client.get("/lineage/source/AIGF:mi-24").text
    assert "AIGF-MI-024" in fwd and "ctl-payment-requires-human-approval" in fwd
    assert any(f"/assessments/{traces[v]}" in fwd for v in ("v1", "v2", "v3"))
    # backward: decision -> ... -> control -> registry -> source lineage
    trace = client.get(f"/assessments/{traces['v2']}/trace").text
    assert "control:" in trace or "AIGF-MI" in trace
    ctl = client.get("/registry/controls/AIGF-MI-024").text
    assert "/lineage/source/AIGF:mi-24" in ctl
    assert client.get(f"/assessments/{traces['v3']}").status_code == 200

def test_execution_page(env):
    client, traces, _ = env
    html = client.get(f"/assessments/{traces['v2']}/execution").text
    assert "validate_calm" in html and "decide" in html and "t-ra-1" in html and "Decider outcomes" in html
    assert "BLOCKED" in client.get(f"/assessments/{traces['v4']}/execution").text


def test_upload_and_export_still_work(env):
    client, traces, _ = env
    assert client.post("/api/upload", content=b"nodes: []\n").status_code == 200
    assert client.post("/api/upload", content=b"plain text").status_code == 422
    assert client.post("/api/upload", content=json.dumps({"nodes": [], "p": "x" * (1024 * 1024 + 5)})).status_code == 413
    ex = client.get(f"/assessments/{traces['v1']}/export")
    assert ex.status_code == 200 and LABEL_SCORING in ex.text and LABEL_SPECTRAL in ex.text


# ---- left-menu portal (Controls / Risk Profile / CALM Patterns / Assessments)
def test_menu_has_the_four_catalog_entries_and_overview(env):
    client, traces, _ = env
    html = client.get("/").text
    for label in ("Controls Catalog", "Risk Profile Catalog", "CALM Patterns Catalog", "Assessments", "Source Registry", "AIGP"):
        assert label in html
    assert "Dashboard" in html and "Overview" in html


def test_catalog_pages_search_filter_expand_and_focus(env):
    client, *_ = env
    c = client.get("/catalogs/controls").text
    assert "AIGF-MI-024" in c and 'class="row' in c and 'class="detail"' in c and "Used in patterns" in c
    assert "AIGF-MI-024" not in client.get("/catalogs/controls?q=zzz-no-match").text
    assert "Nothing matches" in client.get("/catalogs/controls?q=zzz-no-match").text
    assert "AIGF-MI-024" in client.get("/catalogs/controls?status=APPROVED&q=approval").text
    assert re.search(r'class="row open focus" id="r-AIGF-MI-024"', client.get("/catalogs/controls?focus=AIGF-MI-024").text)
    assert "AIGF-RI-018" in client.get("/catalogs/risks").text
    p = client.get("/catalogs/patterns").text
    assert "RA03-LITE" in p and "P02" in p and "RA template" in p
    t = client.get("/catalogs/templates").text   # RA templates live in the patterns catalog
    assert "RA03-LITE" in t and "No match" not in t and 'id="r-P02"' not in t
    assert client.get("/catalogs/nope").status_code == 404


def test_assessments_list_expands_to_report_with_catalog_links(env):
    client, traces, _ = env
    lst = client.get("/assessments").text
    assert traces["v2"] in lst and f"/assessments/{traces['v2']}?partial=1" in lst
    assert "REJECTED" in client.get("/assessments?decision=REJECTED").text
    assert traces["v2"] not in client.get("/assessments?decision=APPROVED_WITH_CONDITIONS").text
    part = client.get(f"/assessments/{traces['v2']}?partial=1").text
    assert "<html" not in part and "Control gaps" in part and "Catalog references" in part
    assert "/catalogs/controls?focus=AIGF-MI-024" in part and "/catalogs/patterns?focus=RA03-LITE" in part
    assert "/catalogs/risks?focus=" in part and "Open full report" in part
    assert "<aside" in client.get(f"/assessments/{traces['v2']}").text   # full report keeps the menu


def test_source_registry_sections(env):
    client, traces, _ = env
    html = client.get("/source-registry").text
    for tab in ("Extraction Sources", "Risk Dimensions", "Scoring Profiles", "ADRs"):
        assert tab in html
    assert "Models &amp; Prompts" not in html and "Prompts" not in html.split("<main>")[1].split("<table")[0]   # no longer a section
    hit = client.get("/source-registry?q=mi-24").text   # 20 per page, so search for the item
    assert "AIGF:mi-24" in hit and "/lineage/source/AIGF:mi-24" in hit
    dims = client.get("/source-registry/dimensions").text
    assert "Autonomy" in dims and "Operational Criticality" in dims and "Taxonomy attributes" in dims
    assert "AIGF-RI-018" in client.get("/source-registry/dimensions?q=autonomous").text
    s = client.get("/source-registry/scoring").text
    assert "scoring_profile" in s
    assert "Rulesets" not in html.split("<main>")[1] and client.get("/source-registry/rulesets").status_code == 404
    a = client.get("/source-registry/adrs").text
    assert "DC-01" in a and "Summary" in a and 'class="scroll"' in a
    assert client.get("/source-registry/adrs?status=Open").status_code == 200
    assert client.get("/source-registry/models-prompts").status_code == 404


def test_sidebar_has_six_main_entries_and_no_others(env):
    client, *_ = env
    side = client.get("/").text.split("</aside>")[0]
    for label in ("Overview", "Controls Catalog", "Risk Profile Catalog", "CALM Patterns Catalog", "Assessments", "Source Registry", "API docs"):
        assert label in side
    for gone in ("Others", "Review queue", "Workbench", "Variants", "Versions", "Rule Authoring", "CALM Generation"):
        assert gone not in side
    for url in ("/review", "/variants", "/versions", "/workbench/governance"):   # pages kept, only unlisted
        assert client.get(url).status_code == 200
    wb = client.get("/workbench/governance").text
    assert "Rule Authoring" in wb and "CALM Generation" in wb and 'class="tab on"' in wb