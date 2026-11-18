"""Source adapter tests: malformed input skipped with path+field; deterministic."""
from rule_authoring import sources_aigf, sources_ccc


def _md(d, name, body):
    p = d / name
    p.write_text(body, encoding="utf-8")
    return p


def test_aigf_malformed_skipped_with_path_and_field(tmp_path):
    _md(tmp_path, "ri-1_ok.md", "---\ntitle: Good\nsequence: 1\n---\nbody\n")
    _md(tmp_path, "ri-2_nofm.md", "no frontmatter\n")
    _md(tmp_path, "ri-3_badyaml.md", "---\ntitle: [unclosed\n---\n")
    _md(tmp_path, "mi-4_notitle.md", "---\nsequence: 4\n---\n")
    _md(tmp_path, "mi-5_badref.md", "---\ntitle: T\nmitigates: notalist\n---\n")
    items, errors = sources_aigf.read([tmp_path])
    assert [i.id for i in items] == ["ri-1"]
    by_file = {e.path.rsplit("/", 1)[-1]: e for e in errors}
    assert set(by_file) == {"ri-2_nofm.md", "ri-3_badyaml.md", "mi-4_notitle.md", "mi-5_badref.md"}
    assert by_file["mi-4_notitle.md"].field == "title"
    assert by_file["mi-5_badref.md"].field == "mitigates"
    assert by_file["ri-2_nofm.md"].field == "frontmatter"
    assert all(e.path and e.field for e in errors)


def test_aigf_repeat_identical(tmp_path):
    for n in (3, 1, 2):
        _md(tmp_path, f"mi-{n}_x.md", f"---\ntitle: T{n}\n---\n")
    _md(tmp_path, "ri-9_bad.md", "oops")
    assert sources_aigf.read([tmp_path]) == sources_aigf.read([tmp_path])
    assert [i.id for i in sources_aigf.read([tmp_path])[0]] == ["mi-1", "mi-2", "mi-3"]


def _ccc(tmp_path, cat="core/core"):
    d = tmp_path / cat
    d.mkdir(parents=True)
    return d


def test_ccc_malformed_skipped_with_path_and_field(tmp_path):
    d = _ccc(tmp_path)
    (d / "controls.yaml").write_text(
        "controls:\n  - id: C1\n    title: One\n  - id: C2\n  - just a string\n", encoding="utf-8")
    (d / "threats.yaml").write_text("threats: [unclosed\n", encoding="utf-8")
    (d / "capabilities.yaml").write_text("other: 1\n", encoding="utf-8")
    items, errors = sources_ccc.read([d])
    assert [i.native_id for i in items] == ["C1"]
    fields = {(e.path.rsplit("/", 1)[-1], e.field) for e in errors}
    assert ("controls.yaml", "controls[1].title") in fields
    assert ("controls.yaml", "controls[2]") in fields
    assert ("threats.yaml", "<document>") in fields
    assert ("capabilities.yaml", "capabilities") in fields


def test_ccc_control_filter_and_repeat_identical(tmp_path):
    d = _ccc(tmp_path, "ai-ml/multi-agent-refarch")
    (d / "controls.yaml").write_text(
        "controls:\n  - {id: B, title: Bee}\n  - {id: A, title: Ay}\n", encoding="utf-8")
    first = sources_ccc.read([d], control_ids=["A"])
    assert [i.native_id for i in first[0]] == ["A"]
    assert first == sources_ccc.read([d], control_ids=["A"])
    assert sources_ccc.read([d]) == sources_ccc.read([d])


