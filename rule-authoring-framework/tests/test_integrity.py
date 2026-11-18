"""Catalog integrity (task 21.5): reference and risk->control link checks, deterministic compile, header."""
import hashlib
import re

import yaml

from rule_authoring import compile as comp
from rule_authoring import consistency as cs

SRC = {"AIGF": {"mi-1"}, "CCC": {"CCC.Core.CN02"}}


def ctl(refs=None):
    return {"control_id": "C1", "references": refs or []}


def test_real_catalogs_pass():
    assert cs.check(cs.load_catalogs(cs.DEFAULT_CATALOGS)) == []


def test_dangling_ccc_and_aigf_refs_fail_with_location():
    errs = cs.check({"c.yaml": {"items": [ctl([{"framework": "CCC", "id": "CCC.NOPE"},
                                                {"framework": "AIGF", "id": "mi-999"}])]}}, SRC)
    assert [e.kind for e in errs] == ["dangling_reference"] * 2
    assert "c.yaml:C1.references.CCC.NOPE" in str(errs[0])


def test_valid_and_external_refs_pass_but_malformed_nist_fails():
    ok = ctl([{"framework": "CCC", "id": "CCC.Core.CN02"}, {"framework": "NIST", "id": "SC-28"},
              {"framework": "ISO42001", "id": "A-3-2"}])
    assert cs.check({"c.yaml": {"items": [ok]}}, SRC) == []
    for bad in ("", "sc28"):
        errs = cs.check({"c.yaml": {"items": [ctl([{"framework": "NIST", "id": bad}])]}}, SRC)
        assert [e.kind for e in errs] == ["malformed_reference"]


def test_missing_risk_control_link_fails():
    docs = {"controls.yaml": {"items": [ctl()]},
            "risks.yaml": {"items": [{"risk_id": "R1", "controls": ["C1", "C404"]}]}}
    errs = cs.check(docs, SRC)
    assert [e.kind for e in errs] == ["dangling_risk_control_link"]
    assert "risks.yaml:R1.controls" in str(errs[0]) and "C404" in str(errs[0])


def test_compile_twice_is_byte_identical(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    comp.compile_all(out_dir=a)
    comp.compile_all(out_dir=b)
    for name in ("controls.spectral.yaml", "risks.spectral.yaml"):
        assert (a / name).read_bytes() == (b / name).read_bytes()


def test_header_has_version_and_manifest_has_sha256(tmp_path):
    comp.compile_all(out_dir=tmp_path)
    manifest = yaml.safe_load((tmp_path / "MANIFEST.yaml").read_text(encoding="utf-8"))["rulesets"]
    for name in ("controls", "risks"):
        f = tmp_path / f"{name}.spectral.yaml"
        text = f.read_text(encoding="utf-8")
        m = re.search(r"^# version: (\d+)$", text, re.M)
        assert m
        entry = manifest[f.name]
        assert str(entry["version"]) == m.group(1)
        assert entry["sha256"] == hashlib.sha256(f.read_bytes()).hexdigest()
        assert yaml.safe_load(text)["rules"]
