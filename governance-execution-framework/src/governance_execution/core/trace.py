"""Traceability graph (Req 25.3): decision -> gate / matrix cell -> control / risk -> Rule_Code + JSON path ->
CALM element -> pattern and template version -> AIGF / CCC source ID. Edges are directed; the explorer
walks them both ways. Pure: built from persisted artifacts only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

_IDX = re.compile(r"^\$\.nodes\[(\d+)\]")


@dataclass
class Graph:
    """Directed traceability graph of nodes keyed by id and (from, to, label) edges."""
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: list[tuple[str, str, str]] = field(default_factory=list)

    def add(self, nid: str, kind: str, label: str, **attrs: Any) -> str:
        """Add a node if the id is new (an existing node is kept unchanged) and return its id."""
        self.nodes.setdefault(nid, {"id": nid, "kind": kind, "label": label, **attrs})
        return nid

    def link(self, a: str, b: str, label: str = "") -> None:
        """Add the directed edge a -> b once; duplicates are ignored."""
        if (a, b, label) not in self.edges:
            self.edges.append((a, b, label))

    def outgoing(self, nid: str) -> list[tuple[str, str]]:
        """(target, label) pairs of edges leaving ``nid``."""
        return [(b, l) for a, b, l in self.edges if a == nid]

    def incoming(self, nid: str) -> list[tuple[str, str]]:
        """(source, label) pairs of edges arriving at ``nid``."""
        return [(a, l) for a, b, l in self.edges if b == nid]

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form with nodes sorted by id and edges in insertion order."""
        return {"nodes": sorted(self.nodes.values(), key=lambda n: n["id"]),
                "edges": [{"from": a, "to": b, "label": l} for a, b, l in self.edges]}


def element_of(path: str, app_model: dict[str, Any]) -> Optional[str]:
    """Unique id of the node addressed by a ``$.nodes[i]...`` JSON path, or None if the path or index does not resolve."""
    m = _IDX.match(path or "")
    nodes = app_model.get("nodes") or []
    if m and int(m.group(1)) < len(nodes):
        return nodes[int(m.group(1))].get("unique-id")
    return None


def _source(g: Graph, src: dict[str, Any]) -> Optional[str]:
    """Add a source node for an AIGF/CCC reference and return its id; None when the reference has no id."""
    if not src.get("id"):
        return None
    return g.add(f"source:{src.get('framework')}:{src['id']}", "source", f"{src.get('framework')} {src['id']}")


def build(art: dict[str, Any], compose_spec: Optional[dict[str, Any]] = None) -> Graph:
    """``art``: artifact kind -> content (decision, control_gap, risk_profile, app_model, calm_validation, versions)."""
    g = Graph()
    app = art.get("app_model") or {}
    decision = art.get("decision") or {}
    d = g.add("decision", "decision", f"Decision: {decision.get('decision', 'none')}")
    versions = art.get("versions") or {}
    tpl_id = versions.get("template_id")
    tpl = g.add(f"template:{tpl_id}", "template", f"Template {tpl_id}") if tpl_id else None
    if tpl:
        g.link(d, tpl, "assessed template")
    patterns_by_element: dict[str, list[str]] = {}
    for comp in (compose_spec or {}).get("components") or []:
        patterns_by_element[comp["id"]] = sorted({ref.split("/")[0] for ref in comp["from"]})
    pat_versions = {p["id"]: p["version"] for p in ((compose_spec or {}).get("_source_patterns") or [])}

    def element(eid: str) -> str:
        """Add the CALM element node and link it to the template and the patterns it was composed from."""
        n = g.add(f"element:{eid}", "element", eid)
        if tpl:
            g.link(n, tpl, "instantiated from")
        for pid in patterns_by_element.get(eid, []):
            p = g.add(f"pattern:{pid}", "pattern", f"Pattern {pid} v{pat_versions.get(pid, '?')}")
            g.link(n, p, "built from")
            if tpl:
                g.link(tpl, p, "composes")
        return n

    def finding(owner: str, f: dict[str, Any]) -> None:
        """Link ``owner`` to the finding's rule code, JSON path and (if resolvable) CALM element."""
        rc = g.add(f"rule:{f['rule_code']}", "rule", f["rule_code"])
        g.link(owner, rc, "rule")
        p = g.add(f"path:{f['path']}", "path", f["path"])
        g.link(rc, p, "matched")
        eid = element_of(f["path"], app)
        if eid:
            g.link(p, element(eid), "in")

    controls = {c["control_id"]: c for c in (art.get("control_gap") or {}).get("controls") or []}
    for c in controls.values():
        if c["status"] not in ("FAIL", "ERROR"):
            continue
        n = g.add(f"control:{c['control_id']}", "control", f"{c['control_id']} {c['status']}", status=c["status"])
        for f in c.get("findings") or []:
            finding(n, f)
        s = _source(g, c.get("source") or {})
        if s:
            g.link(n, s, "source")
    for r in (art.get("risk_profile") or {}).get("risks") or []:
        n = g.add(f"risk:{r['risk_id']}", "risk", f"{r['risk_id']} {r['severity']}", severity=r["severity"])
        for f in r.get("findings") or []:
            finding(n, f)
        s = _source(g, r.get("source") or {})
        if s:
            g.link(n, s, "source")

    for gate in decision.get("gates_evaluated") or []:
        if not gate.get("fired"):
            continue
        gn = g.add(f"gate:{gate['id']}", "gate", f"Gate {gate['id']} -> {gate['outcome']}")
        g.link(d, gn, "overridden" if gate.get("overridden") else "fired")
        if gate["id"].startswith("G1"):
            cv = art.get("calm_validation") or {}
            for e in cv.get("errors") or []:
                p = g.add(f"calm:{e['path']}", "path", f"CALM {e['code']} {e['path']}")
                g.link(gn, p, "calm error")
                m = re.match(r"^/nodes/([^/]+)", e.get("path") or "")
                if m:
                    g.link(p, element(m.group(1)), "in")
        elif gate["id"].startswith("G2"):
            for cid, c in controls.items():
                if c["status"] == "FAIL" and c.get("mandatory"):
                    g.link(gn, f"control:{cid}", "control")
        elif gate["id"].startswith("G3"):
            for u in (art.get("risk_profile") or {}).get("unevaluable") or []:
                rid = u.split(":")[0]
                n = g.add(f"risk:{rid}", "risk", f"{rid} unevaluable")
                g.link(gn, n, "unevaluable")
    cell = decision.get("matrix_cell") or {}
    if cell.get("evaluated"):
        cn = g.add("cell", "matrix_cell", f"Matrix {cell['gap']} x {cell['risk']} -> {cell['result']}")
        g.link(d, cn, "matrix")
        for cid, c in controls.items():
            if c["status"] == "FAIL":
                g.link(cn, f"control:{cid}", "gap")
        for r in (art.get("risk_profile") or {}).get("risks") or []:
            g.link(cn, f"risk:{r['risk_id']}", "risk")
    for nid, n in list(g.nodes.items()):  # findings not reached via a gate or matrix cell (e.g. a gate decided) stay traceable
        if n["kind"] in ("control", "risk") and not g.incoming(nid):
            g.link(d, nid, "assessed")
    return g
