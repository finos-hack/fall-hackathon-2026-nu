"""Pattern_Library: file copy + catalog record per pattern, with version and status (Req 7.2, 7.4, 7.6, 7.7).

A pattern is published only when ``calm validate -p`` reports no errors AND a human approver is named.
Live-drafted patterns enter as ``CANDIDATE`` and are never published automatically.
The validator is injected (``validate_pattern(pattern) -> obj with .status/.errors``) so this
package does not depend on the governance execution adapters.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Protocol

from agip_shared.hashing import sha256_hex

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
PATTERN_DIR = FRAMEWORK_ROOT / "patterns"


class PatternValidator(Protocol):
    """Protocol for an injected ``calm validate -p`` runner."""
    def validate_pattern(self, pattern: Any) -> Any:
        """Validate a pattern; the result exposes ``status`` and ``errors``."""
        ...


class CatalogStore(Protocol):
    """Protocol for the catalog the published records are written to."""
    def upsert_catalog_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Insert or update a catalog record and return the stored item."""
        ...


class PatternRejected(Exception):
    """Raised when a pattern or template cannot be published; ``errors`` lists the reasons."""
    def __init__(self, pattern_id: str, errors: list[str]):
        """Keep the pattern id and error list and build a combined message."""
        self.pattern_id, self.errors = pattern_id, errors
        super().__init__(f"pattern {pattern_id} rejected: " + "; ".join(errors))


@dataclass(frozen=True)
class PatternRef:
    """Identity of a library pattern: id, integer version, SHA-256 of its canonical text and file path."""
    id: str
    version: int
    sha256: str
    path: Path


def dumps(pattern: dict[str, Any]) -> str:
    """Deterministic JSON text (sorted keys, 2-space indent, trailing newline); the form hashed and written to disk."""
    return json.dumps(pattern, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def pattern_id(pattern: dict[str, Any]) -> str:
    """``metadata.pattern-id`` or an empty string."""
    return str((pattern.get("metadata") or {}).get("pattern-id") or "")


def load_patterns(directory: Path = PATTERN_DIR) -> dict[str, dict[str, Any]]:
    """All pattern JSON files, keyed by pattern ID."""
    out: dict[str, dict[str, Any]] = {}
    for f in sorted(directory.glob("P*.json")):
        p = json.loads(f.read_text(encoding="utf-8"))
        out[pattern_id(p)] = p
    return out


def ref_of(pattern: dict[str, Any], path: Optional[Path] = None) -> PatternRef:
    """Build a PatternRef; the version defaults to 1 when metadata has none."""
    md = pattern.get("metadata") or {}
    return PatternRef(pattern_id(pattern), int(md.get("version", 1)), sha256_hex(dumps(pattern)), path or Path())


def publish(pattern: dict[str, Any], validator: PatternValidator, store: Optional[CatalogStore],
            approved_by: Optional[str], library_dir: Path = PATTERN_DIR) -> dict[str, Any]:
    """Validate, require approval, write the library copy and the catalog record. Raises PatternRejected."""
    pid = pattern_id(pattern)
    if not pid:
        raise PatternRejected("?", ["metadata.pattern-id missing"])
    v = validator.validate_pattern(pattern)
    if getattr(v, "status", None) != "VALID":
        errs = [f"{e.code} at {e.path}: {e.message}" for e in getattr(v, "errors", [])]
        raise PatternRejected(pid, errs or [f"calm validate status {getattr(v, 'status', None)}: {getattr(v, 'error', '')}"])
    if not approved_by or not approved_by.strip():
        raise PatternRejected(pid, ["human approval required before publishing"])
    md = pattern.get("metadata") or {}
    file_ = library_dir / f"{pid}-{Path(str(pattern.get('$id', pid))).stem.split('-', 1)[-1]}.json"
    text = dumps(pattern)
    library_dir.mkdir(parents=True, exist_ok=True)
    file_.write_text(text, encoding="utf-8")
    record = {"id": pid, "kind": "pattern", "version": str(md.get("version", 1)), "status": "PUBLISHED",
              "source_ids": [], "approved_by": approved_by.strip(), "approved_at": None,
              "body": {"title": pattern.get("title"), "file": file_.name, "sha256": sha256_hex(text),
                       "related_controls": md.get("related_controls", []), "related_risks": md.get("related_risks", []),
                       "calm_cli_version": getattr(v, "version", None)}}
    return store.upsert_catalog_item(record) if store is not None else record


def as_candidate(pattern: dict[str, Any]) -> dict[str, Any]:
    """Mark a live-drafted pattern as an unapproved candidate (Req 7.6)."""
    p = json.loads(json.dumps(pattern))
    p.setdefault("metadata", {})["status"] = "CANDIDATE"
    p["metadata"].pop("approved_by", None)
    return p


def publish_template(template_text: str, validator: PatternValidator, store: Optional[CatalogStore],
                     status: str = "PUBLISHED") -> dict[str, Any]:
    """Publish a composed RA_Template to the CALM_Catalog after ``calm validate -p`` passes (Req 8.5)."""
    if status not in ("DRAFT", "PUBLISHED"):
        raise ValueError("status must be DRAFT or PUBLISHED")
    tpl = json.loads(template_text)
    md = tpl.get("metadata") or {}
    v = validator.validate_pattern(tpl)
    if getattr(v, "status", None) != "VALID":
        errs = [f"{e.code} at {e.path}: {e.message}" for e in getattr(v, "errors", [])]
        raise PatternRejected(md.get("ra-id", "?"), errs or [f"calm validate status {getattr(v, 'status', None)}"])
    record = {"id": md["ra-id"], "kind": "ra_template", "version": str(md.get("ra-version", 1)), "status": status,
              "source_ids": [p["id"] for p in md.get("source-patterns", [])],
              "body": {"title": tpl.get("title"), "file": f"{md['ra-id']}.json", "sha256": sha256_hex(template_text),
                       "source_patterns": md.get("source-patterns", []), "composer_version": md.get("composer-version"),
                       "calm_cli_version": getattr(v, "version", None)}}
    return store.upsert_catalog_item(record) if store is not None else record