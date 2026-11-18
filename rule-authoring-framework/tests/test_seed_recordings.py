from pathlib import Path

import pytest
import yaml

from agip_shared.gateway import ModelGateway, Recorder
from rule_authoring import approval, extraction as ex, seed_recordings as sr
from rule_authoring.sources_aigf import read as read_aigf

AIGF = Path(__file__).resolve().parents[3] / "ai-governance-framework" / "docs"
pytestmark = pytest.mark.skipif(not AIGF.is_dir(), reason="AIGF checkout not present")


@pytest.mark.parametrize("key", sorted(sr.SEED_ITEMS))
def test_replay_to_approved_entry_matches_catalog(key, tmp_path):
    items, _ = read_aigf([AIGF / "_mitigations", AIGF / "_risks"])
    src = next(i for i in items if ex.item_key(i.framework, i.id) == key)
    prose = ex.body_of_markdown(Path(src.path).read_text(encoding="utf-8"))
    gw = ModelGateway("replay", recorder=Recorder(sr.RECORDINGS))
    res = ex.extract(gw, framework=src.framework, native_id=src.id, title=src.title, prose=prose, source_path=src.path)
    assert res.ok and res.item["status"] == "DRAFT"

    entry = ex.to_catalog_entry(res.item)
    cat = tmp_path / "c.catalog.yaml"
    cat.write_text(yaml.safe_dump({"items": [entry]}, sort_keys=False), encoding="utf-8")
    approved = approval.approve_in_catalog(cat, key, "demo-approver", confirm_scores=True)
    assert approved["status"] == "APPROVED" and approved["approved_by"] == "demo-approver"

    ref = sr._catalog_entry(key)
    code = next(iter(ref["spectral_rules"]))
    for f in ("given", "then", "description", "severity"):
        assert approved["spectral_rules"][code][f] == ref["spectral_rules"][code][f]
