"""Property tests 9.2, 9.4, 9.6, 9.7 (facts, acceptance, Input_Hash, provider failures)."""
import math
import subprocess
import urllib.error

from hypothesis import given, settings, strategies as st

from agip_shared.hashing import input_hash
from governance_execution.adapters.calm import CalmAdapter
from governance_execution.adapters.decider import DeciderGateway
from governance_execution.adapters.spectral import SpectralAdapter
from governance_execution.core import acceptance, facts as fx

TAX = fx.load_taxonomy()
POLICY = acceptance.load_policy()
CHOICE = POLICY["tasks"]["classify_attribute"]
NOUL = POLICY["tasks"]["attribute_is_sensitive"]
KNOWN_AUTONOMY = {str(k).lower() for k in TAX["attributes"]["autonomy"]["values"]}

json_scalars = st.one_of(st.none(), st.booleans(), st.integers(), st.floats(allow_nan=True, allow_infinity=True), st.text(max_size=20))
json_values = st.recursive(json_scalars, lambda c: st.lists(c, max_size=3) | st.dictionaries(st.text(max_size=5), c, max_size=3), max_leaves=8)


# Feature: governance-as-code-mvp, Property 6: UNMAPPED retention
@settings(max_examples=100)
@given(raw=st.one_of(st.text(max_size=30), st.integers(), st.lists(st.text(max_size=5), max_size=3)).filter(
    lambda v: not (isinstance(v, str) and v.strip().lower() in KNOWN_AUTONOMY)))
def test_property_6_unmapped_retention(raw):
    app = {"nodes": [{"unique-id": "a1", "node-type": "ai:agent", "metadata": {"autonomy": raw}}]}
    fs = fx.extract(app, TAX)
    hits = [f for f in fs.facts if f.element_id == "a1" and f.attribute == "autonomy"]
    assert len(hits) == 1
    assert hits[0].mapping_status == "UNMAPPED" and hits[0].raw == raw and hits[0].normalized is None
    assert hits[0] in fx.unmapped(fs)


# Feature: governance-as-code-mvp, Property 8: Acceptance policy correctness
prob = st.floats(min_value=0.0, max_value=1.0)


@settings(max_examples=100)
@given(conf=prob, probs=st.lists(prob, min_size=1, max_size=5), on_fail=st.sampled_from(["ABSTAIN", "HUMAN_REVIEW"]))
def test_property_8_choice_and_score(conf, probs, on_fail):
    s = sorted(probs, reverse=True)
    margin = s[0] - (s[1] if len(s) > 1 else 0.0)
    for typ, key in (("choice", "choice"), ("score", "score")):
        task = {**CHOICE, "type": typ, "on_fail": on_fail}
        ans = {key: "x", "confidence": conf, "probabilities": {f"c{i}": p for i, p in enumerate(probs)}}
        ok = conf >= task["min_confidence"] and margin >= task["min_top2_margin"]
        assert acceptance.evaluate(task, ans) == ("ACCEPTED" if ok else on_fail)


@settings(max_examples=100)
@given(v=prob, conf=st.one_of(st.none(), prob))
def test_property_8_noul_ignores_confidence(v, conf):
    ans = {"noul": v} if conf is None else {"noul": v, "confidence": conf}
    expected = "ACCEPTED" if v >= NOUL["accept_high"] or v <= NOUL["accept_low"] else "ABSTAIN"
    assert acceptance.evaluate(NOUL, ans) == expected


@settings(max_examples=100)
@given(answer=json_values, task=st.sampled_from([CHOICE, NOUL]))
def test_property_8_invalid_never_accepted(answer, task):
    # Arbitrary junk is not accepted unless it is a well-formed answer that meets the thresholds.
    res = acceptance.evaluate(task, answer)
    if res == "ACCEPTED":
        assert isinstance(answer, dict)
        if task["type"] == "noul":
            v = answer.get("noul")
            assert isinstance(v, (int, float)) and not isinstance(v, bool) and not math.isnan(v)
            assert v >= task["accept_high"] or v <= task["accept_low"]
        else:
            assert answer.get("choice") not in (None, "") and isinstance(answer.get("confidence"), (int, float))


@settings(max_examples=100)
@given(drop=st.sampled_from(["choice", "confidence", "probabilities"]), bad=st.sampled_from([None, "x", float("nan"), float("inf")]))
def test_property_8_missing_or_undeterminable(drop, bad):
    ok = {"choice": "c", "confidence": 0.99, "probabilities": {"c": 0.99, "d": 0.01}}
    assert acceptance.evaluate(CHOICE, ok) == "ACCEPTED"
    assert acceptance.evaluate(CHOICE, {k: v for k, v in ok.items() if k != drop}) != "ACCEPTED"
    if drop != "choice" or bad is None:
        assert acceptance.evaluate(CHOICE, {**ok, drop: bad}) != "ACCEPTED"


