from rule_authoring.coverage import build, load_sources


def test_build_counts_per_state():
    src = [
        {"framework": "AIGF", "id": "ri-1", "kind": "risk", "title": "a"},
        {"framework": "AIGF", "id": "ri-2", "kind": "risk", "title": "b"},
        {"framework": "AIGF", "id": "ri-3", "kind": "risk", "title": "c"},
        {"framework": "AIGF", "id": "ri-4", "kind": "risk", "title": "d"},
        {"framework": "AIGF", "id": "mi-1", "kind": "mitigation", "title": "m"},
        {"framework": "CCC", "id": "C.CN01", "kind": "control", "title": "x"},
        {"framework": "CCC", "id": "C.CP01", "kind": "capability", "title": "skip"},
    ]
    cats = [
        {"risk_id": "R1", "status": "APPROVED", "rule_codes": ["r-one"], "source": {"id": "ri-1"}},
        {"risk_id": "R2", "status": "IN_REVIEW", "rule_codes": ["r-two"], "source": {"id": "ri-2"}},
    ]
    drafts = [{"status": "DRAFT", "inexpressible_reason": "no check", "source": {"id": "ri-3"}}]
    rep = build(src, drafts, cats)
    assert len(rep["rows"]) == 6
    assert rep["counts"] == {"APPROVED rule": 1, "IN_REVIEW": 1, "not expressible": 1,
                             "non-executable (stored)": 1, "missing extraction": 2}


def test_real_sources_have_24_aigf_risks():
    rep = build(load_sources(), [], [])
    assert sum(1 for r in rep["rows"] if r["framework"] == "AIGF" and r["kind"] == "risk") == 24
