import pytest

from agip_shared.gateway import ModelGateway, Recorder
from rule_authoring import extraction as ex

GOOD = {
    "kind": "control",
    "triggers": [{"dimension": "autonomy", "condition": "agent acts without approval"}],
    "likelihood": {"score": 4, "criteria": "common"},
    "impact": {"score": 5, "criteria": "payments"},
    "remediation": "Route through the approval service.",
    "candidate_rule": {"rule_code": "ctl-payment-requires-approval", "description": "d", "severity": "error",
                       "given": "$.nodes[*].metadata", "then": {"field": "approval", "function": "truthy"}},
}


class RT:
    def __init__(self, out):
        self.out = out

    def complete(self, prompt, model, region):
        import json
        return json.dumps(self.out)


def gw(tmp_path, out):
    return ModelGateway("bedrock", "m", "r", Recorder(tmp_path), RT(out))


def run(g, **kw):
    return ex.extract(g, framework="AIGF", native_id="mi-6", title="HITL", prose="prose /etc/x", **kw)


def test_valid_extraction_is_draft(tmp_path):
    r = run(gw(tmp_path, GOOD))
    assert r.ok and r.item["status"] == "DRAFT" and r.item["id"] == "AIGF-MI-006" and r.item["kind"] == "control_rule"
    assert r.record.prompt_version == "v1" and r.record.model == "m" and r.record.input_hash


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(likelihood={"score": 9, "criteria": "x"}),
    lambda d: d.pop("remediation"),
    lambda d: d.update(triggers=[]),
    lambda d: d["candidate_rule"]["then"].update(function="evalJs"),
    lambda d: d["candidate_rule"].update(given="nodes"),
])
def test_schema_invalid_rejected_with_reason(tmp_path, mutate):
    import copy
    bad = copy.deepcopy(GOOD)
    mutate(bad)
    r = run(gw(tmp_path, bad))
    assert not r.ok and r.item is None and "AIGF-MI-006" in r.reason


def test_aigf_rule_code_is_assigned_by_code_not_model(tmp_path):
    import copy
    out = copy.deepcopy(GOOD)
    out["candidate_rule"]["rule_code"] = "Bad_Code"   # model's name is ignored for AIGF
    r = run(gw(tmp_path, out))
    assert r.ok and r.item["body"]["extraction"]["candidate_rule"]["rule_code"] == ex.rule_code_for("AIGF", "mi-6", "control")
    assert ex.rule_code_for("AIGF", "ri-999", "risk") == "risk-aigf-ri-999"


def test_non_object_rejected(tmp_path):
    class T:
        def complete(self, *a):
            return "not json"

    r = run(ModelGateway("bedrock", "m", "r", Recorder(tmp_path), T()))
    assert not r.ok and "not a JSON object" in r.reason


def test_replay_reproduces_item(tmp_path):
    live = run(gw(tmp_path, GOOD))
    rep = run(ModelGateway("replay", recorder=Recorder(tmp_path)))
    assert rep.item == live.item


def test_item_keys():
    assert ex.item_key("AIGF", "ri-10") == "AIGF-RI-010"
    assert ex.item_key("CCC", "CCC.Core.CN01") == "CCC.Core.CN01"
