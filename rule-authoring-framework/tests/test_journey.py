"""Task 21.7: independent Rule Authoring journey (no CALM Generation, no Governance Execution)."""
import ast
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from rule_authoring import approval as ap, compile as cp, coverage as cov, extraction as ex, ingest as ing
from rule_authoring.paths import FRAMEWORK_ROOT

PLATFORM = FRAMEWORK_ROOT.parent

pytestmark = pytest.mark.acceptance

ROOT = PLATFORM.parent
AIGF, CCC = ROOT / "ai-governance-framework", ROOT / "common-cloud-controls"
CALM_FIXTURE = PLATFORM / "calm-app-generation-framework" / "fixtures" / "variants" / "invoice-lite-v1.json"
REC = FRAMEWORK_ROOT / "fixtures" / "recordings" / "llm"
FORBIDDEN = ("calm_generation", "governance_execution")


def _dump(path, doc):
    path.write_bytes(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True).encode("utf-8"))


@pytest.fixture(scope="module")
def journey(tmp_path_factory):
    if not (AIGF / "docs").is_dir() or not (CCC / "catalogs").is_dir():
        pytest.skip("AIGF / CCC checkouts not present")
    w = tmp_path_factory.mktemp("journey")
    cats, drafts, srcs = w / "catalogs", w / "catalogs" / "drafts", w / "catalogs" / "sources"
    cats.mkdir()
    for n in ("controls", "risks"):  # copies; repo catalogs are never modified
        shutil.copy(FRAMEWORK_ROOT / "catalogs" / f"{n}.catalog.yaml", cats)
    for name, src in (("aigf", AIGF), ("ccc", CCC)):
        ing.main(["--source", name, "--path", str(src), "--out", str(srcs / f"{name}.json"), "--extract",
                  "--provider", "replay", "--recordings", str(REC), "--drafts", str(drafts)])
    return w


def _draft(w, key):
    return json.loads((w / "catalogs" / "drafts" / f"{key}.json").read_text(encoding="utf-8"))


def test_journey(journey):
    w = journey
    cats = w / "catalogs"
    # 1. ingest + extract: drafts exist, inexpressible CCC.Core.CN01 stored and reported
    assert (cats / "sources" / "aigf.json").is_file() and (cats / "sources" / "ccc.json").is_file()
    d = _draft(w, "CCC.Core.CN01")
    assert d["status"] == "DRAFT" and d["body"]["extraction"]["candidate_rule"] is None
    assert d["body"]["extraction"]["inexpressible_reason"]
    assert (cats / "drafts" / "CCC.Core.CN02.json").is_file() and (cats / "drafts" / "CCC.Core.TH01.json").is_file()

    # 2. review: promote drafts to catalog entries (still DRAFT), edit a field
    ctl = ex.to_catalog_entry(_draft(w, "CCC.Core.CN02"))
    risk = ex.to_catalog_entry(_draft(w, "CCC.Core.TH01"))
    cpath, rpath = cats / "controls.catalog.yaml", cats / "risks.catalog.yaml"
    for e in (ctl, risk):  # to_catalog_entry emits "FW:id" strings; the catalog schema wants {framework, id}
        e["references"] = [dict(zip(("framework", "id"), r.split(":", 1))) for r in e["references"]]
    for path, entry in ((cpath, ctl), (rpath, risk)):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        doc["items"].append(entry)
        _dump(path, doc)
    doc = yaml.safe_load(cpath.read_text(encoding="utf-8"))
    for i in doc["items"]:
        if i.get("control_id") == "CCC.Core.CN02":
            i["configurations"][0]["remediation"] = "Reviewed: " + i["configurations"][0]["remediation"]
    _dump(cpath, doc)

    # 3. approve: control by role/rationale; risk is refused until confirmed
    ap.transition_in_catalog(cpath, "CCC.Core.CN02", "IN_REVIEW", "alice", "reviewer", "checked")
    ap.transition_in_catalog(cpath, "CCC.Core.CN02", "APPROVED", "bob", "approver", "ok")
    ap.transition_in_catalog(rpath, "CCC.Core.TH01", "IN_REVIEW", "alice", "reviewer", "checked")
    with pytest.raises(ap.ApprovalError, match="confirm"):
        ap.transition_in_catalog(rpath, "CCC.Core.TH01", "APPROVED", "bob", "approver", "ok")
    ap.confirm_in_catalog(rpath, "CCC.Core.TH01", "bob", "approver", "scores reviewed")
    ap.transition_in_catalog(rpath, "CCC.Core.TH01", "APPROVED", "bob", "approver", "ok")

    # 4. compile twice: identical bytes
    out1, out2 = w / "rs1", w / "rs2"
    cp.compile_all(cats, out1)
    cp.compile_all(cats, out2)
    for f in ("controls.spectral.yaml", "risks.spectral.yaml", "MANIFEST.yaml"):
        assert (out1 / f).read_bytes() == (out2 / f).read_bytes()
    rules = yaml.safe_load((out1 / "controls.spectral.yaml").read_text(encoding="utf-8"))["rules"]
    code = ctl["configurations"][0]["rule_codes"][0]
    assert code in rules
    assert risk["rule_codes"][0] in yaml.safe_load((out1 / "risks.spectral.yaml").read_text(encoding="utf-8"))["rules"]

    # 5. lineage: rule_code -> catalog item -> source id -> source path -> coverage row
    item = next(i for i in yaml.safe_load(cpath.read_text(encoding="utf-8"))["items"] if code in i["spectral_rules"])
    assert item["control_id"] == "CCC.Core.CN02" and item["history"][-1]["to"] == "APPROVED"
    assert item["configurations"][0]["remediation"].startswith("Reviewed: ")
    sid = item["source"]["id"]
    src = next(s for s in json.loads((cats / "sources" / "ccc.json").read_text(encoding="utf-8"))["items"] if s["id"] == sid)
    assert (CCC / src["path"]).exists()
    rep = cov.build(cov.load_sources(w), cov.load_drafts(w), cov.load_catalogs(w))
    row = next(r for r in rep["rows"] if r["id"] == sid)
    assert row["state"] == "APPROVED rule" and code in row["rule_codes"]
    assert next(r for r in rep["rows"] if r["id"] == "CCC.Core.CN01")["state"] == "not expressible"

    # 6. independent CALM fixture is plain JSON data; compiled `given` paths are well-formed
    calm = json.loads(CALM_FIXTURE.read_text(encoding="utf-8"))
    assert calm["nodes"]
    for r in rules.values():
        assert str(r["given"]).startswith("$")
    (w / "ok").write_text("1")


@pytest.mark.skipif(shutil.which("spectral") is None, reason="spectral CLI not installed")
def test_real_spectral_runs_on_independent_calm_fixture(journey):
    ruleset = journey / "rs1" / "controls.spectral.yaml"
    if not ruleset.exists():
        pytest.skip("journey did not run")
    r = subprocess.run(["spectral", "lint", "-r", str(ruleset), "-f", "json", str(CALM_FIXTURE)],
                       capture_output=True, text=True, check=False)
    assert r.returncode in (0, 1) and isinstance(json.loads(r.stdout or "[]"), list)


def test_no_module_imports_calm_generation_or_governance_execution():
    for p in (FRAMEWORK_ROOT / "src" / "rule_authoring").glob("*.py"):
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            names = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""] if isinstance(n, ast.ImportFrom) else []
            assert not any(re.match(rf"^({'|'.join(FORBIDDEN)})(\.|$)", x) for x in names), f"{p.name} imports {names}"
