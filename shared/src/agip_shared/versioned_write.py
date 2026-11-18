"""Hash-based write rule for generated artifacts (all frameworks).

* ``inputs_hash``  covers everything that produces an artifact (source content, prompt text, model, parameters,
  upstream artifact hashes). Same inputs as the stored artifact -> the step is skipped (no regeneration, no write).
* ``content_hash`` covers the artifact's content, excluding its own version. Changed content -> version + 1;
  identical content -> the version stays and the file is not rewritten.

Versions and hashes are kept in a sidecar index ``<dir>/.versions`` (JSON, {file name: entry}; no file extension, so
``*.json`` / ``*.yaml`` globs over artifact directories never pick it up), so artifact formats do not change.
Writers that already carry a version field (draft items, ruleset headers) take it from here.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agip_shared.hashing import canonical_hash, sha256_hex

INDEX = ".versions"


def hash_inputs(**parts: Any) -> str:
    """inputs_hash over named parts (canonical JSON, sorted keys)."""
    return canonical_hash(parts)


def hash_content(content: Any) -> str:
    """content_hash of text/bytes as-is, or of any other value as canonical JSON."""
    return sha256_hex(content) if isinstance(content, (str, bytes)) else canonical_hash(content)


@dataclass(frozen=True)
class Written:
    """Result of a versioned write: path, version, what happened (created/updated/unchanged) and the hashes recorded."""
    path: Path
    version: int
    action: str            # created | updated | unchanged
    inputs_hash: Optional[str]
    content_hash: str


def _index_path(path: Path) -> Path:
    """Sidecar version index that lives next to the artifact."""
    return path.parent / INDEX


def _load(path: Path) -> dict[str, Any]:
    """Read the sidecar index; a missing, unreadable or malformed index counts as empty."""
    p = _index_path(path)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _save(path: Path, index: dict[str, Any]) -> None:
    """Write the sidecar index atomically (temp file then replace)."""
    p = _index_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, p)


def entry(path: str | Path) -> Optional[dict[str, Any]]:
    """Index entry {version, inputs_hash, content_hash, updated} of an artifact, or None."""
    path = Path(path)
    return _load(path).get(path.name)


def is_fresh(path: str | Path, inputs_hash: str) -> bool:
    """True when the artifact exists and was produced from the same inputs: skip regeneration."""
    path = Path(path)
    e = entry(path)
    return bool(e and path.is_file() and e.get("inputs_hash") == inputs_hash)


def version_for(path: str | Path, content_hash: str, initial: int = 1) -> int:
    """Version the artifact gets for this content: unchanged content keeps it, changed content is +1.

    ``initial`` is used when the artifact has no index entry yet (e.g. a version already recorded elsewhere)."""
    e = entry(path)
    if not e:
        return int(initial)
    v = int(e.get("version", initial))
    return v if e.get("content_hash") == content_hash else v + 1


def write(path: str | Path, data: str | bytes, *, content_hash: str, version: int,
          inputs_hash: Optional[str] = None) -> Written:
    """Write ``data`` unless the file already holds these bytes; record version and hashes in the index."""
    path = Path(path)
    raw = data.encode("utf-8") if isinstance(data, str) else data
    index = _load(path)
    old = index.get(path.name)
    same_bytes = path.is_file() and path.read_bytes() == raw
    if not same_bytes:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    action = "created" if old is None and not same_bytes else ("unchanged" if same_bytes else "updated")
    new = {"version": int(version), "content_hash": content_hash, "inputs_hash": inputs_hash}
    if old is None or any(old.get(k) != v for k, v in new.items()):
        index[path.name] = {**new, "updated": datetime.now(timezone.utc).isoformat()}
        _save(path, index)
    return Written(path, int(version), action, inputs_hash, content_hash)