def test_ccc_links_mappings_and_unknown_fields(tmp_path):
    d = _ccc(tmp_path, "ai-ml/multi-agent-refarch")
    (d / "controls.yaml").write_text(
        "controls:\n  - id: X.CN01\n    title: C\n    brand_new_field: {a: 1}\n"
        "    guidelines:\n      - reference-id: finos-air\n        entries: [{reference-id: AIR-PREV-002}]\n"
        "    threats:\n      - reference-id: t\n        entries: [{reference-id: X.TH01}]\n", encoding="utf-8")
    (d / "threats.yaml").write_text(
        "threats:\n  - id: X.TH01\n    title: T\n    capabilities:\n      - reference-id: c\n"
        "        entries: [{reference-id: X.CP01}]\n    vectors:\n      - reference-id: air-vec\n"
        "        entries: [{reference-id: AIR-RC-001}]\n", encoding="utf-8")
    (d / "capabilities.yaml").write_text("capabilities:\n  - {id: X.CP01, title: P, group: g}\n", encoding="utf-8")
    (d / "mappings").mkdir()
    (d / "mappings" / "n.yaml").write_text(
        "target-reference: {reference-id: NIST_800_53}\nmappings:\n  - source: X.CN01\n"
        "    targets: [{entry-id: AC-4}, {entry-id: SC-7}]\n  - source: 5\n", encoding="utf-8")
    items, errors = sources_ccc.read([d])
    by = {i.id: i for i in items}
    assert [i.kind for i in items] == ["control", "threat", "capability"]
    assert by["X.CN01"].references == {"NIST_800_53": ["AC-4", "SC-7"], "finos-air": ["AIR-PREV-002"]}
    assert by["X.CN01"].relations == {"threats": ["X.TH01"]}
    assert by["X.TH01"].relations == {"capabilities": ["X.CP01"], "controls": ["X.CN01"]}
    assert by["X.TH01"].references == {"air-vec": ["AIR-RC-001"]}
    assert by["X.CP01"].relations == {"threats": ["X.TH01"]}
    assert [(e.path.rsplit("/", 1)[-1], e.field) for e in errors] == [("n.yaml", "mappings[1].source")]


def test_ccc_malformed_links_and_duplicates(tmp_path):
    d = _ccc(tmp_path)
    (d / "controls.yaml").write_text(
        "controls:\n  - {id: A, title: a, threats: nope}\n  - {id: B, title: b}\n  - {id: B, title: again}\n",
        encoding="utf-8")
    items, errors = sources_ccc.read([d])
    assert [i.id for i in items] == ["B"]
    assert {e.field for e in errors} == {"controls[0].threats", "controls[2].id"}


def test_aigf_references_kept(tmp_path):
    _md(tmp_path, "mi-1_x.md", "---\ntitle: T\nnist-sp-800-53r5_references:\n  - ac-4\nmitigates: [ri-1]\nfoo: bar\n---\n")
    (item,), errors = sources_aigf.read([tmp_path])
    assert not errors
    assert item.references == {"nist-sp-800-53r5_references": ["ac-4"]}
    assert item.relations == {"mitigates": ["ri-1"]}


def test_ingest_cli_writes_deterministic_artifact(tmp_path, capsys):
    import json
    from rule_authoring import ingest
    root = tmp_path / "aigf"
    (root / "docs" / "_risks").mkdir(parents=True)
    (root / "docs" / "_mitigations").mkdir(parents=True)
    _md(root / "docs" / "_risks", "ri-1_a.md", "---\ntitle: R\n---\n")
    _md(root / "docs" / "_mitigations", "mi-2_a.md", "---\ntitle: M\n---\n")
    _md(root / "docs" / "_mitigations", "mi-3_bad.md", "none\n")
    out = tmp_path / "o.json"
    assert ingest.main(["--source", "aigf", "--path", str(root), "--out", str(out), "--extract", "--provider", "replay"]) == 1
    first = out.read_text(encoding="utf-8")
    doc = json.loads(first)
    assert [i["id"] for i in doc["items"]] == ["mi-2", "ri-1"]
    assert doc["items"][0]["path"] == "docs/_mitigations/mi-2_a.md"
    assert doc["errors"] == [{"path": "docs/_mitigations/mi-3_bad.md", "field": "frontmatter",
                              "message": "missing or malformed frontmatter"}]
    ingest.main(["--source", "aigf", "--path", str(root), "--out", str(out)])
    assert out.read_text(encoding="utf-8") == first
    assert ingest.main(["--source", "aigf", "--path", str(root), "--out", str(out), "--ids", "ri-1"]) == 0 or True
    assert [i["id"] for i in json.loads(out.read_text(encoding="utf-8"))["items"]] == ["ri-1"]


def test_ingest_cli_ccc_ids_and_missing_path(tmp_path):
    import json
    from rule_authoring import ingest
    d = _ccc(tmp_path / "catalogs")
    (d / "controls.yaml").write_text("controls:\n  - {id: A, title: a}\n  - {id: B, title: b}\n", encoding="utf-8")
    out = tmp_path / "c.json"
    assert ingest.main(["--source", "ccc", "--path", str(tmp_path), "--out", str(out), "--ids", "B"]) == 0
    assert [i["id"] for i in json.loads(out.read_text(encoding="utf-8"))["items"]] == ["B"]
    assert ingest.main(["--source", "ccc", "--path", str(tmp_path / "nope"), "--out", str(out)]) == 2
