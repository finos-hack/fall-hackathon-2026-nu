import json

from agip_shared.gateway import ModelGateway, Recorder
from governance_execution.store.repository import MemoryRepository
from governance_execution.units.rule_authoring import extract_and_store

GOOD = {
    "kind": "risk",
    "triggers": [{"dimension": "autonomy", "condition": "agent autonomous"}],
    "likelihood": {"score": 4, "criteria": "c"}, "impact": {"score": 5, "criteria": "c"},
    "remediation": "Require approval.",
    "candidate_rule": {"rule_code": "risk-agent-autonomous", "description": "d", "severity": "error",
                       "given": "$.nodes[*].metadata", "then": {"function": "pattern", "field": "autonomy"}},
}


class RT:
    def __init__(self, out):
        self.out = out

    def complete(self, *a):
        return json.dumps(self.out)


def test_extract_stores_draft_and_rejects_invalid(tmp_path):
    src = tmp_path / "ri-10_x.md"
    src.write_text("---\ntitle: T\n---\n\nProse body.", encoding="utf-8")
    repo = MemoryRepository(tmp_path / "data")
    ok = extract_and_store(repo, ModelGateway("bedrock", "m", "r", Recorder(tmp_path / "rec"), RT(GOOD)),
                           framework="AIGF", native_id="ri-10", title="T", source_path=str(src))
    assert ok.ok
    item = repo.get_catalog_item("AIGF-RI-010")
    assert item["status"] == "DRAFT" and item["kind"] == "risk_rule"

    bad = extract_and_store(repo, ModelGateway("bedrock", "m", "r", Recorder(tmp_path / "rec2"), RT({"kind": "risk"})),
                            framework="AIGF", native_id="ri-11", title="T", source_path=str(src))
    assert not bad.ok and repo.get_catalog_item("AIGF-RI-011") is None
