import pytest

from rule_authoring import compile as cc
from rule_authoring import knowledge as k

RULE = {"R-1": {"description": "d", "message": "m", "severity": "error", "given": "$.x",
                "then": {"field": "f", "function": "truthy"}}}


def test_thirteen_types():
    assert len(k.KnowledgeType) == 13
    assert k.EXECUTABLE_TYPES == {k.KnowledgeType.CONTROL, k.KnowledgeType.RISK}
    assert k.EXECUTABLE_TYPES.isdisjoint(k.NON_EXECUTABLE_TYPES)


def test_legacy_items_infer_type():
    assert k.item_type({"control_id": "C"}) is k.KnowledgeType.CONTROL
    assert k.item_type({"risk_id": "R"}) is k.KnowledgeType.RISK
    with pytest.raises(ValueError):
        k.item_type({"id": "x"})
    with pytest.raises(ValueError):
        k.item_type({"id": "x", "type": "bogus"})


def test_non_executable_stored_never_compiled_and_reported():
    items = [{"control_id": "C1", "status": "APPROVED", "rule_codes": ["R-1"], "spectral_rules": RULE}]
    stored = [{"id": f"K-{t.value}", "type": t.value, "status": "APPROVED",
               "rule_codes": ["R-1"], "spectral_rules": RULE} for t in k.NON_EXECUTABLE_TYPES]
    cat = {"catalog": "controls", "version": 1, "items": items + stored}
    out = cc.compile_catalog(cat, "controls")
    assert out.rule_codes == ("R-1",) and not out.unexpressible
    assert set(out.non_executable) == {s["id"] for s in stored}
    assert {i["id"] for i in k.non_executable(cat["items"])} == {s["id"] for s in stored}
    assert k.executable(cat["items"]) == items
    only = cc.compile_catalog({"catalog": "controls", "version": 1, "items": stored}, "controls")
    assert only.rule_codes == ()
