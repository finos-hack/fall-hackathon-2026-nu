import pytest
from hypothesis import given, settings as hsettings, strategies as st

from agip_shared.hashing import canonical_json, sha256_hex
from agip_shared.paths import PathEscapeError
from agip_shared.settings import Settings
from governance_execution.store import (ArtifactImmutableError, ArtifactIntegrityError, FileArtifactStore,
                                        MemoryRepository, open_repository)
from governance_execution.store.repository import open_sqlite


def test_put_get_roundtrip_and_hash(tmp_path):
    s = FileArtifactStore(tmp_path)
    a = s.put("t1", "facts", "f1", {"b": 1, "a": [1, 2]})
    assert a.path == "artifacts/t1/facts/f1.json"
    f = tmp_path / a.path
    assert a.sha256 == sha256_hex(f.read_bytes())
    assert s.get("t1", "facts", "f1", a.sha256) == {"a": [1, 2], "b": 1}
    assert s.verify(a)


def test_identical_rewrite_ok_differing_refused(tmp_path):
    s = FileArtifactStore(tmp_path)
    a = s.put("t1", "decision", "d", {"x": 1})
    assert s.put("t1", "decision", "d", {"x": 1}).sha256 == a.sha256
    with pytest.raises(ArtifactImmutableError):
        s.put("t1", "decision", "d", {"x": 2})
    assert s.get("t1", "decision", "d") == {"x": 1}


def test_tamper_detected(tmp_path):
    s = FileArtifactStore(tmp_path)
    a = s.put("t1", "k", "i", {"x": 1})
    (tmp_path / a.path).write_text("{}")
    assert not s.verify(a)
    with pytest.raises(ArtifactIntegrityError):
        s.get("t1", "k", "i", a.sha256)


@pytest.mark.parametrize("bad", ["../x", "a/b", "..", "", "/abs", "a\\b", "C:x"])
def test_path_escape_rejected(tmp_path, bad):
    s = FileArtifactStore(tmp_path)
    for args in [(bad, "k", "i"), ("t", bad, "i"), ("t", "k", bad)]:
        with pytest.raises(PathEscapeError):
            s.put(*args, {})


@given(st.dictionaries(st.text(max_size=5), st.integers() | st.text(max_size=5), max_size=5))
@hsettings(max_examples=25, deadline=None)
def test_hash_is_canonical_content_hash(tmp_path_factory, doc):
    s = FileArtifactStore(tmp_path_factory.mktemp("p"))
    a = s.put("t", "k", "i", doc)
    assert a.sha256 == sha256_hex(canonical_json(doc))


def test_yaml_seed_and_file_export_rebuild(tmp_path):
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "c.yaml").write_text(
        "- {id: AIGF-MI-006, kind: control_rule, version: 1, status: APPROVED, title: HITL}\n", encoding="utf-8")
    data = tmp_path / "data"
    r = MemoryRepository(data, seed)
    assert r.get_catalog_item("AIGF-MI-006")["body"]["title"] == "HITL"
    art = r.files.put("t1", "facts", "f", {"a": 1})
    r.record_artifact(art)
    r.save_assessment({"trace_id": "t1", "decision": "ALLOW", "versions": {"calm": "1"}})
    r2 = MemoryRepository(data, seed)  # restart: rebuilt from files
    assert r2.get_artifact("t1", "facts", "f").sha256 == art.sha256
    assert r2.get_assessment("t1")["decision"] == "ALLOW"


def test_sqlite_backend(tmp_path):
    r = open_sqlite(tmp_path)
    assert r.backend == "sqlite"
    r.upsert_catalog_item({"id": "R1", "kind": "risk_rule", "version": 1, "status": "APPROVED", "body": {"k": 1}})
    assert r.get_catalog_item("R1")["body"] == {"k": 1}
    assert [i["id"] for i in r.list_catalog_items("risk_rule")] == ["R1"]
    art = FileArtifactStore(tmp_path).put("t", "k", "i", {"z": 1})
    assert r.record_artifact(art).sha256 == art.sha256
    assert r.record_artifact(art).sha256 == art.sha256  # idempotent
    bad = art.model_copy(update={"sha256": "0" * 64})
    with pytest.raises(ArtifactImmutableError):
        r.record_artifact(bad)
    r.save_assessment({"trace_id": "t", "decision": "ALLOW", "versions": {"a": 1}})
    r.save_assessment({"trace_id": "t", "decision": "DENY", "versions": {"a": 1}})
    assert r.get_assessment("t")["decision"] == "DENY"
    assert [a.id for a in r.list_artifacts("t")] == ["i"]


def test_auto_falls_back_to_sqlite_when_pglite_and_yaml_unusable(tmp_path, monkeypatch):
    import governance_execution.store.repository as repo

    def boom(*a, **k):
        raise repo.PGliteUnavailable("down")
    monkeypatch.setattr(repo, "open_pglite", boom)
    r = open_repository(Settings(data_dir=str(tmp_path)), "auto", seed_dir=tmp_path / "missing")
    assert r.backend == "sqlite"
