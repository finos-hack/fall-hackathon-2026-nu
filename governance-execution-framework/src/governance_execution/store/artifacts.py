"""Immutable on-disk artifact store: ``<data_dir>/artifacts/<trace_id>/<kind>/<id>.json``.

Works without any database. Content is canonical JSON; the SHA-256 of the file bytes is
returned in the :class:`Artifact` record. Re-writing identical content is a no-op; writing
different content to an existing artifact raises :class:`ArtifactImmutableError`.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from agip_shared.contracts import Artifact
from agip_shared.hashing import canonical_json, sha256_hex
from agip_shared.paths import PathEscapeError, resolve_within

_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ArtifactImmutableError(Exception):
    """Attempt to overwrite an artifact with different content."""


class ArtifactIntegrityError(Exception):
    """Stored bytes no longer match the recorded SHA-256."""


class ArtifactNotFound(KeyError):
    """No artifact file exists at the requested trace/kind/id."""
    pass


def _check_segment(name: str, value: str) -> str:
    """Return ``value`` if it is a safe single path segment; raise PathEscapeError otherwise (blocks traversal)."""
    if not isinstance(value, str) or not _SEGMENT.match(value) or value.endswith(".") or ".." in value:
        raise PathEscapeError(f"invalid {name}: {value!r}")
    return value


class FileArtifactStore:
    """Write-once JSON artifact files under ``<data_dir>/artifacts``, addressed by trace id, kind and artifact id."""
    def __init__(self, data_dir: str | Path):
        """Bind the store to ``data_dir``; artifacts live under ``data_dir/artifacts`` (created lazily on first write)."""
        self.data_dir = Path(data_dir)
        self.root = self.data_dir / "artifacts"

    def _rel(self, trace_id: str, kind: str, artifact_id: str) -> str:
        """Build the validated data_dir-relative POSIX path for an artifact; every segment is checked."""
        _check_segment("trace_id", trace_id)
        _check_segment("kind", kind)
        _check_segment("id", artifact_id)
        return f"artifacts/{trace_id}/{kind}/{artifact_id}.json"

    def _path(self, trace_id: str, kind: str, artifact_id: str) -> tuple[str, Path]:
        """Return the relative path and its absolute form, guaranteed to resolve inside ``data_dir``."""
        rel = self._rel(trace_id, kind, artifact_id)
        return rel, resolve_within(self.data_dir, rel)

    def put(self, trace_id: str, kind: str, artifact_id: str, content: Any,
            versions: dict[str, Any] | None = None) -> Artifact:
        """Write ``content`` as canonical JSON and return its Artifact record (with SHA-256).

        Idempotent for identical content. Raises ArtifactImmutableError if the artifact already exists with different bytes.
        """
        rel, path = self._path(trace_id, kind, artifact_id)
        data = canonical_json(content).encode("utf-8")
        digest = sha256_hex(data)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "xb") as fh:  # exclusive create: never truncates an existing file
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
        except FileExistsError:
            existing = sha256_hex(path.read_bytes())
            if existing != digest:
                raise ArtifactImmutableError(
                    f"{rel} already exists with sha256 {existing}; refusing to overwrite with {digest}"
                ) from None
        return Artifact(id=artifact_id, kind=kind, sha256=digest, trace_id=trace_id,
                        path=rel, versions=versions or {})

    def get_bytes(self, trace_id: str, kind: str, artifact_id: str, expected_sha256: str | None = None) -> bytes:
        """Return the raw stored bytes. Raises ArtifactNotFound if missing, and ArtifactIntegrityError if ``expected_sha256`` is given and does not match."""
        rel, path = self._path(trace_id, kind, artifact_id)
        if not path.is_file():
            raise ArtifactNotFound(rel)
        data = path.read_bytes()
        if expected_sha256 is not None and sha256_hex(data) != expected_sha256:
            raise ArtifactIntegrityError(f"{rel}: sha256 mismatch")
        return data

    def get(self, trace_id: str, kind: str, artifact_id: str, expected_sha256: str | None = None) -> Any:
        """Return the parsed JSON content of an artifact (same checks as :meth:`get_bytes`)."""
        return json.loads(self.get_bytes(trace_id, kind, artifact_id, expected_sha256))

    def verify(self, artifact: Artifact) -> bool:
        """True if the artifact file exists inside ``data_dir`` and its bytes still match ``artifact.sha256``; never raises."""
        try:
            path = resolve_within(self.data_dir, artifact.path)
            return path.is_file() and sha256_hex(path.read_bytes()) == artifact.sha256
        except (PathEscapeError, OSError):
            return False

    def list(self, trace_id: str) -> list[Artifact]:
        """Rebuild Artifact records from files (used when the DB is unavailable)."""
        base = self.root / _check_segment("trace_id", trace_id)
        out: list[Artifact] = []
        if not base.is_dir():
            return out
        for f in sorted(base.glob("*/*.json")):
            out.append(Artifact(id=f.stem, kind=f.parent.name, sha256=sha256_hex(f.read_bytes()),
                                trace_id=trace_id, path=f"artifacts/{trace_id}/{f.parent.name}/{f.name}"))
        return out

    def list_traces(self) -> list[str]:
        """Return the sorted trace ids that have an artifact directory."""
        return sorted(p.name for p in self.root.iterdir() if p.is_dir()) if self.root.is_dir() else []
