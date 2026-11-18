"""Property tests 1, 2, 3, 5 for CALM app generation (task 20.2)."""
import copy
import json
import random
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from calm_generation import attributes as at, composer, pattern_library as pl
from calm_generation.placeholders import fill

ROOT = Path(__file__).resolve().parents[1]
SPEC = composer.load_spec(ROOT / "templates" / "RA03-LITE.compose.yaml")
PATTERNS = pl.load_patterns()
TEXT = (ROOT / "templates" / "RA03-LITE.json").read_text(encoding="utf-8")
TPL = json.loads(TEXT)
SAFE_TEXT = st.text(alphabet="abcdefghij klmnop-_", min_size=1, max_size=12).filter(lambda s: s.strip())


# ---------- helpers ----------
def _value(a, draw):
    t = a["type"]
    if t == "enum":
        return draw(st.sampled_from(a["allowed"]))
    if t == "boolean":
        return draw(st.booleans())
    if t in ("number", "integer"):
        lo = max(a.get("min", 0), 0)
        return draw(st.integers(min_value=lo, max_value=lo + 100000))
    return draw(SAFE_TEXT)


@st.composite
def valid_forms(draw):
    form = at.form_for(TPL, TEXT, "PUBLISHED")
    form["app"] = {"id": draw(st.from_regex(r"[a-z0-9][a-z0-9-]{1,20}", fullmatch=True)), "name": "App"}
    form["values"] = {a["name"]: _value(a, draw) for a in form["attributes"]}
    for o in form["options"]:
        keys = sorted(o["choices"])
        o["selected"] = draw(st.sampled_from(keys)) if o["type"] == "oneOf" else [draw(st.sampled_from(keys))]
    return form


def stub_generate(form):
    """What `calm generate` emits: consts kept, placeholders for free fields, enums omitted, every node."""
    nodes = []
    for d, _ in at.iter_node_defs(TPL):
        p = d["properties"]
        meta = {}
        for k, s in (p.get("metadata") or {}).get("properties", {}).items():
            if "const" in s:
                meta[k] = s["const"]
            elif "enum" not in s:
                meta[k] = at._placeholder(k, s)
        nodes.append({"unique-id": p["unique-id"]["const"], "node-type": p["node-type"]["const"],
                      "name": p["name"]["const"], "description": p["description"]["const"], "metadata": meta})
    return {"nodes": nodes, "relationships": [], "$schema": TPL["$id"]}


def walk(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)
    else:
        yield o


# ---------- Property 1 ----------
# Feature: governance-as-code-mvp, Property 1: Composer determinism
@settings(max_examples=100, deadline=None)
@given(seed=st.integers(0, 2**32), repeat=st.integers(1, 3))
def test_property_1_composer_determinism(seed, repeat):
    rng = random.Random(seed)
    base = composer.compose(PATTERNS, SPEC)
    assert base.ok
    for _ in range(repeat):
        keys = list(PATTERNS)
        rng.shuffle(keys)
        sel = list(SPEC["patterns"])
        rng.shuffle(sel)
        r = composer.compose({k: copy.deepcopy(PATTERNS[k]) for k in keys}, {**SPEC, "patterns": sel})
        assert r.ok and r.text == base.text and r.text.encode() == base.text.encode()


