"""Listing model for the four main menus (Controls, Risk Profile, CALM Patterns, Assessments).

Every list is built the same way: a row has a few ``cells`` for the table, ``details`` for the expandable part,
and ``facets`` for the filters. Search, filtering and 20-per-page pagination are shared (server side, so a
filtered or paged view can be bookmarked).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

from . import mvp_data as md

PAGE_SIZE = 20
SEVERITY_ORDER = ["critical", "high", "medium", "low"]
RA_TYPE = "RA template"
PATTERN_TYPE = "Pattern"


# ---------------------------------------------------------------- shared helpers
def _flat(v: Any) -> str:
    """Flatten a value, including nested lists, into a space-separated string for search."""
    if isinstance(v, (list, tuple)):
        return " ".join(_flat(x) for x in v)
    return "" if v is None else str(v)


def _row(rid: str, cells: list[tuple[str, Any]], details: list[tuple[str, Any]], facets: dict[str, str],
         detail_url: Optional[str] = None) -> dict[str, Any]:
    """Build a listing row. Empty details are dropped, and ``search`` is a lower-cased blob of the id, cells, details and facet values."""
    # drop empty details so the expandable section only shows fields that have content
    details = [(k, v) for k, v in details if v not in (None, "", [], ())]
    blob = " ".join([rid] + [_flat(v) for _, v in cells] + [_flat(v) for _, v in details] + list(facets.values())).lower()
    return {"id": rid, "cells": cells, "details": details, "facets": facets, "search": blob, "detail_url": detail_url, "open": False}


def _src(it: dict) -> tuple[str, str]:
    """Return (framework, 'framework id') for an item's source reference."""
    s = it.get("source") or {}
    return str(s.get("framework") or ""), f"{s.get('framework', '')} {s.get('id', '')}".strip()


def _approved(it: dict) -> str:
    """Approval note like 'alice on 2025-01-31', or '' if the item was not approved."""
    return f"{it.get('approved_by')} on {str(it.get('approved_at'))[:10]}" if it.get("approved_by") else ""


def _refs(it: dict) -> list[str]:
    """Format an item's references as 'framework id' strings."""
    return [f"{r.get('framework')} {r.get('id')}" for r in it.get("references") or []]


def _link_list(kind: str, ids: list[str]) -> list[tuple[str, str]]:
    """Pair each id with its catalog page URL, which opens and focuses that entry."""
    return [(i, f"/catalogs/{kind}?focus={i}") for i in ids]


def _life(entry: dict) -> str:
    """Join the simple (str/number) lifecycle fields into 'key: value' text, leaving out the hash."""
    return ", ".join(f"{k}: {v}" for k, v in (entry or {}).items() if isinstance(v, (str, int, float)) and k != "sha256")


# ---------------------------------------------------------------- row builders
def control_rows(store) -> list[dict]:
    """Listing rows for the controls catalog; severity is the worst across the control's configurations."""
    pats = md.patterns()
    rows = []
    for r in md.registry_rows("controls", store):
        it = r["raw"]
        cfgs = it.get("configurations") or []
        sevs = [str(c.get("severity") or "").lower() for c in cfgs]
        worst = next((s for s in SEVERITY_ORDER if s in sevs), sevs[0] if sevs else "")
        mand = "Mandatory" if any(c.get("mandatory") for c in cfgs) else "Optional"
        fw, src = _src(it)
        used_in = [p["id"] for p in pats if r["id"] in p["related_controls"]]
        rows.append(_row(
            r["id"],
            [("mono", r["id"]), ("text", it.get("title")), ("badge", pending_label(it.get("status"))), ("badge", worst), ("text", mand), ("text", src)],
            _action("controls", r["id"], it.get("status")) +
            [("Version", str(it.get("version", ""))),
             ("Status", str(it.get("status") or "")),
             ("Source", src),
             ("Applies when", (it.get("applicability") or {}).get("facts")),
             ("Configurations", [f"{c.get('id')}: {c.get('severity')}{', mandatory' if c.get('mandatory') else ''}" for c in cfgs]),
             ("Rule codes", md._codes(it)),
             ("Remediation", [f"{c.get('id')}: {c.get('remediation')}" for c in cfgs if c.get("remediation")]),
             ("References", _refs(it)),
             ("Approved", _approved(it)),
             ("Used in patterns", _link_list("patterns", used_in)),
             ("More", [("Registry entry and assessments that used it", f"/registry/controls/{r['id']}")])],
            {"status": str(it.get("status") or ""), "severity": worst, "mandatory": mand, "source": fw}))
    return rows


