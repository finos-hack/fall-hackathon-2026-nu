import copy

import yaml

from rule_authoring import compile as cp
from rule_authoring import consistency as cs

RULE = {"description": "d", "message": "m", "severity": "error", "given": "$.nodes[*]",
        "then": {"field": "x", "function": "truthy"}}


def cat(*items):
    return {"catalog": "controls", "version": 3, "items": list(items)}


def item(cid, code, status="APPROVED", rule=None):
    return {"control_id": cid, "status": status, "configurations": [{"rule_codes": [code]}],
            "spectral_rules": {code: copy.deepcopy(rule or RULE)}}


def test_only_approved_compiled():
    c = cp.compile_catalog(cat(item("A", "ctl-a"), item("B", "ctl-b", "DRAFT"), item("C", "ctl-c", "REJECTED")), "controls")
    assert c.rule_codes == ("ctl-a",) and set(c.skipped_unapproved) == {"B", "C"}
    assert list(yaml.safe_load(c.text)["rules"]) == ["ctl-a"]
    assert "version: 3" in c.text


def test_deterministic_and_order_independent():
    a, b = item("A", "ctl-a"), item("B", "ctl-b")
    assert cp.compile_catalog(cat(a, b), "controls") == cp.compile_catalog(cat(b, a), "controls")


def test_inexpressible_reported_by_rule_code():
    bad = copy.deepcopy(RULE)
    bad["then"] = {"function": "evalMagic"}
    missing = {"control_id": "M", "status": "APPROVED", "configurations": [{"rule_codes": ["ctl-ghost"]}], "spectral_rules": {}}
    c = cp.compile_catalog(cat(item("A", "ctl-bad", rule=bad), missing, item("B", "ctl-ok")), "controls")
    assert {u.rule_code for u in c.unexpressible} == {"ctl-bad", "ctl-ghost"}
    assert c.rule_codes == ("ctl-ok",)


def test_custom_function_listed_with_reason_and_core_first():
    cust = copy.deepcopy(RULE)
    cust["then"] = {"function": "countEdges"}
    c = cp.compile_catalog(cat(item("A", "ctl-a-custom", rule=cust), item("B", "ctl-z-core")), "controls",
                           {"countEdges": {"reason": "no core function counts relationships"}})
    assert c.rule_codes == ("ctl-z-core", "ctl-a-custom")
    assert "custom function countEdges: no core function counts relationships" in c.text
    assert yaml.safe_load(c.text)["functions"] == ["countEdges"]


def test_shipped_rulesets_are_fresh_and_core_only():
    docs = cs.load_catalogs(cs.DEFAULT_CATALOGS)
    custom = cp.load_custom_functions()
    for kind in ("controls", "risks"):
        c = cp.compile_catalog(docs[f"{kind}.catalog.yaml"], kind, custom)
        on_disk = (cp.RULESET_DIR / f"{kind}.spectral.yaml").read_bytes().decode("utf-8")
        assert on_disk == c.text, f"{kind}.spectral.yaml is stale; run `python -m rule_authoring.compile`"
        assert not c.unexpressible and c.rule_codes
        info = cp.ruleset_info(cp.RULESET_DIR / f"{kind}.spectral.yaml")
        assert info["sha256"] == c.sha256 and info["version"] == str(docs[f"{kind}.catalog.yaml"]["version"])


def test_cli_writes_files(tmp_path):
    assert cp.main(["--out", str(tmp_path)]) == 0
    assert (tmp_path / "controls.spectral.yaml").read_bytes() == (cp.RULESET_DIR / "controls.spectral.yaml").read_bytes()