# ---------- Property 2 ----------
# Feature: governance-as-code-mvp, Property 2: Composer conflict rejection
@settings(max_examples=100, deadline=None)
@given(value=st.text(alphabet="abcdefxyz", min_size=1, max_size=8), seed=st.integers(0, 2**32))
def test_property_2_composer_conflict_rejection(value, seed):
    pats = copy.deepcopy(PATTERNS)
    p12 = pats["P12"]["properties"]["nodes"]["prefixItems"][0]["properties"]["metadata"]["properties"]["privilege"]
    new = {"enum": [f"zz-{value}"]}
    assume_diff = new != p12
    assert assume_diff
    pats["P14"]["properties"]["nodes"]["prefixItems"][0]["properties"]["metadata"]["properties"]["privilege"] = new
    sel = list(SPEC["patterns"])
    random.Random(seed).shuffle(sel)
    r = composer.compose(pats, {**SPEC, "patterns": sel})
    assert not r.ok and r.text is None and r.template is None
    assert r.conflicts
    assert any(c.key == "metadata.privilege" and set(c.patterns) == {"P12", "P14"} for c in r.conflicts)
    assert all("P12" in str(c) and "P14" in str(c) for c in r.conflicts if c.key == "metadata.privilege")


# ---------- Property 5 ----------
# Feature: governance-as-code-mvp, Property 5: Invalid attributes block instantiation
@settings(max_examples=100, deadline=None)
@given(form=valid_forms(), data=st.data())
def test_property_5_invalid_attributes_are_reported(form, data):
    assert at.validate(form, TPL, TEXT) == []
    attrs = form["attributes"]
    kind = data.draw(st.sampled_from(["missing", "disallowed", "type", "uncovered", "unknown"]))
    f = copy.deepcopy(form)
    if kind == "missing":
        a = data.draw(st.sampled_from([a for a in attrs if a["required"]]))
        del f["values"][a["name"]]
    elif kind == "disallowed":
        a = data.draw(st.sampled_from([a for a in attrs if a["type"] == "enum"]))
        f["values"][a["name"]] = "not-" + data.draw(SAFE_TEXT)
    elif kind == "type":
        a = data.draw(st.sampled_from([a for a in attrs if a["type"] in ("boolean", "number", "integer", "string")]))
        f["values"][a["name"]] = [1] if a["type"] == "string" else "wrong"
    elif kind == "uncovered":
        a = data.draw(st.sampled_from(attrs))
        f["attributes"] = [x for x in f["attributes"] if x["name"] != a["name"]]
        f["values"].pop(a["name"], None)
    else:
        a = {"name": "NOT_A_FIELD"}
        f["values"]["NOT_A_FIELD"] = 1
    errs = at.validate(f, TPL, TEXT)
    assert a["name"] in {e.field for e in errs}


@settings(max_examples=100, deadline=None)
@given(status=st.sampled_from(["DRAFT", "CANDIDATE", "RETIRED", "draft", ""]))
def test_property_5_non_published_template_refused(status):
    with pytest.raises(at.TemplateNotPublished):
        at.form_for(TPL, TEXT, status)


# ---------- Property 3 ----------
# Feature: governance-as-code-mvp, Property 3: Generate and fill leaves no placeholder
@settings(max_examples=100, deadline=None)
@given(form=valid_forms())
def test_property_3_fill_leaves_no_placeholder(form):
    assert at.validate(form, TPL, TEXT) == []
    r = fill(stub_generate(form), form, TPL)
    assert r.model is not None and r.leftovers == []
    for v in walk(r.model):
        assert not (isinstance(v, str) and v.startswith("[[") and v.endswith("]]"))
        assert not (isinstance(v, (int, float)) and not isinstance(v, bool) and v == -1)
    assert r.model["$schema"] == "https://calm.finos.org/release/1.2/meta/calm.json"


@settings(max_examples=100, deadline=None)
@given(form=valid_forms(), data=st.data())
def test_property_3_uncovered_placeholder_reported_with_path(form, data):
    cand = [a for a in form["attributes"] if a["type"] != "enum" or a["required"]]
    a = data.draw(st.sampled_from(cand))
    f = copy.deepcopy(form)
    del f["values"][a["name"]]
    r = fill(stub_generate(f), f, TPL)
    assert r.model is None and r.leftovers
    suffix = f".metadata.{a['target']['field']}"
    assert any(l.json_path.startswith("$.nodes[") and l.json_path.endswith(suffix) for l in r.leftovers)
