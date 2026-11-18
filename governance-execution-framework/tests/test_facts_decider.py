import json

from governance_execution.adapters.decider import DeciderGateway, build_state, classify_unmapped, select_for_decider
from governance_execution.core import acceptance, facts as fx

TAX = fx.load_taxonomy()
POLICY = acceptance.load_policy()
APP = {"nodes": [
    {"unique-id": "pay", "node-type": "ai:agent", "metadata": {"autonomy": "supervised", "privilege": "restricted-write",
                                                              "permitted_tools": "payment-tool"}},
    {"unique-id": "db", "node-type": "database", "description": "Invoices", "metadata": {"data_classification": "supplier-financial"}},
]}


def test_facts_mapped_unmapped_unknown_with_provenance():
    fs = fx.extract(APP, TAX)
    by = {(f.element_id, f.attribute): f for f in fs.facts}
    assert by[("pay", "autonomy")].mapping_status == "MAPPED" and by[("pay", "autonomy")].json_path == "$.nodes[0].metadata.autonomy"
    assert by[("db", "data_classification")].mapping_status == "UNMAPPED" and by[("db", "data_classification")].raw == "supplier-financial"
    assert by[("pay", "decision_impact")].mapping_status == "UNKNOWN"
    assert fx.agent_facts(fs)["pay"] == {"autonomy": "supervised", "privilege": "restricted-write", "permitted_tools": "payment-tool"}
    assert fs.taxonomy_version == "1" and fs.app_model_sha256 and fx.extract(APP, TAX) == fs


def test_acceptance_policy():
    choice = POLICY["tasks"]["classify_attribute"]
    noul = POLICY["tasks"]["attribute_is_sensitive"]
    ok = {"choice": "confidential", "confidence": 0.9, "probabilities": {"confidential": 0.85, "internal": 0.1}}
    assert acceptance.evaluate(choice, ok) == "ACCEPTED"
    assert acceptance.evaluate(choice, {**ok, "confidence": 0.5}) == "ABSTAIN"
    assert acceptance.evaluate(choice, {**ok, "probabilities": {"a": 0.5, "b": 0.45}}) == "ABSTAIN"
    assert acceptance.evaluate(choice, {"choice": "x", "probabilities": {"a": 1}}) == "ABSTAIN"  # no confidence
    assert acceptance.evaluate(choice, None) == "ABSTAIN"
    assert acceptance.evaluate(noul, {"noul": 0.95}) == "ACCEPTED" and acceptance.evaluate(noul, {"noul": 0.05}) == "ACCEPTED"
    assert acceptance.evaluate(noul, {"noul": 0.5, "confidence": 1.0}) == "ABSTAIN"


def test_state_builder_limits_and_scrubs():
    s = build_state({"element_id": "db", "attribute_name": "x", "raw_value": "C:\\secret\\f.txt",
                     "description": "d" * 5000}, POLICY)
    assert len(s) <= 4000 and "C:\\secret" not in s and s.startswith("element_id: db")


def test_only_unmapped_without_deterministic_check_selected():
    fs = fx.extract(APP, TAX).facts
    assert [f.attribute for f in select_for_decider(fs, set())] == ["data_classification"]
    assert select_for_decider(fs, {"data_classification"}) == []


def _run(gw):
    return classify_unmapped(gw, fx.extract(APP, TAX).facts, TAX, set(), {"db": "Invoices"}, "t1")


def test_unavailable_and_fixture_missing_record_unknown(tmp_path):
    def down(url, body, timeout):
        raise OSError("connection refused")

    facts, audits = _run(DeciderGateway(POLICY, "http", "http://x", "m", 1, tmp_path, down))
    f = next(f for f in facts if f.attribute == "data_classification")
    assert f.decider_outcome == "UNKNOWN" and f.decider_label is None and audits[0]["error"].startswith("unavailable")
    facts, audits = _run(DeciderGateway(POLICY, "fixture", fixtures_dir=tmp_path))
    assert audits[0]["error"] == "fixture_missing"


def test_fixture_answer_accepted_and_cached(tmp_path):
    gw = DeciderGateway(POLICY, "fixture", model="m", fixtures_dir=tmp_path)
    _, audits = _run(gw)
    (tmp_path / f"{audits[0]['input_hash']}.json").write_text(json.dumps(
        {"model": "m", "answers": [{"choice": "confidential", "confidence": 0.9,
                                    "probabilities": {"confidential": 0.9, "internal": 0.05}}], "usage": {}}))
    gw = DeciderGateway(POLICY, "fixture", model="m", fixtures_dir=tmp_path)
    facts, audits = _run(gw)
    f = next(f for f in facts if f.attribute == "data_classification")
    assert f.decider_label == "confidential" and f.decider_outcome == "ACCEPTED" and f.mapping_status == "INFERRED"
    assert f.raw == "supplier-financial" and f.normalized == "confidential" and audits[0]["classification"]["original_raw"] == "supplier-financial"
    _, again = _run(gw)
    assert again[0]["cache_hit"] is True