def risk_rows(store) -> list[dict]:
    """Listing rows for the risks catalog; the score is likelihood x impact when both are integers."""
    pats = md.patterns()
    rows = []
    for r in md.registry_rows("risks", store):
        it = r["raw"]
        l, i = it.get("likelihood"), it.get("impact")
        score = f"{l} x {i} = {l * i}" if isinstance(l, int) and isinstance(i, int) else ""
        fw, src = _src(it)
        conf = it.get("confirmation") or {}
        used_in = [p["id"] for p in pats if r["id"] in p["related_risks"]]
        sc = it.get("scoring") or {}
        scored = (f"Decider {sc.get('model') or ''}: likelihood {(sc.get('likelihood') or {}).get('label')} "
                  f"(confidence {(sc.get('likelihood') or {}).get('confidence')}), impact {(sc.get('impact') or {}).get('label')} "
                  f"(confidence {(sc.get('impact') or {}).get('confidence')})"
                  + (f"; low confidence: {', '.join(sc.get('low_confidence') or [])}" if sc.get("low_confidence") else "")
                  if sc.get("source") == "decider" else (f"LLM ({sc.get('decider_error')})" if sc else ""))
        rows.append(_row(
            r["id"],
            [("mono", r["id"]), ("text", it.get("title")), ("badge", pending_label(it.get("status"))), ("text", score), ("text", it.get("dimension")), ("text", src)],
            _action("risks", r["id"], it.get("status"), f"Approving also confirms likelihood {l} and impact {i}.") +
            [("Version", str(it.get("version", ""))),
             ("Status", str(it.get("status") or "")),
             ("Source", src),
             ("Likelihood / impact", f"likelihood {l}, impact {i}"),
             ("Scored by", scored),
             ("Confirmed by", f"{conf.get('by')} ({conf.get('role')}): {conf.get('note')}" if conf else ""),
             ("Mandatory trigger", "Yes" if it.get("mandatory_trigger") else ""),
             ("Rule codes", md._codes(it)),
             ("Remediation", it.get("remediation")),
             ("References", _refs(it)),
             ("Approved", _approved(it)),
             ("Used in patterns", _link_list("patterns", used_in)),
             ("More", [("Registry entry and assessments that used it", f"/registry/risks/{r['id']}")])],
            {"status": str(it.get("status") or ""), "dimension": str(it.get("dimension") or ""), "source": fw}))
    return rows


def _file_link(name):
    """Return a File-field value that opens the pattern/template JSON in a new tab.

    The 3-tuple (label, url, True) is rendered by ``_ui.html`` with ``target="_blank"``;
    the file itself is served by ``/catalogs/file/{name}``.
    """
    return [(name, f"/catalogs/file/{name}", True)] if name else None


def pattern_rows(store) -> list[dict]:
    """Listing rows for CALM patterns followed by RA templates."""
    rows = []
    ras = md.ras()
    for r in md.registry_rows("patterns", store):
        raw = r["raw"]
        used_in = [x["id"] for x in ras if any(sp.get("id") == r["id"] for sp in x["patterns"])]
        rows.append(_row(
            r["id"],
            [("mono", r["id"]), ("text", r["title"]), ("text", PATTERN_TYPE), ("badge", pending_label(r["status"])), ("text", f"v{r['version']}")],
            _action("patterns", r["id"], r["status"]) +
            [("Related controls", _link_list("controls", raw.get("related_controls") or [])),
             ("Related risks", _link_list("risks", raw.get("related_risks") or [])),
             ("Used in RA templates", _link_list("patterns", used_in)),
             ("Lifecycle", _life(raw.get("lifecycle"))),
             ("File", _file_link(raw.get("file")))],
            {"type": PATTERN_TYPE, "status": str(r["status"] or "")}))
    for r in md.registry_rows("ras", store):
        raw = r["raw"]
        rows.append(_row(
            r["id"],
            [("mono", r["id"]), ("text", f"Assessment requirements template {r['id']}"), ("text", RA_TYPE), ("badge", pending_label(r["status"])), ("text", f"v{r['version']}")],
            _action("ras", r["id"], r["status"], "Approving publishes the template so applications can be instantiated from it.") +
            [("Source patterns", [(f"{p['id']} v{p.get('version')}", f"/catalogs/patterns?focus={p['id']}") for p in raw.get("patterns") or []]),
             ("Lifecycle", _life(raw.get("lifecycle"))),
             ("File", _file_link(raw.get("file")))],
            {"type": RA_TYPE, "status": str(r["status"] or "")}))
    return rows


PENDING = "PENDING HUMAN REVIEW"
PENDING_STATES = {"WAITING_FOR_HUMAN", "DRAFT", "IN_REVIEW"}   # statuses shown as PENDING HUMAN REVIEW


