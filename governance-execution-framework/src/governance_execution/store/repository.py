"""Repository interface with three interchangeable backends (``store.backend``).

* ``pglite``: PostgreSQL via py-pglite on TCP 5433 (psycopg, single serialised connection).
* ``yaml``:   in-memory repository seeded from YAML files; runs/artifacts exported to files
              and rebuilt from them on start (primary fallback, Req 23.2).
* ``sqlite``: stdlib sqlite3 with the same ``schema.sql`` (last resort).
* ``auto``:   try pglite, then yaml, then sqlite.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

import yaml

from agip_shared.contracts import Artifact
from agip_shared.hashing import canonical_hash, canonical_json
from agip_shared.settings import Settings

from .artifacts import ArtifactImmutableError, FileArtifactStore
from .db import PGliteServer, PGliteUnavailable, dsn

log = logging.getLogger(__name__)
SCHEMA_PATH = Path(__file__).with_name("schema.sql")

_CATALOG_JSON = ("source_ids", "body")


class Repository(Protocol):
    """Structural interface implemented by every storage backend (catalog items, artifact index, assessments)."""
    backend: str

    def upsert_catalog_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Insert or replace a catalog item keyed by (id, version); returns the normalised item."""
    def get_catalog_item(self, item_id: str, version: str | None = None) -> dict[str, Any] | None:
        """Return the item at ``version``, or the highest version when omitted; None if absent."""
    def list_catalog_items(self, kind: str | None = None) -> list[dict[str, Any]]:
        """List catalog items, optionally filtered by kind."""
    def record_artifact(self, artifact: Artifact) -> Artifact:
        """Index an artifact. Idempotent for the same SHA-256; raises ArtifactImmutableError if it differs."""
    def get_artifact(self, trace_id: str, kind: str, artifact_id: str) -> Artifact | None:
        """Return the indexed artifact, or None."""
    def list_artifacts(self, trace_id: str) -> list[Artifact]:
        """List the artifacts indexed for a trace."""
    def save_assessment(self, record: dict[str, Any]) -> None:
        """Store the assessment run record keyed by ``record['trace_id']``."""
    def get_assessment(self, trace_id: str) -> dict[str, Any] | None:
        """Return the assessment run record for a trace, or None."""
    def close(self) -> None:
        """Release backend resources."""


def _now() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _norm_item(item: dict[str, Any]) -> dict[str, Any]:
    """Normalise a raw catalog item: apply defaults (version '1', status DRAFT), move extra keys into ``body`` and compute the body's SHA-256."""
    out = {
        "id": str(item["id"]), "kind": item["kind"], "version": str(item.get("version", "1")),
        "status": item.get("status", "DRAFT"), "source_ids": item.get("source_ids") or [],
        "body": item.get("body") if "body" in item else {k: v for k, v in item.items()
                                                         if k not in ("id", "kind", "version", "status", "source_ids",
                                                                      "approved_by", "approved_at")},
        "approved_by": item.get("approved_by"), "approved_at": item.get("approved_at"),
    }
    out["sha256"] = canonical_hash(out["body"])
    return out


_LIFECYCLE = {"history", "confirmation", "superseded_by", "previous_approved", "type", "mandatory_trigger", "extraction",
              "scoring", "approved_by", "approved_at", "status", "version"}


def _content_sha(n: dict[str, Any]) -> str:
    """Hash of a catalog row's body without lifecycle fields, so status/approval changes do not count as content changes."""
    body = n["body"] if isinstance(n.get("body"), dict) else {}
    return canonical_hash({k: v for k, v in body.items() if k not in _LIFECYCLE})


def _versioned(n: dict[str, Any], existing: Optional[dict[str, Any]], versions: Callable[[], list[str]]) -> dict[str, Any]:
    """Hash rule for catalog rows: same content at (id, version) updates status/approval in place; different content
    becomes a new DRAFT version (max + 1) instead of overwriting the stored one. Lifecycle fields are not content."""
    if existing is None or _content_sha(existing) == _content_sha(n):
        return n
    nums = [int(v) for v in versions() if str(v).isdigit()]
    if not nums:   # non-numeric versions (e.g. an app model keyed by content hash) are already content-addressed
        return n
    return {**n, "version": str(max(nums) + 1), "status": "DRAFT", "approved_by": None, "approved_at": None}


