"""Catalog consistency check (Req 5.6, 5.7).

``check`` fails on: an item defined more than once (``conflict`` when the content differs,
``duplicate_item`` when identical), a Rule_Code defined more than once (``duplicate_rule_code``),
and a Rule_Code referenced but defined nowhere (``undefined_rule_code``). Every error names
both locations (``<file>:<item id>``) where two exist.

CLI: ``python -m rule_authoring.consistency [catalog.yaml ...]`` (exit 1 on any error).
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

from agip_shared.hashing import canonical_hash

from .paths import FRAMEWORK_ROOT

DEFAULT_CATALOGS = [FRAMEWORK_ROOT / "catalogs" / "controls.catalog.yaml",
                    FRAMEWORK_ROOT / "catalogs" / "risks.catalog.yaml"]


@dataclass(frozen=True)
class ConsistencyError:
    """One catalog consistency problem: its kind, the offending key and where it occurs."""
    kind: str                    # conflict | duplicate_item | duplicate_rule_code | undefined_rule_code | dangling_reference | malformed_reference | dangling_risk_control_link
    key: str                     # item id or Rule_Code
    locations: tuple[str, ...]   # one or two "<file>:<id>" locations

    def __str__(self) -> str:
        """One-line report form."""
        return f"{self.kind}: {self.key} at {' and '.join(self.locations)}"


def _item_id(item: dict[str, Any]) -> Optional[str]:
    """Catalog item id (control_id, risk_id or id), or None."""
    return next((str(item[k]) for k in ("control_id", "risk_id", "id") if k in item), None)


def _referenced_codes(item: dict[str, Any]) -> list[str]:
    """Rule codes an item refers to, including those in its configurations."""
    codes = list(item.get("rule_codes") or [])
    for cfg in item.get("configurations") or []:
        codes += cfg.get("rule_codes") or []
    return codes


SOURCES_DIR = FRAMEWORK_ROOT / "catalogs" / "sources"
LINK_FIELDS = ("controls", "control_ids", "linked_controls", "mitigations")   # risk -> control links
NIST_ID = re.compile(r"^[A-Z]{2}-\d+(\(\d+\))?$")


def load_source_ids(sources_dir: Path = SOURCES_DIR) -> dict[str, set[str]]:
    """Ingested IDs per reference framework prefix (AIGF, CCC)."""
    out: dict[str, set[str]] = {}
    for fw in ("AIGF", "CCC"):
        f = sources_dir / f"{fw.lower()}.json"
        if f.is_file():
            out[fw] = {str(i["id"]) for i in json.loads(f.read_text(encoding="utf-8")).get("items", [])}
    return out


def check(catalogs: dict[str, Any], sources: Optional[dict[str, set[str]]] = None) -> list[ConsistencyError]:
    """``catalogs`` maps a location label (file path) to its parsed content (``{items: [...]}`` or a list)."""
    if sources is None:
        sources = load_source_ids()
    errors: list[ConsistencyError] = []
    control_ids: set[str] = set()
    risk_links: list[tuple[str, str]] = []              # (control id, location)
    items_seen: dict[str, tuple[str, str]] = {}      # id -> (location, content hash)
    defined: dict[str, str] = {}                      # rule_code -> location
    references: list[tuple[str, str]] = []            # (rule_code, location)

    for label in sorted(catalogs):
        doc = catalogs[label]
        items = doc if isinstance(doc, list) else (doc or {}).get("items") or []
        for item in items:
            if not isinstance(item, dict):
                continue
            iid = _item_id(item)
            if iid is None:
                continue
            here = f"{label}:{iid}"
            digest = canonical_hash(item)
            if iid in items_seen:
                prev_loc, prev_hash = items_seen[iid]
                errors.append(ConsistencyError("duplicate_item" if prev_hash == digest else "conflict",
                                               iid, (prev_loc, here)))
            else:
                items_seen[iid] = (here, digest)
            for code in (item.get("spectral_rules") or {}):
                loc = f"{here}.spectral_rules.{code}"
                if code in defined:
                    errors.append(ConsistencyError("duplicate_rule_code", code, (defined[code], loc)))
                else:
                    defined[code] = loc
            references += [(c, here) for c in _referenced_codes(item)]
            for ref in item.get("references") or []:
                fw, rid = (ref.get("framework"), ref.get("id")) if isinstance(ref, dict) else (None, None)
                rloc = f"{here}.references.{rid}"
                if not isinstance(rid, str) or not rid.strip():
                    errors.append(ConsistencyError("malformed_reference", str(rid), (rloc,)))
                elif fw == "NIST" and not NIST_ID.match(rid):
                    errors.append(ConsistencyError("malformed_reference", rid, (rloc,)))
                elif fw in sources and rid not in sources[fw]:
                    errors.append(ConsistencyError("dangling_reference", rid, (rloc,)))
            if "control_id" in item:
                control_ids.add(str(item["control_id"]))
            if "risk_id" in item:
                for fld in LINK_FIELDS:
                    risk_links += [(str(c), f"{here}.{fld}") for c in item.get(fld) or []]

    for code, loc in references:
        if code not in defined:
            errors.append(ConsistencyError("undefined_rule_code", code, (loc,)))
    for cid, loc in risk_links:
        if cid not in control_ids:
            errors.append(ConsistencyError("dangling_risk_control_link", cid, (loc,)))
    return errors


def load_catalogs(paths: list[Path]) -> dict[str, Any]:
    """Parse each catalog YAML file, keyed by file name."""
    return {p.name: yaml.safe_load(p.read_text(encoding="utf-8")) for p in paths}


def main(argv: Optional[list[str]] = None) -> int:
    """CLI: check catalogs (arguments or defaults) and print errors. Exit code 1 when any are found."""
    paths = [Path(a) for a in (argv if argv is not None else sys.argv[1:])] or DEFAULT_CATALOGS
    errors = check(load_catalogs(paths))
    for e in errors:
        print(e, file=sys.stderr)
    print("consistent" if not errors else f"{len(errors)} consistency error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
