"""Persist and look up Extraction_Records (Req 4.5). One JSON file per record."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from agip_shared.contracts import Extraction_Record
from agip_shared.hashing import canonical_json
from agip_shared.paths import resolve_within


class Recorder:
    """Records live in ``<root>/<prompt_id>/<prompt_version>/<input_hash>.json``."""

    def __init__(self, root: str | Path):
        """Recordings live under root, laid out as prompt_id/prompt_version/input_hash.json."""
        self.root = Path(root)

    @staticmethod
    def key(prompt_id: str, prompt_version: str, input_hash: str) -> str:
        """Relative recording path; rejects empty parts or characters that could traverse directories."""
        for name, v in (("prompt_id", prompt_id), ("prompt_version", prompt_version), ("input_hash", input_hash)):
            if not v or not all(c.isalnum() or c in "._-" for c in v) or ".." in v:
                raise ValueError(f"invalid {name}: {v!r}")
        return f"{prompt_id}/{prompt_version}/{input_hash}.json"

    def path_for(self, prompt_id: str, prompt_version: str, input_hash: str) -> Path:
        """Absolute recording path, confined to the recorder root."""
        self.root.mkdir(parents=True, exist_ok=True)
        return resolve_within(self.root, self.key(prompt_id, prompt_version, input_hash))

    def save(self, record: Extraction_Record) -> Path:
        """Write the record as canonical JSON and return its path."""
        path = self.path_for(record.prompt_id or "", record.prompt_version, record.input_hash)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_json(json.loads(record.model_dump_json())), encoding="utf-8")
        return path

    def load(self, prompt_id: str, prompt_version: str, input_hash: str) -> Optional[Extraction_Record]:
        """Load the matching record, or None if no recording exists."""
        path = self.path_for(prompt_id, prompt_version, input_hash)
        if not path.is_file():
            return None
        return Extraction_Record.model_validate_json(path.read_text(encoding="utf-8"))

    def list_records(self) -> list[Extraction_Record]:
        """All recordings under the root, in sorted path order."""
        if not self.root.is_dir():
            return []
        return [Extraction_Record.model_validate_json(p.read_text(encoding="utf-8"))
                for p in sorted(self.root.rglob("*.json"))]
