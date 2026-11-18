"""Task 26.4: cross-framework contracts.

Rule Authoring output is valid Governance input; CALM Generation output is valid Governance input; pattern
related_controls / related_risks join to the Rule Authoring catalogs; Rule_Code joins are deterministic; a ruleset
whose bytes no longer match MANIFEST.yaml is visible in the versions record. Offline: CALM and Spectral run from
recorded outputs, LLM and Decider from fixtures.
"""
import json
import shutil
from pathlib import Path

import pytest
import yaml

from agip_shared.hashing import canonical_json, sha256_hex
from agip_shared.settings import Settings
from governance_execution import cli as gcli
from governance_execution.core import catalogs as gcatalogs
from governance_execution.dashboard.data import ReportStore
from governance_execution.exec import factory, rulesets as grulesets
from governance_execution.store.repository import MemoryRepository
from governance_execution.units.calm_builder import instantiate, load_template
from rule_authoring import compile as rcompile
from rule_authoring.paths import FRAMEWORK_ROOT as RA

PLATFORM = RA.parent
CG = PLATFORM / "calm-app-generation-framework"
GE = PLATFORM / "governance-execution-framework"
SETTINGS = Settings(_env_file=None, decider_provider="fixture", model_provider="replay")
TPL, TEXT = load_template("RA03-LITE")


def _form(v):
    return yaml.safe_load((GE / "forms" / f"{v}.attributes.yaml").read_text(encoding="utf-8"))


def _assess_file(app_file, data, catalogs, rulesets, capsys):
    """Run the standalone governance CLI; return (exit code, parsed JSON result)."""
    capsys.readouterr()
    code = gcli.main(["assess", str(app_file), "--mode", "no-llm", "--cli", "replay", "--decider", "fixture",
                      "--catalogs", str(catalogs), "--rulesets", str(rulesets), "--template", "RA03-LITE",
                      "--data-dir", str(data)])
    return code, json.loads(capsys.readouterr().out)


@pytest.fixture(scope="module")
def ra_out(tmp_path_factory):
    """Rule Authoring output: compiled rulesets + MANIFEST.yaml in a tmp dir, from the repo catalogs."""
    out = tmp_path_factory.mktemp("ra-out")
    rcompile.compile_all(RA / "catalogs", out)
    return out


def _manifest(d):
    return yaml.safe_load((d / "MANIFEST.yaml").read_text(encoding="utf-8"))["rulesets"]


def test_rule_authoring_output_is_valid_governance_input(ra_out, tmp_path, capsys):
    man = _manifest(ra_out)
    assert set(man) == {"controls.spectral.yaml", "risks.spectral.yaml"}
    for name, m in man.items():
        assert sha256_hex((ra_out / name).read_bytes()) == m["sha256"]
    for lane in ("controls", "risks"):                      # governance loads the catalogs RA produced/approved
        cat = gcatalogs.load(lane, RA / "catalogs")
        assert cat["items"] and cat["version"] == man[f"{lane}.spectral.yaml"]["version"]
    app = tmp_path / "invoice-lite-v2.json"
    app.write_bytes((CG / "fixtures" / "variants" / "invoice-lite-v2.json").read_bytes())
    code, res = _assess_file(app, tmp_path / "data", RA / "catalogs", ra_out, capsys)
    assert code == 0 and res["assessment_status"] == "COMPLETED"
    versions = ReportStore(tmp_path / "data").get(res["trace_id"], "versions")
    for lane in ("controls", "risks"):
        rec, m = versions["rulesets"][lane], man[f"{lane}.spectral.yaml"]
        assert rec["sha256"] == m["sha256"] and str(rec["version"]) == str(m["version"])
        assert rec["file"] == f"{lane}.spectral.yaml"


def test_calm_generation_output_is_valid_governance_input(tmp_path, capsys):
    d = tmp_path / "gen"
    coord, _ = factory.build("no-llm", settings=SETTINGS, repo=MemoryRepository(d), data_dir=d, cli="replay")
    r = instantiate(_form("v1"), template=TPL, template_text=TEXT, template_status="PUBLISHED", calm=coord.ctx.calm,
                    sink=coord.ctx.sink, trace_id="gen-v1")
    assert r.status == "VALID" and r.app_model
    manifest = coord.ctx.sink.get("gen-v1", "generation_manifest", "invoice-lite-v1")
    model = coord.ctx.sink.get("gen-v1", "app_model", "invoice-lite-v1")
    assert manifest["output_sha256"] == sha256_hex(canonical_json(model)) == r.app_sha256
    assert manifest["template"]["id"] == "RA03-LITE" and manifest["calm_cli_version"]
    app = tmp_path / "app.json"
    app.write_text(json.dumps(model), encoding="utf-8")
    code, res = _assess_file(app, tmp_path / "data", RA / "catalogs", RA / "rulesets", capsys)
    assert code == 0 and res["validation_status"] == "VALID" and res["decision"] == "APPROVED_WITH_CONDITIONS"
    versions = ReportStore(tmp_path / "data").get(res["trace_id"], "versions")
    assert versions["input_artifacts"]["app_model"]["sha256"] == manifest["output_sha256"]