class MemoryRepository:
    """YAML-seeded repository. Artifact/assessment records are mirrored to files and rebuilt on start."""

    backend = "yaml"

    def __init__(self, data_dir: str | Path, seed_dir: str | Path | None = None):
        """Create the file store, optionally seed catalog items from ``seed_dir``, then restore artifacts and assessments from existing files."""
        self.files = FileArtifactStore(data_dir)
        self._items: dict[tuple[str, str], dict[str, Any]] = {}
        self._artifacts: dict[tuple[str, str, str], Artifact] = {}
        self._assessments: dict[str, dict[str, Any]] = {}
        if seed_dir is not None:
            self.seed_from_yaml(seed_dir)
        self._rebuild_from_files()

    def seed_from_yaml(self, seed_dir: str | Path) -> int:
        """Load ``*.yaml``/``*.yml`` files containing a list of catalog items (or ``{items: [...]}``)."""
        seed = Path(seed_dir)
        if not seed.is_dir():
            raise FileNotFoundError(f"YAML seed directory not found: {seed}")
        n = 0
        for f in sorted([*seed.glob("*.yaml"), *seed.glob("*.yml")]):
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or []
            for item in (doc.get("items", []) if isinstance(doc, dict) else doc):
                self.upsert_catalog_item(item)
                n += 1
        return n

    def _rebuild_from_files(self) -> None:
        """Reload the artifact index and assessment records from files written by a previous run."""
        for trace in self.files.list_traces():
            for a in self.files.list(trace):
                self._artifacts[(a.trace_id, a.kind, a.id)] = a
            try:
                self._assessments[trace] = self.files.get(trace, "assessment_record", "assessment")
            except KeyError:
                pass

    def upsert_catalog_item(self, item):
        """Store the normalised item in memory. Same body at (id, version): updated in place; different body: new version."""
        n = _versioned(_norm_item(item), self.get_catalog_item(str(item["id"]), str(item.get("version", "1"))),
                       lambda: [v["version"] for (i, _), v in self._items.items() if i == str(item["id"])])
        self._items[(n["id"], n["version"])] = n
        return n

    def get_catalog_item(self, item_id, version=None):
        """Return the exact version, or the highest one when omitted (compared as strings)."""
        if version is not None:
            return self._items.get((item_id, str(version)))
        c = [v for (i, _), v in self._items.items() if i == item_id]
        # versions are compared as text, so "10" sorts before "2"
        return sorted(c, key=lambda v: v["version"])[-1] if c else None

    def list_catalog_items(self, kind=None):
        """List in-memory catalog items, optionally filtered by kind."""
        return [v for v in self._items.values() if kind is None or v["kind"] == kind]

    def record_artifact(self, artifact):
        """Index an artifact; first write wins. Raises ArtifactImmutableError if a different SHA-256 is already recorded."""
        key = (artifact.trace_id, artifact.kind, artifact.id)
        cur = self._artifacts.get(key)
        if cur and cur.sha256 != artifact.sha256:
            raise ArtifactImmutableError(f"{artifact.path}: sha256 differs from recorded")
        self._artifacts.setdefault(key, artifact)
        return self._artifacts[key]

    def get_artifact(self, trace_id, kind, artifact_id):
        """Return the indexed artifact, or None."""
        return self._artifacts.get((trace_id, kind, artifact_id))

    def list_artifacts(self, trace_id):
        """List indexed artifacts for a trace, in insertion order."""
        return [a for k, a in self._artifacts.items() if k[0] == trace_id]

    def save_assessment(self, record):
        """Keep the record in memory and export it once as an immutable file."""
        self._assessments[record["trace_id"]] = record
        try:  # export run record to a file; immutable once written with different content
            self.files.put(record["trace_id"], "assessment_record", "assessment", record)
        except ArtifactImmutableError:
            pass  # a later update stays in memory only; the first export is the audit record

    def get_assessment(self, trace_id):
        """Return the in-memory assessment record, or None."""
        return self._assessments.get(trace_id)

    def close(self) -> None:
        """No resources to release."""
        pass


