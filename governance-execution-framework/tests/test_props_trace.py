"""Task 13.4 (20.2 C2): Property 23, trace graph completeness. Offline; the graph is built from persisted artifacts."""
import copy
from pathlib import Path

import pytest
import yaml
from hypothesis import HealthCheck, given, settings, strategies as st

from agip_shared.settings import Settings
from governance_execution.dashboard import data
from governance_execution.exec import factory
from governance_execution.store.repository import MemoryRepository
from governance_execution.units.calm_builder import instantiate, load_template

ROOT = Path(__file__).resolve().parents[2]
FORMS = ROOT / "governance-execution-framework" / "forms"
SETTINGS = Settings(_env_file=None, decider_provider="fixture", model_provider="replay")
TPL, TEXT = load_template("RA03-LITE")
ALL = settings(max_examples=100, deadline=None, suppress_health_check=list(HealthCheck))


@pytest.fixture(scope="module")
def bundles(tmp_path_factory):
    res = {}
    for v in ("v1", "v2", "v3", "v4"):
        d = tmp_path_factory.mktemp(v)
        coord, ex = factory.build("normal", settings=SETTINGS, repo=MemoryRepository(d), data_dir=d, cli="replay")
        f = yaml.safe_load((FORMS / f"{v}.attributes.yaml").read_text(encoding="utf-8"))
        r = instantiate(f, template=TPL, template_text=TEXT, template_status="PUBLISHED", calm=coord.ctx.calm)
        out = coord.run(r.app_model, executor=ex, template_id="RA03-LITE", source={"app_id": f["app"]["id"]})
        store = data.ReportStore(d)
        res[v] = (out, store.bundle(out.trace_id))
    return res


def reach(g, start, step):
    seen, todo = {start}, [start]
    while todo:
        for n, _ in step(todo.pop()):
            if n in g.nodes and n not in seen:
                seen.add(n)
                todo.append(n)
    return seen


def expected_ids(b):
    d, ids = b["decision"] or {}, set()
    ids |= {f"gate:{g['id']}" for g in d.get("gates_evaluated", []) if g["fired"]}
    if (d.get("matrix_cell") or {}).get("evaluated"):
        ids.add("cell")
    ids |= {f"control:{c['control_id']}" for c in (b.get("control_gap") or {}).get("controls", []) if c["status"] in ("FAIL", "ERROR")}
    ids |= {f"risk:{r['risk_id']}" for r in (b.get("risk_profile") or {}).get("risks", [])}
    return ids


def check_complete(b):
    g = data.graph(b)
    fwd = reach(g, "decision", g.outgoing)
    assert set(g.nodes) <= fwd, f"unreachable from decision: {sorted(set(g.nodes) - fwd)}"
    assert expected_ids(b) <= set(g.nodes)
    kinds = {n["kind"] for n in g.nodes.values()}
    for item in [*(b.get("control_gap") or {}).get("controls", []), *(b.get("risk_profile") or {}).get("risks", [])]:
        for f in item.get("findings") or []:
            assert f"rule:{f['rule_code']}" in g.nodes and f"path:{f['path']}" in g.nodes
    for n in g.nodes.values():
        if n["kind"] == "source":
            back = reach(g, n["id"], g.incoming)
            assert "decision" in back, f"{n['id']} does not reach the decision"
    return g, kinds


# Feature: governance-as-code-mvp, Property 23: Trace graph completeness
@ALL
@given(v=st.sampled_from(["v1", "v2", "v3", "v4"]))
def test_p23_real_assessments_complete(bundles, v):
    out, b = bundles[v]
    g, kinds = check_complete(b)
    assert "decision" in kinds
    if out.status == "COMPLETED":
        if any(c["status"] == "FAIL" for c in b["control_gap"]["controls"]):
            assert {"control", "rule", "path", "source"} <= kinds
        if b["risk_profile"]["risks"]:
            assert "risk" in kinds
        if any(n["kind"] == "path" for n in g.nodes.values()):
            assert {"element", "template", "pattern"} <= kinds
    assert g.nodes["decision"]["label"].endswith(out.decision or "none")   # blocked run: no decision


# Feature: governance-as-code-mvp, Property 23: Trace graph completeness (random subsets of findings)
@ALL
@given(v=st.sampled_from(["v1", "v2", "v3"]), data_=st.data())
def test_p23_any_subset_of_controls_and_risks_stays_reachable(bundles, v, data_):
    _, b = bundles[v]
    b = copy.deepcopy(b)
    gap, prof = b["control_gap"], b["risk_profile"]
    gap["controls"] = [c for c in gap["controls"] if data_.draw(st.booleans())]
    prof["risks"] = [r for r in prof["risks"] if data_.draw(st.booleans())]
    for item in [*gap["controls"], *prof["risks"]]:
        item["findings"] = [f for f in item.get("findings") or [] if data_.draw(st.booleans())]
    b["decision"]["gates_evaluated"] = [x for x in b["decision"]["gates_evaluated"] if data_.draw(st.booleans())]
    check_complete(b)