def test_pattern_relations_join_to_rule_authoring_catalog_ids():
    controls = {i["control_id"] for i in yaml.safe_load((RA / "catalogs" / "controls.catalog.yaml").read_text(encoding="utf-8"))["items"]}
    risks = {i["risk_id"] for i in yaml.safe_load((RA / "catalogs" / "risks.catalog.yaml").read_text(encoding="utf-8"))["items"]}
    seen_c, seen_r = set(), set()
    files = sorted((CG / "patterns").glob("P*.json"))
    assert len(files) == 8
    for f in files:
        md = json.loads(f.read_text(encoding="utf-8"))["metadata"]
        for c in md.get("related_controls", []):
            assert c in controls, f"{f.name}: unknown control {c}"
            seen_c.add(c)
        for k in md.get("related_risks", []):
            assert k in risks, f"{f.name}: unknown risk {k}"
            seen_r.add(k)
    assert seen_c and seen_r


def _joins(trace_store, trace, ruleset_dir):
    """control/risk -> Rule_Codes (result side) checked against the Rule_Codes defined by the compiled rulesets."""
    defined = {lane: set(yaml.safe_load((ruleset_dir / f"{lane}.spectral.yaml").read_text(encoding="utf-8"))["rules"])
               for lane in ("controls", "risks")}
    gap, prof = trace_store.get(trace, "control_gap"), trace_store.get(trace, "risk_profile")
    joins = {f"control:{c['control_id']}": sorted(c["rule_codes"]) for c in gap["controls"]}
    joins.update({f"risk:{r['risk_id']}": sorted({f["rule_code"] for f in r["findings"]}) for r in prof["risks"]})
    for key, codes in joins.items():
        lane = "controls" if key.startswith("control:") else "risks"
        assert set(codes) <= defined[lane], (key, sorted(set(codes) - defined[lane]))
    return joins


def test_rule_code_joins_are_deterministic(ra_out, tmp_path, capsys):
    app = tmp_path / "v3.json"
    app.write_bytes((CG / "fixtures" / "variants" / "invoice-lite-v3.json").read_bytes())
    runs = []
    for n in (1, 2):
        data = tmp_path / f"data{n}"
        _, res = _assess_file(app, data, RA / "catalogs", ra_out, capsys)
        runs.append(_joins(ReportStore(data), res["trace_id"], ra_out))
    assert runs[0] == runs[1] and runs[0]
    assert any(k.startswith("control:") and v for k, v in runs[0].items())
    assert any(k.startswith("risk:") and v for k, v in runs[0].items())   # V3 triggers risks with findings


def test_ruleset_manifest_mismatch_is_visible_in_versions(ra_out, tmp_path):
    """Governance has no refusal check for a MANIFEST mismatch (not added here); the recorded hash must differ."""
    tampered = tmp_path / "rs"
    shutil.copytree(ra_out, tampered)
    ctl = tampered / "controls.spectral.yaml"
    ctl.write_bytes(ctl.read_bytes() + b"# tampered after compile\n")
    man = _manifest(tampered)["controls.spectral.yaml"]
    info = grulesets.ruleset_info(ctl)                      # the function the versions record is built from
    assert info["sha256"] != man["sha256"] and info["version"] == str(man["version"])
    d = tmp_path / "data"
    coord, ex = factory.build("no-llm", settings=SETTINGS, repo=MemoryRepository(d), data_dir=d, cli="replay")
    coord.ctx.rulesets = {lane: tampered / f"{lane}.spectral.yaml" for lane in ("controls", "risks")}
    from governance_execution.exec.coordinator import collect_versions
    v = collect_versions(coord.ctx, coord.ctx.sink, "t-mismatch", {})
    assert v["rulesets"]["controls"]["sha256"] == info["sha256"] != man["sha256"]
    assert v["rulesets"]["risks"]["sha256"] == _manifest(tampered)["risks.spectral.yaml"]["sha256"]
