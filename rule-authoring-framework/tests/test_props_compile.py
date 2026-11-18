# Feature: governance-as-code-mvp, Properties 11-13: compile / consistency
from hypothesis import given, settings, strategies as st

from rule_authoring.compile import compile_catalog
from rule_authoring.consistency import check

STATUSES = ["DRAFT", "APPROVED", "REJECTED"]
_RULE = {"description": "d", "message": "m", "severity": "error", "given": "$", "then": {"function": "truthy", "field": "x"}}
_BAD = {"description": "d", "message": "m", "severity": "error", "given": "$", "then": {"function": "nope"}}


@st.composite
def catalogs(draw, with_bad=True):
    n = draw(st.integers(0, 8))
    items = []
    for i in range(n):
        status = draw(st.sampled_from(STATUSES))
        bad = with_bad and draw(st.booleans())
        code = f"R{i}"
        items.append({"control_id": f"C{i}", "status": status, "rule_codes": [code],
                      "source_id": f"S{i}", "remediation": f"fix {i}",
                      "spectral_rules": {code: dict(_BAD if bad else _RULE)}, "_bad": bad})
    return items


def _clean(items):
    return {"version": 1, "items": [{k: v for k, v in it.items() if k != "_bad"} for it in items]}


@settings(max_examples=100)
@given(items=catalogs())
def test_p11_only_approved_compiled(items):
    # Feature: governance-as-code-mvp, Property 11: Only APPROVED items are compiled
    c = compile_catalog(_clean(items), "controls")
    approved_ok = {f"R{i}" for i, it in enumerate(items) if it["status"] == "APPROVED" and not it["_bad"]}
    assert set(c.rule_codes) == approved_ok
    skipped = {f"C{i}" for i, it in enumerate(items) if it["status"] != "APPROVED"}
    assert set(c.skipped_unapproved) == skipped


@settings(max_examples=100)
@given(items=catalogs())
def test_p12_determinism_and_unexpressible_reported(items):
    # Feature: governance-as-code-mvp, Property 12: Ruleset compile determinism
    a = compile_catalog(_clean(items), "controls")
    b = compile_catalog(_clean(items), "controls")
    assert a.text.encode() == b.text.encode() and a.sha256 == b.sha256
    bad_codes = {f"R{i}" for i, it in enumerate(items) if it["status"] == "APPROVED" and it["_bad"]}
    assert {u.rule_code for u in a.unexpressible} == bad_codes
    assert not bad_codes & set(a.rule_codes)


@settings(max_examples=100)
@given(items=catalogs(with_bad=False), order=st.randoms())
def test_p12_order_independent(items, order):
    # Feature: governance-as-code-mvp, Property 12: Ruleset compile determinism
    shuffled = list(items)
    order.shuffle(shuffled)
    assert compile_catalog(_clean(items), "x").text == compile_catalog(_clean(shuffled), "x").text


@settings(max_examples=100)
@given(items=catalogs(with_bad=False))
def test_p13_codes_join_to_unique_catalog_item(items):
    # Feature: governance-as-code-mvp, Property 13: Rule_Code join back to catalog and source
    doc = _clean(items)
    assert check({"c.yaml": doc}) == []
    compiled = compile_catalog(doc, "controls")
    for code in compiled.rule_codes:
        owners = [it for it in doc["items"] if code in it["spectral_rules"]]
        assert len(owners) == 1
        assert owners[0]["source_id"] and owners[0]["remediation"]


@settings(max_examples=100)
@given(items=catalogs(with_bad=False).filter(lambda x: len(x) > 0), data=st.data())
def test_p13_duplicate_and_undefined_fail(items, data):
    # Feature: governance-as-code-mvp, Property 13: Rule_Code join back to catalog and source
    doc = _clean(items)
    k = data.draw(st.integers(0, len(items) - 1))
    dup = {"control_id": "DUP", "status": "DRAFT", "rule_codes": [f"R{k}"],
           "spectral_rules": {f"R{k}": dict(_RULE)}}
    kinds = {e.kind for e in check({"a": doc, "b": {"items": [dup]}})}
    assert "duplicate_rule_code" in kinds
    undefined = {"control_id": "UND", "status": "DRAFT", "rule_codes": ["NOPE"]}
    kinds = {e.kind for e in check({"a": {"items": doc["items"] + [undefined]}})}
    assert "undefined_rule_code" in kinds
