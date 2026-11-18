import copy
import shutil
from pathlib import Path

import pytest

from agip_shared.contracts import InvalidTransition
from calm_generation import composer, lifecycle as lc, pattern_library as pl

ROOT = Path(__file__).resolve().parents[1]
SPEC = composer.load_spec(ROOT / "templates" / "RA03-LITE.compose.yaml")


@pytest.fixture
def reg(tmp_path):
    p = tmp_path / "lifecycle.yaml"
    shutil.copy(lc.REGISTRY, p)
    return p


def set_state(path, key, state):
    r = lc.load(path)
    r["entries"][key]["state"] = state
    lc.save(r, path)


def test_all_seed_patterns_are_valid_and_published():
    r = lc.load()["entries"]
    pats = pl.load_patterns()
    assert set(pats) >= {"P02", "P03", "P07", "P08", "P11", "P12", "P13", "P14", "P15", "P16"}   # seed; Build Pattern may add more
    for pid, p in pats.items():
        assert lc.validate_pattern_shape(p, r[pid]) == [], pid
        assert r[pid]["state"] == "PUBLISHED" and r[pid]["history"][-1]["to"] == "PUBLISHED"
        assert r[pid]["sha256"] == pl.ref_of(p).sha256
    assert r["RA03-LITE"]["state"] == "PUBLISHED" and r["RA05-CYBER-REMEDIATION"]["state"] == "PUBLISHED"


def _bad_rel(p):
    p["properties"]["relationships"]["prefixItems"][0]["properties"]["relationship-type"]["const"]["connects"]["source"]["node"] = "ghost"


@pytest.mark.parametrize("mutate,msg", [
    (_bad_rel, "unknown node"),
    (lambda p: p["metadata"]["related_controls"].append("NOPE-1"), "unknown control"),
    (lambda p: p["metadata"]["related_risks"].append("NOPE-2"), "unknown risk"),
    (lambda p: p.update(description="Runs on AWS"), "technology"),
    (lambda p: p.update({"$schema": "https://example/x.json"}), "schema"),
])
def test_invalid_pattern_cannot_be_approved(mutate, msg, reg):
    pats = copy.deepcopy(pl.load_patterns())
    set_state(reg, "P03", "IN_REVIEW")
    mutate(pats["P03"])
    with pytest.raises(lc.PatternInvalid, match=msg):
        lc.transition("P03", "APPROVED", by="a", role="r", rationale="x", path=reg, patterns=pats)
    assert lc.state_of("P03", reg) == "IN_REVIEW"


def test_transition_history_and_table(reg):
    set_state(reg, "P02", "DRAFT")
    for tgt in ("IN_REVIEW", "APPROVED", "PUBLISHED"):
        lc.transition("P02", tgt, by="bob", role="reviewer", rationale="ok", path=reg)
    h = lc.load(reg)["entries"]["P02"]["history"]
    assert [x["to"] for x in h[-3:]] == ["IN_REVIEW", "APPROVED", "PUBLISHED"]
    assert all(h[-1][k] for k in ("by", "role", "rationale", "at"))
    with pytest.raises(InvalidTransition):
        lc.transition("P02", "DRAFT", by="b", role="r", rationale="x", path=reg)
    with pytest.raises(ValueError, match="rationale"):
        lc.transition("P02", "DEPRECATED", by="b", role="r", rationale=" ", path=reg)


def test_only_approved_patterns_compose(reg):
    pats = pl.load_patterns()
    lc.composable_patterns(SPEC, pats, reg)
    for st in ("DRAFT", "IN_REVIEW", "DEPRECATED"):
        set_state(reg, "P02", st)
        with pytest.raises(lc.NotComposable, match="P02"):
            lc.composable_patterns(SPEC, pats, reg)
    set_state(reg, "P02", "APPROVED")
    lc.composable_patterns(SPEC, pats, reg)


def test_ra_manifest_matches_template_and_hash_is_stable(reg):
    e = lc.load(reg)["entries"]["RA03-LITE"]
    res = composer.compose(pl.load_patterns(), SPEC)
    assert e["composed_sha256"] == lc.sha256_hex(res.text)
    assert e["source_patterns"] == res.template["metadata"]["source-patterns"]
    assert lc.record_composition("RA03-LITE", int(SPEC["version"]), res.text, res.template, by="t", path=reg)["state"] == "PUBLISHED"
    with pytest.raises(ValueError, match="bump"):
        lc.record_composition("RA03-LITE", int(SPEC["version"]), res.text + " ", res.template, by="t", path=reg)
