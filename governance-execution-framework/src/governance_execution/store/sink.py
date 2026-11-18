"""Artifact sink: write immutable artifact files and record them in the repository in one call."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from agip_shared.contracts import Artifact

from .artifacts import FileArtifactStore


class ArtifactSink:
    """Writes an artifact file and records it in the repository so file and index stay consistent."""
    def __init__(self, repo: Any, data_dir: str | Path):
        """Use the repository's own file store when it has one (MemoryRepository), else create one under ``data_dir``."""
        self.repo = repo
        self.files = getattr(repo, "files", None) or FileArtifactStore(data_dir)

    def put(self, trace_id: str, kind: str, artifact_id: str, content: Any,
            versions: Optional[dict[str, Any]] = None) -> Artifact:
        """Write the artifact file, then register it in the repository and return the recorded Artifact. Raises ArtifactImmutableError on conflicting content."""
        a = self.files.put(trace_id, kind, artifact_id, content, versions)
        return self.repo.record_artifact(a)

    def get(self, trace_id: str, kind: str, artifact_id: str) -> Any:
        """Return artifact content, verifying the SHA-256 recorded in the repository when a record exists."""
        rec = self.repo.get_artifact(trace_id, kind, artifact_id)
        return self.files.get(trace_id, kind, artifact_id, rec.sha256 if rec else None)

    def list(self, trace_id: str) -> list[Artifact]:
        """Return the trace's recorded artifacts sorted by kind then id."""
        return sorted(self.repo.list_artifacts(trace_id), key=lambda a: (a.kind, a.id))