def pending_label(status: str | None) -> str:
    """Display label for a status: anything waiting on a human reads PENDING HUMAN REVIEW."""
    return PENDING if str(status or "") in PENDING_STATES else str(status or "")


def _action(kind: str, item_id: str, status: str | None, note: str = "") -> list:
    """Detail row with the MVP Approve button when the record is pending human review (else none)."""
    if str(status or "") not in PENDING_STATES:
        return []
    return [("Action", {"action": f"/catalogs/{kind}/{item_id}/approve", "label": "Approve", "note": note})]


def assessment_rows(store) -> list[dict]:
    """Listing rows for assessments, newest first; each expands to a lazily loaded report."""
    rows = []
    for s in store.assessments():
        app = (s["app_id"] or "") + (f" (replay of {s['replay_of'][:8]})" if s["replay_of"] else "")
        status = pending_label(s["status"])
        rows.append(_row(
            s["trace_id"],
            [("text", app), ("badge", s["decision"] or "none"), ("badge", status), ("text", s["validation_status"]),
             ("text", s["time"]), ("mono", s["trace_id"][:12])],
            [], {"decision": s["decision"] or "none", "status": status, "application": str(s["app_id"] or "")},
            detail_url=f"/assessments/{s['trace_id']}?partial=1"))
        rows[-1]["search"] += " " + s["trace_id"]
    return rows


# ---------------------------------------------------------------- Source Registry sections
DOCS = Path(__file__).resolve().parents[4] / "docs"
SECTIONS = [("sources", "Extraction Sources"), ("dimensions", "Risk Dimensions"), ("scoring", "Scoring Profiles & Config"),
            ("adrs", "ADRs")]
CONFIG_TYPES = {"scoring_profile": "Scoring profile", "decision_matrix": "Decision logic", "gates": "Decision logic",
                "gap_rule": "Decision logic", "taxonomy": "Taxonomy", "decider_policy": "Decider policy", "roles": "Roles"}


def source_rows(store) -> list[dict]:
    """Listing rows for extraction sources."""
    rows = []
    for r in md.registry_rows("sources", store):
        s = r["raw"]
        fw = str(s.get("framework") or r["id"].split(":")[0])
        mit = (s.get("relations") or {}).get("mitigates") or []
        rows.append(_row(
            r["id"], [("mono", r["id"]), ("text", s.get("title")), ("text", s.get("kind")), ("text", fw), ("text", s.get("_file"))],
            [("Path in source repo", s.get("path")), ("Source file", s.get("_file")), ("Mitigates", mit),
             ("More", [("Lineage: where this source is used", f"/lineage/source/{r['id']}"), ("Registry entry", f"/registry/sources/{r['id']}")])],
            {"type": str(s.get("kind") or ""), "framework": fw}))
    return rows


def dimension_rows(store) -> list[dict]:
    """Listing rows for risk dimensions: those declared in the taxonomy plus any used only by risks."""
    tax = md._yaml(md.CONFIG / "taxonomy.yaml")
    declared = list(tax.get("dimensions") or [])
    attrs = tax.get("attributes") or {}
    risks = md.catalog_items("risks")
    names = declared + sorted({str(r.get("dimension")) for r in risks if r.get("dimension")} - set(declared))
    rows = []
    for name in names:
        mine = {k: v for k, v in attrs.items() if v.get("dimension") == name}
        rl = [md.item_id(r) for r in risks if r.get("dimension") == name]
        lines = []
        for k, v in mine.items():
            vals = "verbatim (recorded as given)" if v.get("verbatim") else (", ".join(f"{a} -> {b}" for a, b in (v.get("values") or {}).items()) or "any value")
            lines.append(f"{k} on {', '.join(v.get('element_types') or [])}: {vals}")
        rows.append(_row(
            name, [("text", name), ("text", ", ".join(mine) or "none"), ("text", str(len(rl)))],
            [("Taxonomy attributes", lines), ("Risks in this dimension", _link_list("risks", rl)),
             ("Note", "" if name in declared else "Used by risks but not declared in taxonomy.yaml.")],
            {"in_taxonomy": "Yes" if name in declared else "No", "has_risks": "Yes" if rl else "No"}))
    return rows


def scoring_rows(store) -> list[dict]:
    """Listing rows for the governance config files, including their full text."""
    rows = []
    for c in md.config_files():
        text = (md.CONFIG / c["file"]).read_text(encoding="utf-8")
        typ = CONFIG_TYPES.get(c["id"], "Config")
        rows.append(_row(
            c["id"], [("mono", c["id"]), ("text", typ), ("text", f"v{c['version']}" if c["version"] else ""), ("text", c["label"]), ("mono", c["sha256"][:12])],
            [("File", c["file"]), ("SHA-256", c["sha256"]), ("Content", {"pre": text}),
             ("More", [("Registry entry", f"/registry/{'scoring-profiles' if c['id'] == 'scoring_profile' else 'governance-config'}/{c['id']}")])],
            {"type": typ}))
    return rows


