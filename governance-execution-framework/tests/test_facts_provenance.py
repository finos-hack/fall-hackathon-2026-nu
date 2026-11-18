"""Task 23.1: facts keep full provenance and the raw value survives every mapping/classification path."""
import json

from hypothesis import given, settings, strategies as st

from agip_shared.contracts import Fact
from governance_execution.adapters.decider import DeciderGateway, classify_unmapped
from governance_execution.core import acceptance, facts as fx

TAX = fx.load_taxonomy()
POLICY = acceptance.load_policy()
APP = {"nodes": [
    {"unique-id": "pay", "node-type": "ai:agent", "metadata": {"autonomy": "supervised"}},
    {"unique-id": "db", "node-type": "database", "description": "Invoices", "metadata": {"data_classification": "supplier-financial"}},
]}


def test_fact_carries_required_fields():
    fs = fx.extract(APP, TAX)
    for f in fs.facts:
        assert f.id == f"{f.element_id}.{f.attribute}"
        assert f.json_path.startswith("$.nodes[") and f.attribute and f.taxonomy_version == "1"
        assert f.mapping_status in {"MAPPED", "UNMAPPED", "UNKNOWN"}
        assert f.extraction_method in {"taxonomy_mapping", "taxonomy_absent"}
        assert f.provenance["app_model_sha256"] == fs.app_model_sha256
    unknown = next(f for f in fs.facts if f.mapping_status == "UNKNOWN")
    assert unknown.extraction_method == "taxonomy_absent" and unknown.raw is None


raw_values = st.one_of(st.text(max_size=30), st.integers(), st.booleans(), st.lists(st.text(max_size=5), max_size=3))


@settings(max_examples=100, deadline=None)
@given(raw=raw_values, label=st.sampled_from(["public", "internal", "confidential", "restricted"]))
def test_raw_survives_mapping_and_classification(raw, label):
    app = {"nodes": [{"unique-id": "db", "node-type": "database", "metadata": {"data_classification": raw}}]}
    fs = fx.extract(app, TAX)
    f = next(x for x in fs.facts if x.attribute == "data_classification")
    assert f.raw == raw
    # Decider-accepted path (same update the gateway applies): raw is untouched, classification is referenced.
    inferred = f.model_copy(update={"decider_label": label, "decider_outcome": "ACCEPTED", "mapping_status": "INFERRED",
                                    "normalized": label, "extraction_method": "decider_classification",
                                    "classification_ref": f.id})
    assert inferred.raw == raw and inferred.json_path == f.json_path and inferred.id == f.id
    # Every other outcome path keeps raw as well.
    for outcome in ("ABSTAIN", "HUMAN_REVIEW", "UNKNOWN"):
        assert f.model_copy(update={"decider_outcome": outcome}).raw == raw


def test_gateway_classification_keeps_raw_and_sets_reference(tmp_path):
    def run(gw):
        return classify_unmapped(gw, fx.extract(APP, TAX).facts, TAX, set(), {"db": "Invoices"}, "t1")

    _, audits = run(DeciderGateway(POLICY, "fixture", model="m", fixtures_dir=tmp_path))
    (tmp_path / f"{audits[0]['input_hash']}.json").write_text(json.dumps(
        {"model": "m", "answers": [{"choice": "confidential", "confidence": 0.9,
                                    "probabilities": {"confidential": 0.9, "internal": 0.05}}], "usage": {}}))
    facts, _ = run(DeciderGateway(POLICY, "fixture", model="m", fixtures_dir=tmp_path))
    f: Fact = next(x for x in facts if x.attribute == "data_classification")
    assert f.raw == "supplier-financial" and f.mapping_status == "INFERRED"
    assert f.extraction_method == "decider_classification" and f.classification_ref == "db.data_classification"