class SqlRepository:
    """Shared SQL implementation for PostgreSQL (psycopg, ``%s``) and SQLite (``?``)."""

    def __init__(self, conn: Any, backend: str, server: PGliteServer | None = None):
        """Wrap an open connection and create the schema if needed. ``backend`` ('sqlite' or 'pglite') selects the parameter placeholder."""
        self.conn, self.backend, self._server = conn, backend, server
        self._ph = "?" if backend == "sqlite" else "%s"
        self._lock = threading.RLock()  # PGlite serves one connection; serialise access
        self._init_schema()

    def _q(self, sql: str) -> str:
        """Translate ``?`` placeholders to the backend's paramstyle."""
        return sql.replace("?", self._ph)

    def _exec(self, sql: str, params: tuple = ()) -> list[tuple]:
        """Run one statement under the lock and return all rows (empty for non-queries). SQLite is committed here; PGlite uses autocommit."""
        with self._lock:
            cur = self.conn.execute(self._q(sql), params)
            rows = cur.fetchall() if cur.description else []
            if self.backend == "sqlite":
                self.conn.commit()
            return rows

    def _init_schema(self) -> None:
        """Apply ``schema.sql`` statement by statement and add columns missing from older databases."""
        for stmt in SCHEMA_PATH.read_text(encoding="utf-8").split(";\n"):
            body = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--")).strip()
            if body:
                self._exec(body)
        for col in ("assessment_status", "validation_status"):   # databases created before task 23.7
            try:
                self._exec(f"ALTER TABLE assessment ADD COLUMN {col} TEXT")
            except Exception:  # noqa: BLE001  (column already exists)
                pass

    # --- catalog
    _CAT_COLS = "id, kind, version, status, source_ids, body, approved_by, approved_at, sha256"

    @staticmethod
    def _cat_row(r: tuple) -> dict[str, Any]:
        """Convert a catalog_item row (in ``_CAT_COLS`` order) to a dict, decoding the JSON columns."""
        return {"id": r[0], "kind": r[1], "version": r[2], "status": r[3], "source_ids": json.loads(r[4]),
                "body": json.loads(r[5]), "approved_by": r[6], "approved_at": r[7], "sha256": r[8]}

    def upsert_catalog_item(self, item):
        """Insert or update the item on (id, version); a different body at an existing (id, version) becomes a new
        version (see ``_versioned``). Returns the normalised item."""
        n = _versioned(_norm_item(item), self.get_catalog_item(str(item["id"]), str(item.get("version", "1"))),
                       lambda: [r[0] for r in self._exec("SELECT version FROM catalog_item WHERE id=?", (str(item["id"]),))])
        self._exec(
            f"INSERT INTO catalog_item ({self._CAT_COLS}) VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT (id, version) DO UPDATE SET kind=excluded.kind, status=excluded.status, "
            "source_ids=excluded.source_ids, body=excluded.body, approved_by=excluded.approved_by, "
            "approved_at=excluded.approved_at, sha256=excluded.sha256",
            (n["id"], n["kind"], n["version"], n["status"], canonical_json(n["source_ids"]),
             canonical_json(n["body"]), n["approved_by"], n["approved_at"], n["sha256"]))
        return n

    def get_catalog_item(self, item_id, version=None):
        """Return the exact version, or the highest one when omitted (ordered as text)."""
        if version is not None:
            rows = self._exec(f"SELECT {self._CAT_COLS} FROM catalog_item WHERE id=? AND version=?",
                              (item_id, str(version)))
        else:
            rows = self._exec(f"SELECT {self._CAT_COLS} FROM catalog_item WHERE id=? ORDER BY version DESC LIMIT 1",
                              (item_id,))
        return self._cat_row(rows[0]) if rows else None

    def list_catalog_items(self, kind=None):
        """List catalog items ordered by id and version, optionally filtered by kind."""
        if kind is None:
            rows = self._exec(f"SELECT {self._CAT_COLS} FROM catalog_item ORDER BY id, version")
        else:
            rows = self._exec(f"SELECT {self._CAT_COLS} FROM catalog_item WHERE kind=? ORDER BY id, version", (kind,))
        return [self._cat_row(r) for r in rows]

    # --- artifacts (insert-only; never updated)
    @staticmethod
    def _art_row(r: tuple) -> Artifact:
        """Convert an artifact row (in ``_ART_COLS`` order) to an Artifact."""
        return Artifact(id=r[0], trace_id=r[1], kind=r[2], sha256=r[3], path=r[4],
                        created=datetime.fromisoformat(r[5]))

    _ART_COLS = "id, trace_id, kind, sha256, path, created"

    def record_artifact(self, artifact):
        """Insert-only index of an artifact. Returns the stored record; raises ArtifactImmutableError if a different SHA-256 is already recorded."""
        self._exec(f"INSERT INTO artifact ({self._ART_COLS}) VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                   (artifact.id, artifact.trace_id, artifact.kind, artifact.sha256, artifact.path,
                    artifact.created.isoformat()))
        cur = self.get_artifact(artifact.trace_id, artifact.kind, artifact.id)
        assert cur is not None
        if cur.sha256 != artifact.sha256:
            raise ArtifactImmutableError(f"{artifact.path}: sha256 differs from recorded {cur.sha256}")
        return cur

    def get_artifact(self, trace_id, kind, artifact_id):
        """Return the indexed artifact, or None."""
        rows = self._exec(f"SELECT {self._ART_COLS} FROM artifact WHERE trace_id=? AND kind=? AND id=?",
                          (trace_id, kind, artifact_id))
        return self._art_row(rows[0]) if rows else None

    def list_artifacts(self, trace_id):
        """List artifacts for a trace ordered by kind and id."""
        rows = self._exec(f"SELECT {self._ART_COLS} FROM artifact WHERE trace_id=? ORDER BY kind, id", (trace_id,))
        return [self._art_row(r) for r in rows]

    # --- assessments
    def save_assessment(self, record):
        """Insert or update the assessment run record keyed by trace_id."""
        self._exec(
            "INSERT INTO assessment (trace_id, app_model_id, executor, mode, decision, versions, started, finished, "
            "assessment_status, validation_status) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT (trace_id) DO UPDATE SET app_model_id=excluded.app_model_id, "
            "executor=excluded.executor, mode=excluded.mode, decision=excluded.decision, "
            "versions=excluded.versions, started=excluded.started, finished=excluded.finished, "
            "assessment_status=excluded.assessment_status, validation_status=excluded.validation_status",
            (record["trace_id"], record.get("app_model_id"), record.get("executor"), record.get("mode"),
             record.get("decision"), canonical_json(record.get("versions") or {}),
             record.get("started"), record.get("finished"), record.get("assessment_status"),
             record.get("validation_status")))

    def get_assessment(self, trace_id):
        """Return the assessment record, or None. ``status`` is an alias of ``assessment_status``."""
        rows = self._exec("SELECT trace_id, app_model_id, executor, mode, decision, versions, started, finished, "
                          "assessment_status, validation_status "
                          "FROM assessment WHERE trace_id=?", (trace_id,))
        if not rows:
            return None
        r = rows[0]
        return {"trace_id": r[0], "app_model_id": r[1], "executor": r[2], "mode": r[3], "decision": r[4],
                "versions": json.loads(r[5]), "started": r[6], "finished": r[7],
                "assessment_status": r[8], "validation_status": r[9], "status": r[8]}

    def close(self) -> None:
        """Close the connection and stop the owned PGlite server, if any."""
        with self._lock:
            self.conn.close()
        if self._server is not None:
            self._server.stop()