def _sections(path: Path) -> list[tuple[str, str]]:
    """Split a Markdown file on '## ' headings into (title, body) pairs; [] if the file is missing."""
    if not path.is_file():
        return []
    out: list[list] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            out.append([line[3:].strip(), []])
        elif out:
            out[-1][1].append(line)
    return [(t, "\n".join(b).strip()) for t, b in out]


def _summary(body: str, limit: int = 300) -> str:
    """First paragraph of ``body`` on one line, cut at a word boundary to about ``limit`` characters."""
    first = next((p for p in re.split(r"\n\s*\n", body) if p.strip()), "")
    text = re.sub(r"\s+", " ", first.replace("`", "")).strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " ..."


def adr_rows() -> list[dict]:
    """Design decisions: each '## ' section of docs/deliberate-changes.md, plus the 'Decisions' section of spike-notes.md."""
    rows = []
    for code, fname, only in (("DC", "deliberate-changes.md", None), ("SN", "spike-notes.md", {"Decisions"})):
        n = 0
        for title, body in _sections(DOCS / fname):
            if only and title not in only:
                continue
            n += 1
            status = "Resolved" if "RESOLVED" in title.upper() else "Open" if title.lower().startswith("open") else "Decision"
            clean = re.sub(r"\s*:?\s*RESOLVED\s*$", "", title).strip()
            rid = f"{code}-{n:02d}"
            rows.append(_row(rid, [("mono", rid), ("text", clean), ("badge", status), ("text", fname)],
                             [("Summary", _summary(body)), ("Full text", {"pre": body or "(no text)"}), ("Source document", f"docs/{fname}")],
                             {"status": status, "document": fname}))
    return rows

# ---------------------------------------------------------------- search, filter, paginate
def build_listing(rows: list[dict], params: dict[str, str], path: str, facets: list[tuple[str, str]],
                  page: int = 1, defaults: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """Apply search (q) and facet filters, honour ?focus=<id>, and paginate PAGE_SIZE rows per page."""
    params = {k: (v or "").strip() for k, v in params.items()}
    for k, v in (defaults or {}).items():
        params.setdefault(k, v)
    q = params.get("q", "").lower()
    active = {n: params[n] for n, _ in facets if params.get(n)}
    options = {n: sorted({r["facets"].get(n, "") for r in rows} - {""}) for n, _ in facets}

    def keep(r: dict) -> bool:
        """True if the row matches the search text and every active facet filter."""
        return (not q or q in r["search"]) and all(r["facets"].get(n) == v for n, v in active.items())

    view = [r for r in rows if keep(r)]
    focus = params.get("focus") or ""
    if focus and any(r["id"] == focus for r in rows):
        if not any(r["id"] == focus for r in view):  # a filter would hide the target: show it anyway
            q, active, view = "", {}, list(rows)
        page = next(i for i, r in enumerate(view) if r["id"] == focus) // PAGE_SIZE + 1
        for r in view:
            r["open"] = r["id"] == focus
    keep_params = {"q": q} if q else {}
    keep_params.update(active)
    total = len(view)
    pages = max(1, -(-total // PAGE_SIZE))
    page = min(max(page, 1), pages)
    start = (page - 1) * PAGE_SIZE
    shown = view[start:start + PAGE_SIZE]

    def link(p: int) -> str:
        """URL of page ``p`` that keeps the current search and filters (page 1 has no page parameter)."""
        qs = urlencode({**keep_params, **({"page": p} if p > 1 else {})})
        return path + (f"?{qs}" if qs else "")

    nums = sorted({1, pages, *range(max(1, page - 2), min(pages, page + 2) + 1)})
    links: list[tuple[str, Optional[str], bool]] = []
    prev = 0
    for n in nums:
        if prev and n - prev > 1:
            links.append(("...", None, False))
        links.append((str(n), link(n), n == page))
        prev = n
    return {"rows": shown, "q": q, "total": total, "page": page, "pages": pages, "start": start + 1 if total else 0,
            "end": start + len(shown), "links": links, "prev": link(page - 1) if page > 1 else None,
            "next": link(page + 1) if page < pages else None, "path": path,
            "filters": [{"name": n, "label": lab, "value": active.get(n, ""), "options": options[n]} for n, lab in facets]}