# Feature: governance-as-code-mvp, Property 9: Input_Hash stability
def _shuffled(o):
    if isinstance(o, dict):
        return {k: _shuffled(o[k]) for k in reversed(list(o))}
    return [_shuffled(x) for x in o] if isinstance(o, list) else o


json_safe = st.recursive(st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=8)),
                         lambda c: st.lists(c, max_size=3) | st.dictionaries(st.text(max_size=5), c, max_size=3), max_leaves=8)
questions = st.lists(st.dictionaries(st.text(min_size=1, max_size=5), json_safe, min_size=1, max_size=3), max_size=3)


@settings(max_examples=100)
@given(model=st.text(max_size=10), state=st.text(max_size=40), qs=questions)
def test_property_9_input_hash_stability(model, state, qs):
    h = input_hash(model, state, qs)
    assert h == input_hash(model, state, qs) == input_hash(model, state, _shuffled(qs))
    assert h != input_hash(model + "x", state, qs)
    assert h != input_hash(model, state + "x", qs)
    assert h != input_hash(model, state, qs + [{"extra": 1}])


@settings(max_examples=100)
@given(raw=st.text(min_size=1, max_size=20), model=st.text(max_size=8))
def test_property_9_cache_hit_makes_no_second_call(raw, model):
    calls = []

    def post(url, body, timeout):
        calls.append(body)
        return {"answers": [{"choice": "c", "confidence": 0.95, "probabilities": {"c": 0.95, "d": 0.05}}], "model": model}

    gw = DeciderGateway(POLICY, provider="http", base_url="http://decider.invalid", model=model, post=post)
    q = {"type": "choice", "id": "n.a", "choices": ["c", "d"]}
    fields = {"element_id": "n", "attribute_name": "a", "raw_value": raw}
    r1, a1 = gw.classify("classify_attribute", q, fields)
    r2, a2 = gw.classify("classify_attribute", q, fields)
    assert len(calls) == 1 and not a1["cache_hit"] and a2["cache_hit"] and a2["input_hash"] == a1["input_hash"]
    assert r2.outcome == r1.outcome and r2.answer == r1.answer


# Feature: governance-as-code-mvp, Property 10: Provider failures never escape
excs = st.sampled_from([urllib.error.URLError("down"), TimeoutError("t"), OSError("o"), ValueError("v"),
                        ConnectionResetError("r"), RuntimeError("x"), KeyError("k")])
garbage = st.text(alphabet="abcdefg xyz:.,{}\n", max_size=60)  # no '[' so never a JSON array


@settings(max_examples=100)
@given(exc=excs, junk=st.one_of(st.none(), st.integers(), st.text(max_size=10), st.lists(st.integers(), max_size=3),
                                st.dictionaries(st.text(max_size=4), st.integers(), max_size=3)))
def test_property_10_decider_failures(exc, junk):
    def boom(url, body, timeout):
        raise exc

    q = {"type": "choice", "id": "n.a", "choices": ["c"]}
    f = {"element_id": "n", "attribute_name": "a", "raw_value": "v"}
    res, audit = DeciderGateway(POLICY, "http", "http://x.invalid", "m", post=boom).classify("classify_attribute", q, f)
    assert res.outcome == "ERROR" and res.answer is None and res.error and audit["outcome"] == "ERROR"
    res2, _ = DeciderGateway(POLICY, "http", "http://x.invalid", "m", post=lambda *a: junk).classify("classify_attribute", q, f)
    assert res2.outcome != "ACCEPTED" and res2.answer is None


def _runner_for(kind, exc, out, code):
    def runner(args, timeout, cwd):
        if kind == "raise":
            raise exc
        return code, out, ""
    return runner


fail_exc = st.sampled_from([FileNotFoundError("nope"), subprocess.TimeoutExpired("x", 1), OSError("o"), PermissionError("p"),
                            RuntimeError("r")])


@settings(max_examples=100)
@given(kind=st.sampled_from(["raise", "garbage"]), exc=fail_exc, out=garbage, code=st.integers(-2, 3))
def test_property_10_calm_failures(kind, exc, out, code):
    a = CalmAdapter(runner=_runner_for(kind, exc, out, code))
    arch = {"nodes": []}
    for v in (a.validate(arch), a.validate(arch, {"p": 1}), a.validate_pattern({"p": 1})):
        assert v.status == "ERROR" and v.error
    assert a.generate({"p": 1}).status == "ERROR"


@settings(max_examples=100)
@given(kind=st.sampled_from(["raise", "garbage"]), exc=fail_exc, out=garbage, code=st.integers(-2, 3))
def test_property_10_spectral_failures(kind, exc, out, code):
    run = SpectralAdapter(runner=_runner_for(kind, exc, out, code)).lint({"nodes": []}, "ruleset.yaml")
    assert run.status == "ERROR" and run.error and run.results == []
