"""Coverage report: one row per source item with its rule-authoring state."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from .knowledge import is_executable
from .paths import FRAMEWORK_ROOT

KINDS = {"AIGF": {"risk", "mitigation"}, "CCC": {"control", "threat"}}
STATES = ("APPROVED rule", "IN_REVIEW", "REJECTED", "DEPRECATED", "DRAFT",
          "not expressible", "non-executable (stored)", "missing extraction")
_STATUS_ORDER = ("IN_REVIEW", "REJECTED", "DEPRECATED", "DRAFT")


def _src_id(item: dict) -> str:
    """Source id an item or draft was derived from."""
    s = item.get("source") or {}
    return str(s.get("id") or item.get("source_id") or "")


def _codes(c: dict) -> list:
    """Rule codes of a catalog entry: top-level (risks) or per configuration (controls)."""
    return list(c.get("rule_codes") or []) + [r for g in c.get("configurations") or [] for r in g.get("rule_codes") or []]


def _executable(kind: str) -> bool:
    """True if items of this kind compile to rules; unknown kinds count as non-executable."""
    try:
        return is_executable({"type": kind})
    except ValueError:
        return False


def _state(kind: str, cats: list[dict], drafts: list[dict]) -> str:
    """Coverage state of a source: an approved rule wins, then 'not expressible', then the first status found in _STATUS_ORDER, else non-executable or missing extraction."""
    if any(c.get("status") == "APPROVED" and _codes(c) for c in cats):
        return "APPROVED rule"
    if any(str(d.get("inexpressible_reason") or "").strip() for d in drafts):
        return "not expressible"
    seen = {str(i.get("status") or "").upper() for i in cats} | {
        str(d.get("status") or "DRAFT").upper() for d in drafts}
    for s in _STATUS_ORDER:
        if s in seen:
            return s
    if "APPROVED" in seen:  # approved without rule codes: still awaiting a rule
        return "DRAFT"
    return "non-executable (stored)" if not _executable(kind) else "missing extraction"


def build(sources: list[dict], drafts: list[dict], catalogs: list[dict]) -> dict:
    """Coverage report: one row per in-scope source with its state and rule codes, plus counts."""
    cat_by: dict[str, list[dict]] = {}
    for c in catalogs:
        cat_by.setdefault(_src_id(c), []).append(c)
    dr_by: dict[str, list[dict]] = {}
    for d in drafts:
        dr_by.setdefault(_src_id(d), []).append(d)
    rows = []
    for s in sources:
        fw, kind = s.get("framework"), s.get("kind")
        if kind not in KINDS.get(fw, ()):
            continue
        cats, drs = cat_by.get(s["id"], []), dr_by.get(s["id"], [])
        rows.append({
            "framework": fw, "id": s["id"], "kind": kind, "title": s.get("title", ""),
            "state": _state(kind, cats, drs),
            "catalog_ids": sorted(str(c.get("risk_id") or c.get("control_id") or "") for c in cats),
            "rule_codes": sorted({r for c in cats for r in _codes(c)}),
            "references": s.get("references") or {},
        })
    rows.sort(key=lambda r: (r["framework"], r["kind"], r["id"]))
    counts = Counter(r["state"] for r in rows)
    return {"rows": rows, "counts": {k: counts[k] for k in STATES if counts[k]}}


def load_sources(root: Path = FRAMEWORK_ROOT) -> list[dict]:
    """Source items from the ingested aigf/ccc artifacts, if present."""
    out: list[dict] = []
    for n in ("aigf", "ccc"):
        p = root / "catalogs" / "sources" / f"{n}.json"
        if p.exists():
            out += json.loads(p.read_text(encoding="utf-8")).get("items", [])
    return out


def load_drafts(root: Path = FRAMEWORK_ROOT) -> list[dict]:
    """Draft items from the drafts directory, flattening stored draft envelopes into the shape coverage expects."""
    out: list[dict] = []
    for p in sorted((root / "catalogs" / "drafts").glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("items", [data])
        for d in items:  # stored draft envelope {id,status,body:{source,extraction}} -> flat coverage shape
            b = d.get("body") if isinstance(d, dict) else None
            if b and "source" not in d:
                d = {**d, "source": b.get("source"),
                     "inexpressible_reason": (b.get("extraction") or {}).get("inexpressible_reason")}
            out.append(d)
    return out


def load_catalogs(root: Path = FRAMEWORK_ROOT) -> list[dict]:
    """Items from the controls and risks catalogs."""
    out: list[dict] = []
    for n in ("controls", "risks"):
        p = root / "catalogs" / f"{n}.catalog.yaml"
        if p.exists():
            out += (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("items", [])
    return out


def _table(rep: dict) -> str:
    """Plain-text table of the report rows."""
    lines = [f"{r['framework']:5} {r['kind']:10} {r['id']:22} {r['state']:24} {','.join(r['rule_codes'])}"
             for r in rep["rows"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI: print or save the coverage report as a table or JSON. Always returns 0."""
    ap = argparse.ArgumentParser(prog="rule_authoring.coverage")
    ap.add_argument("--format", choices=("table", "json"), default="table")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    rep = build(load_sources(), load_drafts(), load_catalogs())
    text = json.dumps(rep, indent=2, sort_keys=True) if a.format == "json" else _table(rep)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    print("counts:", json.dumps(rep["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
