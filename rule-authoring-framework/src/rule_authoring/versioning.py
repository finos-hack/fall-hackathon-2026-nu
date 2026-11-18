"""Content identity of catalog entries, for the hash-based version rule (agip_shared.versioned_write).

Lifecycle and human-curated fields are not content: approving, confirming or deprecating an entry never changes
its content hash, so it never bumps the version. Changing what the rule says (title, source, references, scores,
rules, remediation) does.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

from agip_shared.hashing import canonical_hash

from .paths import FRAMEWORK_ROOT

NON_CONTENT = {"status", "version", "history", "approved_by", "approved_at", "confirmation", "superseded_by",
               "previous_approved", "type", "mandatory_trigger", "extraction", "scoring"}
CATALOG_DIR = FRAMEWORK_ROOT / "catalogs"


def write_catalog(path: Path, doc: Any) -> None:
    """Write a catalog YAML, keeping its leading comment header (the CALM metadata vocabulary and notes live there;
    ``yaml.safe_dump`` alone would drop them)."""
    path = Path(path)
    header = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("#"):
                break
            header.append(line)
    body = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
    path.write_text(("\n".join(header) + "\n" if header else "") + body, encoding="utf-8")


def schema_refs(entry: dict[str, Any]) -> dict[str, Any]:
    """to_catalog_entry emits "FW:id" strings; the catalog schema (consistency check) wants {framework, id}."""
    refs = [dict(zip(("framework", "id"), r.split(":", 1))) if isinstance(r, str) else r
            for r in entry.get("references") or []]
    return {**entry, "references": refs}


def content(entry: dict[str, Any]) -> dict[str, Any]:
    """The entry without NON_CONTENT keys (version and bookkeeping), i.e. the part that decides whether it changed."""
    return {k: v for k, v in schema_refs(entry).items() if k not in NON_CONTENT}


def content_hash(entry: dict[str, Any]) -> str:
    """Hash of an entry's content, ignoring version bookkeeping."""
    return canonical_hash(content(entry))


def catalog_file(kind: str, catalog_dir: Path = CATALOG_DIR) -> Path:
    """risks.catalog.yaml for risk entries, controls.catalog.yaml otherwise."""
    return catalog_dir / ("risks.catalog.yaml" if kind in ("risk", "risk_rule") else "controls.catalog.yaml")


def find_entry(item_id: str, catalog_dir: Path = CATALOG_DIR) -> Optional[dict[str, Any]]:
    """Catalog entry with this id from the risks or controls catalog, or None; unreadable catalogs are skipped."""
    for name in ("risks.catalog.yaml", "controls.catalog.yaml"):
        try:
            doc = yaml.safe_load((catalog_dir / name).read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        for e in doc.get("items") or []:
            if isinstance(e, dict) and str(e.get("risk_id") or e.get("control_id") or e.get("id")) == item_id:
                return e
    return None
