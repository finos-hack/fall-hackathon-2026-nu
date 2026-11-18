"""Option B (Accepted Classification) properties 1-7, task 23.3. Fixture/fake provider only; no live Decider or Bedrock."""
import json

from hypothesis import given, settings, strategies as st

from agip_shared.contracts import FactSet
from governance_execution.adapters.decider import DeciderGateway, classify_unmapped
from governance_execution.core import acceptance, facts as fx
from governance_execution.units import risk_assessment as ra

TAX = fx.load_taxonomy()
POLICY = acceptance.load_policy()
TASK = POLICY["tasks"]["classify_attribute"]
VALUES = sorted(set(TAX["attributes"]["data_classification"]["values"].values()))
APP = {"nodes": [{"unique-id": "db", "node-type": "database", "description": "Invoices",
                  "metadata": {"data_classification": "supplier-financial"}}]}
P = settings(max_examples=100, deadline=None)

prob = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
answers = st.fixed_dictionaries({"choice": st.sampled_from(VALUES + ["bogus"]), "confidence": prob,
                                 "probabilities": st.dictionaries(st.sampled_from(VALUES), prob, min_size=1, max_size=4)})


class Fake(DeciderGateway):
    def __init__(self, resp, policy=POLICY):
        super().__init__(policy, "fixture", model="m")
        self.resp = resp

    def _call(self, h, state, question):
        if isinstance(self.resp, Exception):
            raise self.resp
        return {"model": "m", "answers": [self.resp]}


def run(resp, policy=POLICY):
    fs = fx.extract(APP, TAX)
    facts, audits = classify_unmapped(Fake(resp, policy), fs.facts, TAX, set(), {"db": "Invoices"}, "t")
    return fs, facts[0], audits[0]


def accepted(ans):
    return (ans["choice"] in VALUES and ans["confidence"] >= TASK["min_confidence"]
            and acceptance.top2_margin(ans["probabilities"]) >= TASK["min_top2_margin"])


# Feature: governance-as-code-mvp, Property 7.1: accepted keeps original and full provenance
@P
@given(ans=answers.filter(accepted))
def test_accepted_keeps_original_and_provenance(ans):
    _, f, audit = run(ans)
    c = audit["classification"]
    assert f.mapping_status == "INFERRED" and f.raw == "supplier-financial" and f.normalized == ans["choice"]
    assert c["original_raw"] == f.raw and c["normalized"] == ans["choice"] and c["answer"] == ans
    for k in ("model", "input_hash", "policy_version", "timestamp", "confidence", "margin", "provenance"):
        assert c[k] not in (None, "", {}), k
    assert c["input_hash"] == audit["input_hash"] and c["policy_version"] == str(POLICY["version"])


# Feature: governance-as-code-mvp, Property 7.2: Decider cannot set likelihood, impact, severity, control status, gates or decision
@P
@given(ans=answers)
def test_decider_cannot_set_scores_or_decision(ans):
    fs, f, audit = run(ans)
    forbidden = {"likelihood", "impact", "severity", "control_status", "gates", "decision"}
    assert not forbidden & set(type(f).model_fields) and not forbidden & set(audit.get("classification", {}))
    assert {k: v for k, v in f.model_dump().items() if k not in ("mapping_status", "normalized", "decider_label", "decider_outcome", "extraction_method", "classification_ref")} == \
           {k: v for k, v in fs.facts[0].model_dump().items() if k not in ("mapping_status", "normalized", "decider_label", "decider_outcome", "extraction_method", "classification_ref")}


# Feature: governance-as-code-mvp, Property 7.3: accepted facts take part in risk applicability like mapped facts
@P
@given(label=st.sampled_from(VALUES))
def test_accepted_facts_feed_risk_inputs(label):
    ans = {"choice": label, "confidence": 0.95, "probabilities": {label: 0.95, "x": 0.01}}
    fs, f, _ = run(ans)
    inferred = ra.approval_tier_inputs(APP, FactSet(facts=[f]))
    mapped = ra.approval_tier_inputs(APP, FactSet(facts=[f.model_copy(update={"mapping_status": "MAPPED", "raw": label})]))
    assert inferred["data_access"] == mapped["data_access"] and "data_unclassified" not in inferred
    assert ra.approval_tier_inputs(APP, fs)["data_access"] == 4 and ra.approval_tier_inputs(APP, fs)["data_unclassified"]


# Feature: governance-as-code-mvp, Property 7.4: unaccepted facts stay UNKNOWN/UNMAPPED (no risk-reducing default)
@P
@given(ans=answers.filter(lambda a: not accepted(a)))
def test_unaccepted_stay_unmapped(ans):
    fs, f, audit = run(ans)
    assert f.mapping_status == "UNMAPPED" and f.normalized is None and f.decider_label is None and "classification" not in audit
    assert ra.approval_tier_inputs(APP, FactSet(facts=[f]))["data_access"] == 4


# Feature: governance-as-code-mvp, Property 7.5: thresholds applied exactly
@P
@given(conf=prob, top=prob, second=prob, mc=prob, mm=prob)
def test_thresholds_exact(conf, top, second, mc, mm):
    hi, lo = max(top, second), min(top, second)
    task = {**TASK, "min_confidence": mc, "min_top2_margin": mm}
    ans = {"choice": VALUES[0], "confidence": conf, "probabilities": {"a": hi, "b": lo}}
    assert (acceptance.evaluate(task, ans) == "ACCEPTED") == (conf >= mc and hi - lo >= mm)
    assert acceptance.evaluate(task, ans) == acceptance.evaluate(task, ans)


# Feature: governance-as-code-mvp, Property 7.6: missing/invalid/failed answers are never accepted
@P
@given(bad=st.one_of(st.none(), st.text(max_size=5), st.integers(), st.just({}), st.just({"choice": ""}),
                     st.just({"choice": VALUES[0]}), st.just({"choice": VALUES[0], "confidence": float("nan"), "probabilities": {"a": 1}}),
                     st.just(OSError("down")), st.just(TimeoutError("slow"))),
       on_fail=st.sampled_from(["ABSTAIN", "HUMAN_REVIEW"]))
def test_bad_answers_never_accepted(bad, on_fail):
    policy = {**POLICY, "tasks": {**POLICY["tasks"], "classify_attribute": {**TASK, "on_fail": on_fail}}}
    _, f, audit = run(bad, policy)
    assert f.mapping_status == "UNMAPPED" and f.normalized is None and "classification" not in audit
    assert f.decider_outcome in ("UNKNOWN", "HUMAN_REVIEW")


# Feature: governance-as-code-mvp, Property 7.7: replay with the same policy gives the same FactSet and downstream result
@P
@given(ans=answers)
def test_replay_same_factset_and_result(ans):
    def once():
        fs = fx.extract(APP, TAX)
        facts, audits = classify_unmapped(Fake(ans), fs.facts, TAX, set(), {"db": "Invoices"}, "t")
        for a in audits:
            if a.get("classification"):
                a["classification"].pop("timestamp")
        return facts, [a.get("classification") for a in audits], ra.approval_tier_inputs(APP, FactSet(facts=facts))
    assert json.dumps(once(), default=str, sort_keys=True) == json.dumps(once(), default=str, sort_keys=True)