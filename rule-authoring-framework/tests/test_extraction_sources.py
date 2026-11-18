"""Task 21.2: extraction over AIGF and CCC source items through the ModelGateway (replay recordings)."""
import json
from pathlib import Path

import pytest

from agip_shared.gateway import ModelGateway, Recorder
from rule_authoring import extract_sources as es, extraction as ex, ingest as ing
from rule_authoring.seed_recordings import RECORDINGS

ROOT = Path(__file__).resolve().parents[3]
AIGF, CCC = ROOT / "ai-governance-framework", ROOT / "common-cloud-controls"
needs_aigf = pytest.mark.skipif(not (AIGF / "docs").is_dir(), reason="AIGF checkout not present")
needs_ccc = pytest.mark.skipif(not (CCC / "catalogs").is_dir(), reason="CCC checkout not present")
DIMS = es.load_dimensions()


def gw():
    return ModelGateway("replay", recorder=Recorder(RECORDINGS))


def run(source, root, ids, tmp_path, **kw):
    doc = ing.ingest(source, root, ids)
    return es.extract_items(doc, root, gw(), drafts_dir=tmp_path, dimensions=DIMS, ids=ids, **kw), doc


def draft(tmp_path, key):
    return json.loads((tmp_path / f"{key}.json").read_text(encoding="utf-8"))


def test_dimensions_come_from_taxonomy_data():
    assert DIMS and "Privilege & Capability" in DIMS


@needs_aigf
def test_aigf_control_and_risk_drafts(tmp_path):
    s, doc = run("aigf", AIGF, ["mi-24", "ri-24"], tmp_path)
    assert sorted(s.drafted) == ["AIGF-MI-024", "AIGF-RI-024"] and not (s.errors or s.missing or s.inexpressible)
    mi = draft(tmp_path, "AIGF-MI-024")
    assert mi["status"] == "DRAFT" and mi["body"]["source"]["id"] == "mi-24"
    assert mi["body"]["source"]["version"] == doc["commit"]
    assert mi["body"]["extraction_record"]["model"] == "recorded-seed"
    assert mi["body"]["extraction_record"]["prompt_version"] == "v1" and len(mi["body"]["extraction_input_hash"]) == 64
    ri = draft(tmp_path, "AIGF-RI-024")
    assert ri["kind"] == "risk_rule" and ri["body"]["extraction"]["triggers"][0]["dimension"] in DIMS


@needs_ccc
def test_ccc_control_threat_keep_ids_and_source_references(tmp_path):
    s, doc = run("ccc", CCC, ["CCC.Core.CN02"], tmp_path)  # control filter; threats are not filtered by --ids in the adapter
    s2, _ = run("ccc", CCC, None, tmp_path, )
    assert "CCC.Core.CN02" in s2.drafted and "CCC.Core.TH01" in s2.drafted
    c = draft(tmp_path, "CCC.Core.CN02")
    src = next(i for i in doc["items"] if i["id"] == "CCC.Core.CN02")
    assert c["id"] == "CCC.Core.CN02" and c["status"] == "DRAFT" and c["kind"] == "control_rule"
    assert c["body"]["references"] == src["references"] and c["body"]["references"]["CCM"]
    assert c["body"]["extraction_record"]["prompt_version"] == "v2"
    assert c["body"]["assessment_requirement_ids"][0].startswith("CCC.Core.CN02.AR")
    t = draft(tmp_path, "CCC.Core.TH01")
    assert t["kind"] == "risk_rule" and t["body"]["extraction"]["triggers"][0]["dimension"] in DIMS
    entry = ex.to_catalog_entry(t)
    assert entry["risk_id"] == "CCC.Core.TH01" and entry["status"] == "DRAFT" and entry["rule_codes"]
    assert any(r.startswith("MITRE-ATT&CK:") for r in entry["references"])


@needs_ccc
def test_inexpressible_is_stored_and_reported(tmp_path):
    s, _ = run("ccc", CCC, None, tmp_path)
    assert [i for i, _ in s.inexpressible] == ["CCC.Core.CN01"]
    assert "CCC.Core.CN01" not in s.drafted and not s.errors
    d = draft(tmp_path, "CCC.Core.CN01")
    assert d["status"] == "DRAFT" and d["body"]["extraction"]["candidate_rule"] is None
    assert "transport" in d["body"]["extraction"]["inexpressible_reason"]
    entry = ex.to_catalog_entry(d)
    assert entry["spectral_rules"] == {} and entry["configurations"] == []
    assert any("INEXPRESSIBLE CCC.Core.CN01" in line for line in s.lines())


@needs_ccc
def test_unrecorded_items_are_reported_missing(tmp_path):
    s, _ = run("ccc", CCC, None, tmp_path)
    assert s.missing and "CCC.Core.CN03" in s.missing
    assert not (tmp_path / "CCC.Core.CN03.json").exists()


class _Fixed:
    def __init__(self, out):
        self.out = out

    def complete(self, prompt, model, region):
        return json.dumps(self.out)


def _ccc(tmp_path, out, **kw):
    g = ModelGateway("bedrock", "m", "r", Recorder(tmp_path), _Fixed(out))
    return ex.extract_ccc(g, native_id="CCC.Core.CN02", kind="control", title="t", objective="o",
                          assessment_requirements=[{"id": "CCC.Core.CN02.AR01", "text": "x"}],
                          threat_mappings=[], references={"CCM": ["A-1"]}, **kw)


def test_model_cannot_override_references_or_id(tmp_path):
    from rule_authoring.seed_recordings import CCC_SEEDS
    out = dict(CCC_SEEDS["CCC.Core.CN02"], references={"CCM": ["MODEL-GUESS"]}, id="OTHER")
    r = _ccc(tmp_path, out)
    assert r.ok and r.item["id"] == "CCC.Core.CN02" and r.item["body"]["references"] == {"CCM": ["A-1"]}


def test_risk_dimension_must_be_in_profile_and_null_rule_needs_reason(tmp_path):
    from rule_authoring.seed_recordings import CCC_SEEDS
    bad = dict(CCC_SEEDS["CCC.Core.TH01"])
    bad["triggers"] = [{"dimension": "Vibes", "condition": "c"}]
    r = _ccc(tmp_path, bad, dimensions=DIMS)
    assert not r.ok and "Scoring_Profile" in r.reason
    r = _ccc(tmp_path, dict(CCC_SEEDS["CCC.Core.CN01"], inexpressible_reason=None))
    assert not r.ok and "inexpressible_reason" in r.reason


@needs_ccc
def test_cli_replay_summary(tmp_path, capsys):
    rc = ing.main(["--source", "ccc", "--path", str(CCC), "--out", str(tmp_path / "ccc.json"),
                   "--extract", "--provider", "replay", "--drafts", str(tmp_path / "d")])
    out = capsys.readouterr().out
    assert rc == 0 and "extraction: drafted=2 inexpressible=1 errors=0" in out
    assert (tmp_path / "d" / "CCC.Core.CN01.json").is_file()
