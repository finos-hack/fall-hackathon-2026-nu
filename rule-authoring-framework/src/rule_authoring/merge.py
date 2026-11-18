"""Merge reviewed DRAFTs into the catalogs under the hash rule.

CLI: ``python -m rule_authoring.merge [--drafts DIR] [--catalogs DIR] [--ids ID ...]``

* New item              -> appended as DRAFT at the draft's version.
* Same content          -> unchanged (nothing written).
* Changed, not approved -> content replaced in place, version + 1, history kept.
* Changed, APPROVED     -> content replaced, status DRAFT, version + 1; the approved entry is kept as
                           ``previous_approved`` and stays in force (compile uses it) until the new version is approved.
Human-curated fields (``mandatory_trigger``, ``type``) are kept from the existing entry. Every merged revision then
goes through ``approval`` with its version recorded in the history.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

import yaml

from . import versioning
from .extraction import to_catalog_entry
from .paths import FRAMEWORK_ROOT

DRAFTS_DIR = FRAMEWORK_ROOT / "catalogs" / "drafts"
_KEEP = ("mandatory_trigger", "type", "history")


def _id(e: dict[str, Any]) -> str:
    """Catalog entry id (risk_id, control_id or id) as a string."""
    return str(e.get("risk_id") or e.get("control_id") or e.get("id"))


def _schema_refs(entry: dict[str, Any]) -> dict[str, Any]:
    return versioning.schema_refs(entry)


def merge_entry(doc: dict[str, Any], entry: dict[str, Any]) -> tuple[str, int]:
    """Merge one catalog entry into ``doc`` in place. Returns (action, version)."""
    entry = _schema_refs(entry)
    items = doc.setdefault("items", [])
    cur = next((e for e in items if isinstance(e, dict) and _id(e) == _id(entry)), None)
    if cur is None:
        items.append({**entry, "status": "DRAFT", "version": int(entry.get("version", 1))})
        return "added", int(entry.get("version", 1))
    if versioning.content_hash(cur) == versioning.content_hash(entry):
        return "unchanged", int(cur.get("version", 1))
    version = int(cur.get("version", 1)) + 1
    new = {**entry, **{k: cur[k] for k in _KEEP if k in cur}, "status": "DRAFT", "version": version}
    if cur.get("status") == "APPROVED":
        new["previous_approved"] = {k: v for k, v in cur.items() if k != "previous_approved"}
    elif cur.get("previous_approved"):
        new["previous_approved"] = cur["previous_approved"]
    items[items.index(cur)] = new
    return ("revised" if "previous_approved" in new else "updated"), version


def merge_drafts(drafts_dir: Path = DRAFTS_DIR, catalog_dir: Path = versioning.CATALOG_DIR,
                 ids: Optional[Sequence[str]] = None) -> dict[str, tuple[str, int]]:
    """Merge draft JSON files into the catalog YAML files, optionally only for `ids`. Returns {item id: (action, version)}; files are rewritten only when something changed."""
    out: dict[str, tuple[str, int]] = {}
    docs: dict[Path, Any] = {}
    changed: set[Path] = set()
    for p in sorted(Path(drafts_dir).glob("*.json")):
        item = json.loads(p.read_text(encoding="utf-8"))
        if ids and item["id"] not in ids:
            continue
        cat = versioning.catalog_file(item["kind"], catalog_dir)
        doc = docs.setdefault(cat, yaml.safe_load(cat.read_text(encoding="utf-8")) or {})
        out[item["id"]] = merge_entry(doc, to_catalog_entry(item))
        if out[item["id"]][0] != "unchanged":
            changed.add(cat)
    for cat in changed:   # a catalog is only rewritten when one of its entries changed
        versioning.write_catalog(cat, docs[cat])
    return out


def main(argv: Optional[list[str]] = None) -> int:
    """CLI: merge stored drafts into the catalogs. Prints each action and always returns 0."""
    ap = argparse.ArgumentParser(prog="python -m rule_authoring.merge")
    ap.add_argument("--drafts", type=Path, default=DRAFTS_DIR)
    ap.add_argument("--catalogs", type=Path, default=versioning.CATALOG_DIR)
    ap.add_argument("--ids", nargs="+")
    a = ap.parse_args(argv)
    res = merge_drafts(a.drafts, a.catalogs, a.ids)
    for i, (action, v) in sorted(res.items()):
        print(f"{action.upper():9} {i} v{v}")
    if not res:
        print("no drafts to merge", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
