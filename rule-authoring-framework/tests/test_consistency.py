import copy

from rule_authoring import consistency as cs


def item(cid="C1", code="ctl-a", ref=None):
    return {"control_id": cid, "configurations": [{"rule_codes": [ref or code]}],
            "spectral_rules": {code: {"given": "$"}}}


def kinds(errs):
    return sorted(e.kind for e in errs)


def test_shipped_catalogs_are_consistent():
    assert cs.check(cs.load_catalogs(cs.DEFAULT_CATALOGS)) == []
    assert cs.main([]) == 0


def test_clean():
    assert cs.check({"a.yaml": {"items": [item()]}, "b.yaml": {"items": [item("C2", "ctl-b")]}}) == []


def test_duplicate_rule_code_reports_both_locations():
    errs = cs.check({"a.yaml": {"items": [item("C1", "ctl-a")]}, "b.yaml": {"items": [item("C2", "ctl-a")]}})
    assert kinds(errs) == ["duplicate_rule_code"]
    assert len(errs[0].locations) == 2 and "a.yaml" in errs[0].locations[0] and "b.yaml" in errs[0].locations[1]


def test_undefined_rule_code():
    errs = cs.check({"a.yaml": {"items": [item("C1", "ctl-a", ref="ctl-missing")]}})
    assert kinds(errs) == ["undefined_rule_code"] and errs[0].key == "ctl-missing"


def test_conflicting_definition_vs_exact_duplicate():
    a = item("C1", "ctl-a")
    b = copy.deepcopy(a)
    b["title"] = "different"
    conflict = cs.check({"a.yaml": {"items": [a]}, "b.yaml": {"items": [b]}})
    assert "conflict" in kinds(conflict)
    dup = cs.check({"a.yaml": {"items": [a]}, "b.yaml": {"items": [copy.deepcopy(a)]}})
    assert "duplicate_item" in kinds(dup)
    assert all(len(e.locations) == 2 for e in conflict + dup if e.kind in ("conflict", "duplicate_item"))
