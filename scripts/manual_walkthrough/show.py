"""Print a stored assessment artifact or a CALM file in a readable form (used by the E2E demo).

  python scripts/manual_walkthrough/show.py <trace> <kind> [--fields a,b] [--rows KEY --cols a,b,c]
  python scripts/manual_walkthrough/show.py --calm <file.json>

<kind> is a folder under DATA_DIR/artifacts/<trace>/ (decision, control_gap, risk_profile, facts, decider_calls,
remediation, calm_validation, versions ...). --rows picks a list inside the artifact ('.' = the artifact itself)
and prints it as a table with the --cols columns.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAX_CELL = 60


def data_dir() -> Path:
    """Data directory: DATA_DIR env var, else DATA_DIR in .env, else 'data'. Relative paths resolve against the repo root."""
    import os
    if os.environ.get("DATA_DIR"):
        p = Path(os.environ["DATA_DIR"])
        return p if p.is_absolute() else ROOT / p
    env = ROOT / ".env"
    m = re.search(r"^DATA_DIR=(\S+)", env.read_text(encoding="utf-8"), re.M) if env.is_file() else None
    p = Path(m.group(1) if m else "data")
    return p if p.is_absolute() else ROOT / p


def load(trace: str, kind: str):
    """First JSON artifact of this kind for the assessment; exits with a message if none exists."""
    d = data_dir() / "artifacts" / trace / kind
    files = sorted(d.glob("*.json")) if d.is_dir() else []
    if not files:
        sys.exit(f"(no '{kind}' artifact for this assessment: nothing was produced at this stage)")
    return json.loads(files[0].read_text(encoding="utf-8"))


def cell(v) -> str:
    """Table cell text: strings as-is, other values as JSON, on one line and truncated to MAX_CELL."""
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    s = s.replace("\n", " ")
    return s if len(s) <= MAX_CELL else s[:MAX_CELL - 3] + "..."


def table(rows: list, cols: list[str]) -> None:
    """Print rows as an aligned text table with the given columns."""
    if not rows:
        print("(empty)")
        return
    data = [[cell(r.get(c, "") if isinstance(r, dict) else r) for c in cols] for r in rows]
    w = [max(len(c), *(len(x[i]) for x in data)) for i, c in enumerate(cols)]
    print("  ".join(c.ljust(w[i]) for i, c in enumerate(cols)))
    print("  ".join("-" * w[i] for i in range(len(cols))))
    for x in data:
        print("  ".join(x[i].ljust(w[i]) for i in range(len(cols))))
    print(f"({len(rows)} rows)")


def calm_summary(path: Path) -> None:
    """Print the nodes and relationships of a CALM architecture file."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    print(f"CALM architecture: {path.name}   ({len(doc.get('nodes') or [])} nodes, {len(doc.get('relationships') or [])} relationships)\n")
    print("NODES")
    for n in doc.get("nodes") or []:
        md = n.get("metadata") or {}
        attrs = ", ".join(f"{k}={v}" for k, v in md.items()) if isinstance(md, dict) else cell(md)
        print(f"  - {n.get('unique-id')}  [{n.get('node-type')}]  {n.get('name', '')}")
        if attrs:
            print(f"      metadata: {attrs}")
    print("\nRELATIONSHIPS")
    for r in doc.get("relationships") or []:
        c = (r.get("relationship-type") or {}).get("connects")
        if c:
            print(f"  - {c['source']['node']}  -->  {c['destination']['node']}   ({r.get('unique-id')})")
        else:
            print(f"  - {r.get('unique-id')}: {cell(r.get('relationship-type'))}")


def main() -> None:
    """CLI: show an assessment artifact or summarise a CALM file."""
    ap = argparse.ArgumentParser()
    ap.add_argument("trace", nargs="?")
    ap.add_argument("kind", nargs="?")
    ap.add_argument("--calm", type=Path)
    ap.add_argument("--fields", default="")
    ap.add_argument("--rows", default="")
    ap.add_argument("--cols", default="")
    ap.add_argument("--item", type=int, default=None, help="print one element of a list artifact in full")
    a = ap.parse_args()
    if a.calm:
        return calm_summary(a.calm if a.calm.is_absolute() else ROOT / a.calm)
    doc = load(a.trace, a.kind)
    if a.item is not None:
        lst = doc if isinstance(doc, list) else (doc.get(a.rows) if a.rows else None) or []
        if not 0 <= a.item < len(lst):
            sys.exit(f"(no element {a.item}: the list has {len(lst)})")
        doc = lst[a.item]
    if a.rows and a.item is None:
        rows = doc if a.rows == "." else (doc.get(a.rows) if isinstance(doc, dict) else None) or []
        return table(rows, [c for c in a.cols.split(",") if c])
    if a.fields and isinstance(doc, dict):
        doc = {k: doc.get(k) for k in a.fields.split(",")}
    print(json.dumps(doc, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