def open_sqlite(data_dir: str | Path) -> SqlRepository:
    """Open (creating if needed) ``<data_dir>/agip.sqlite``; the connection may be shared across threads, access is serialised by the repository lock."""
    p = Path(data_dir) / "agip.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: the dashboard serves requests from worker threads; SqlRepository._lock serialises use
    return SqlRepository(sqlite3.connect(p, check_same_thread=False), "sqlite")


def open_pglite(settings: Settings, start_server: bool = True) -> SqlRepository:
    """Start PGlite (unless ``start_server`` is False) and connect with psycopg. Raises PGliteUnavailable if psycopg, the server or the connection is unavailable."""
    try:
        import psycopg
    except ImportError as e:
        raise PGliteUnavailable(f"psycopg not installed: {e}") from e
    server = PGliteServer(settings) if start_server else None
    if server:
        server.start()
    try:
        conn = psycopg.connect(dsn(settings), autocommit=True)
        return SqlRepository(conn, "pglite", server)
    except Exception as e:  # noqa: BLE001
        if server:
            server.stop()
        raise PGliteUnavailable(f"cannot connect to py-pglite: {e}") from e


def open_repository(settings: Settings, backend: str = "auto",
                    seed_dir: str | Path | None = None) -> Repository:
    """Open the configured backend; ``auto`` falls back pglite -> yaml -> sqlite (Req 23.2)."""
    order = ["pglite", "yaml", "sqlite"] if backend == "auto" else [backend]
    last: Exception | None = None
    for name in order:
        try:
            if name == "pglite":
                return open_pglite(settings)
            if name == "yaml":
                if seed_dir is None:
                    raise FileNotFoundError("no YAML seed directory configured")
                return MemoryRepository(settings.data_dir, seed_dir)
            if name == "sqlite":
                return open_sqlite(settings.data_dir)
            raise ValueError(f"unknown store backend: {name}")
        except ValueError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("store backend %s unavailable: %s", name, e)
            last = e
    raise RuntimeError(f"no usable store backend (last error: {last})")
