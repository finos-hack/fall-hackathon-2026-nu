"""Composer: merge selected Patterns into ONE CALM 1.2 pattern (RA_Template) (Req 8.1, 8.2, 8.6, 8.7, 8.8).

Pure and deterministic. Input: patterns keyed by ID and a composition spec (YAML/dict). Output: the
template (sorted-key JSON text) or a list of conflicts/errors and no output.

Spec rules:
* ``components``: each RA component lists the pattern nodes it is built from (``P12/agent``). Their
  definitions are merged property by property; the same property defined differently in two patterns
  is a conflict naming both patterns. ``unique-id``, ``name`` and ``description`` are set by the spec.
* ``bind``: fixes a metadata property declared by the patterns to a ``const``. Binding a property no
  pattern declares is an error: the Composer never adds controls or metadata.
* ``relationships``: either a pattern relationship (``from: P12/agent-uses-tool`` with a ``map`` from
  pattern roles to components) or a plain ``connects`` wiring between components.
* ``options``: CALM ``options`` relationships. Items an option controls carry ``option: <id>``.
  ``oneOf`` choices must name the same number of nodes and relationships (one position per index, so
  the generated architecture still lines up with ``prefixItems``). At most one ``anyOf`` option; its
  items go last.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from agip_shared.hashing import sha256_hex

COMPOSER_VERSION = 1
CALM_SCHEMA = "https://calm.finos.org/release/1.2/meta/calm.json"
CORE = "https://calm.finos.org/release/1.2/meta/core.json#/defs/"
_IDENTITY = ("unique-id", "name", "description")


@dataclass(frozen=True)
class Conflict:
    """The same property defined differently by two patterns on one component."""
    component: str
    key: str
    patterns: tuple[str, str]

    def __str__(self) -> str:
        """Message naming the component, property and both patterns."""
        return f"conflict on {self.component}.{self.key} between {self.patterns[0]} and {self.patterns[1]}"


@dataclass
class ComposeResult:
    """Outcome of :func:`compose`: either ``template``/``text`` or ``conflicts``/``errors`` (never both)."""
    template: Optional[dict[str, Any]] = None
    text: Optional[str] = None
    conflicts: list[Conflict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when a template was produced."""
        return self.template is not None


def dumps(obj: Any) -> str:
    """Deterministic JSON text (sorted keys, 2-space indent, trailing newline) so the SHA-256 is reproducible."""
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _items(pattern: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """``prefixItems`` of ``properties.<kind>`` in a pattern, or an empty list."""
    return (((pattern.get("properties") or {}).get(kind) or {}).get("prefixItems")) or []


def _uid(defn: dict[str, Any]) -> Optional[str]:
    """The ``unique-id`` const of a node/relationship definition, or None."""
    return ((defn.get("properties") or {}).get("unique-id") or {}).get("const")


def _find(patterns: dict[str, Any], ref: str, kind: str) -> tuple[str, dict[str, Any]]:
    """Resolve ``<pattern>/<unique-id>`` to ``(pattern id, definition)``. Raises KeyError if the pattern is not selected or lacks the item."""
    pid, _, local = ref.partition("/")
    if pid not in patterns:
        raise KeyError(f"{ref}: pattern {pid} not selected")
    for d in _items(patterns[pid], kind):
        if _uid(d) == local:
            return pid, d
    raise KeyError(f"{ref}: no {kind[:-1]} '{local}' in {pid}")


def _check_value(value: Any, schema: dict[str, Any]) -> Optional[str]:
    """Check a ``bind`` value against the property schema (const, enum, type, bounds); return the reason or None."""
    if "const" in schema and value != schema["const"]:
        return f"must equal {schema['const']!r}"
    if "enum" in schema and value not in schema["enum"]:
        return f"must be one of {schema['enum']}"
    t = schema.get("type")
    types = {"string": str, "boolean": bool, "number": (int, float), "integer": int, "array": list, "object": dict}
    if t in types and (not isinstance(value, types[t]) or (t in ("number", "integer") and isinstance(value, bool))):
        return f"must be of type {t}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            return f"must be >= {schema['minimum']}"
        if "maximum" in schema and value > schema["maximum"]:
            return f"must be <= {schema['maximum']}"
    return None


def _merge_nodes(comp_id: str, parts: list[tuple[str, dict[str, Any]]], conflicts: list[Conflict]) -> dict[str, Any]:
    """Merge several pattern node definitions into one, property by property, recording a Conflict when two patterns differ. Metadata is merged per property; ``required`` lists are unioned."""
    merged: dict[str, Any] = {"$ref": CORE + "node", "type": "object", "properties": {}, "required": []}
    owner: dict[str, str] = {}
    meta_props: dict[str, Any] = {}
    meta_req: set[str] = set()
    for pid, d in parts:
        for key, val in (d.get("properties") or {}).items():
            if key in _IDENTITY:
                continue
            if key == "metadata":
                for mk, mv in (val.get("properties") or {}).items():
                    tag = f"metadata.{mk}"
                    if mk in meta_props and meta_props[mk] != mv:
                        conflicts.append(Conflict(comp_id, tag, (owner[tag], pid)))
                    elif mk not in meta_props:
                        meta_props[mk], owner[tag] = copy.deepcopy(mv), pid
                meta_req |= set(val.get("required") or [])
                continue
            if key in merged["properties"] and merged["properties"][key] != val:
                conflicts.append(Conflict(comp_id, key, (owner[key], pid)))
            elif key not in merged["properties"]:
                merged["properties"][key], owner[key] = copy.deepcopy(val), pid
        merged["required"] = sorted(set(merged["required"]) | set(d.get("required") or []))
    if meta_props:
        merged["properties"]["metadata"] = {"type": "object", "properties": meta_props, "required": sorted(meta_req)}
    return merged


def _connects(uid: str, desc: str, src: str, dst: str) -> dict[str, Any]:
    """Build a ``connects`` relationship definition from ``src`` to ``dst``."""
    return {"$ref": CORE + "relationship", "type": "object",
            "properties": {"unique-id": {"const": uid}, "description": {"const": desc},
                           "relationship-type": {"const": {"connects": {"source": {"node": src},
                                                                         "destination": {"node": dst}}}}},
            "required": ["unique-id", "description", "relationship-type"]}


def _option(opt: dict[str, Any]) -> dict[str, Any]:
    """Build a CALM ``options`` relationship whose decisions list the nodes/relationships each choice enables."""
    decisions = [{"$ref": CORE + "decision", "type": "object",
                  "properties": {"description": {"const": c["description"]}, "nodes": {"const": list(c.get("nodes") or [])},
                                 "relationships": {"const": list(c.get("relationships") or [])}}}
                 for c in opt["choices"]]
    return {"$ref": CORE + "relationship", "type": "object",
            "properties": {"unique-id": {"const": opt["id"]}, "description": {"const": opt["description"]},
                           "relationship-type": {"type": "object", "properties": {"options": {
                               "type": "array", "prefixItems": [{opt["type"]: decisions}]}}}},
            "required": ["unique-id", "description", "relationship-type"]}


def _positions(defs: dict[str, dict[str, Any]], order: list[str], options: list[dict[str, Any]], kind: str,
               errors: list[str]) -> tuple[list[dict[str, Any]], int]:
    """Fixed items, then one position per oneOf index, then anyOf items. Returns (prefixItems, minItems)."""
    controlled: dict[str, str] = {}
    out = [defs[i] for i in order if not defs[i].get("x-option")]
    minimum = len(out)
    for opt in sorted(options, key=lambda o: (o["type"] == "anyOf", o["id"])):
        lists = [list(c.get(kind) or []) for c in opt["choices"]]
        for lst in lists:
            for i in lst:
                if i not in defs:
                    errors.append(f"option {opt['id']}: unknown {kind[:-1]} '{i}'")
                elif defs[i].get("x-option") != opt["id"]:
                    errors.append(f"option {opt['id']}: '{i}' is not marked option: {opt['id']}")
                controlled[i] = opt["id"]
        if opt["type"] == "oneOf":
            if len({len(l) for l in lists}) > 1:
                errors.append(f"option {opt['id']}: oneOf choices must name the same number of {kind}")
                continue
            for j in range(len(lists[0]) if lists else 0):
                alts = [defs[l[j]] for l in lists if l[j] in defs]
                out.append({"oneOf": alts})
                minimum += 1
        else:
            # anyOf items keep spec order so the generated template is deterministic.
            for i in sorted({i for l in lists for i in l if i in defs}, key=order.index):
                out.append({"anyOf": [defs[i]]})
    for i in order:
        if defs[i].get("x-option") and i not in controlled:
            errors.append(f"{kind[:-1]} '{i}' is marked option: {defs[i]['x-option']} but no choice names it")
    for d in defs.values():
        d.pop("x-option", None)
    return out, minimum


def compose(patterns: dict[str, dict[str, Any]], spec: dict[str, Any]) -> ComposeResult:
    """Merge the selected patterns per the spec into one CALM 1.2 template.

    Returns conflicts/errors and no template if anything fails; otherwise the template dict and its deterministic text. Never adds controls or metadata not declared by a pattern.
    """
    res = ComposeResult()
    selected = {pid: patterns[pid] for pid in sorted(spec.get("patterns") or []) if pid in patterns}
    for pid in spec.get("patterns") or []:
        if pid not in patterns:
            res.errors.append(f"pattern {pid} not found in library")
    options = sorted(spec.get("options") or [], key=lambda o: o["id"])
    if sum(o.get("type") == "anyOf" for o in options) > 1:
        res.errors.append("at most one anyOf option is supported")
    if any(o.get("type") not in ("oneOf", "anyOf") for o in options):
        res.errors.append("option type must be oneOf or anyOf")

    nodes: dict[str, dict[str, Any]] = {}
    node_order: list[str] = []
    for comp in spec.get("components") or []:
        cid = comp["id"]
        if cid in nodes:
            res.errors.append(f"component {cid} defined twice")
            continue
        try:
            parts = [_find(selected, ref, "nodes") for ref in comp["from"]]
        except KeyError as exc:
            res.errors.append(str(exc.args[0]))
            continue
        d = _merge_nodes(cid, parts, res.conflicts)
        d["properties"].update({"unique-id": {"const": cid}, "name": {"const": comp["name"]},
                                "description": {"const": comp["description"]}})
        meta = (d["properties"].get("metadata") or {}).get("properties") or {}
        for k, v in sorted((comp.get("bind") or {}).items()):
            if k not in meta:
                res.errors.append(f"{cid}: bind '{k}' is not declared by patterns {sorted({p for p, _ in parts})}")
                continue
            why = _check_value(v, meta[k])
            if why:
                res.errors.append(f"{cid}: bind '{k}'={v!r} {why}")
            meta[k] = {"const": v}
        if comp.get("option"):
            d["x-option"] = comp["option"]
        nodes[cid] = d
        node_order.append(cid)

    rels: dict[str, dict[str, Any]] = {}
    rel_order: list[str] = []
    for r in spec.get("relationships") or []:
        rid = r["id"]
        if rid in rels:
            res.errors.append(f"relationship {rid} defined twice")
            continue
        if "from" in r:
            try:
                pid, base = _find(selected, r["from"], "relationships")
            except KeyError as exc:
                res.errors.append(str(exc.args[0]))
                continue
            ends = base["properties"]["relationship-type"]["const"]["connects"]
            src = (r.get("map") or {}).get(ends["source"]["node"])
            dst = (r.get("map") or {}).get(ends["destination"]["node"])
            desc = r.get("description") or base["properties"]["description"]["const"]
        else:
            src, dst = r["connects"]
            desc = r["description"]
        if src not in nodes or dst not in nodes:
            res.errors.append(f"relationship {rid}: endpoint not a component ({src} -> {dst})")
            continue
        d = _connects(rid, desc, src, dst)
        if r.get("option"):
            d["x-option"] = r["option"]
        rels[rid] = d
        rel_order.append(rid)

    if res.conflicts or res.errors:
        res.conflicts.sort(key=lambda c: (c.component, c.key))
        return res

    node_items, node_min = _positions(nodes, node_order, options, "nodes", res.errors)
    rel_items, rel_min = _positions(rels, rel_order, options, "relationships", res.errors)
    if res.errors:
        return res
    rel_items = [_option(o) for o in options] + rel_items
    rel_min += len(options)
    template = {
        "$schema": CALM_SCHEMA,
        "$id": f"https://agip.example/templates/{spec['ra_id']}.json",
        "title": spec.get("title", spec["ra_id"]),
        "description": spec.get("description", ""),
        "metadata": {
            "ra-id": spec["ra_id"], "ra-version": int(spec["version"]), "composer-version": COMPOSER_VERSION,
            "source-patterns": [{"id": pid, "version": int((p.get("metadata") or {}).get("version", 1)),
                                 "sha256": sha256_hex(dumps(p))} for pid, p in selected.items()],
        },
        "type": "object",
        "properties": {
            "nodes": {"type": "array", "minItems": node_min, "maxItems": len(node_items), "prefixItems": node_items},
            "relationships": {"type": "array", "minItems": rel_min, "maxItems": len(rel_items), "prefixItems": rel_items},
        },
        "required": ["nodes", "relationships"],
    }
    res.template, res.text = template, dumps(template)
    return res


def load_spec(path: Any) -> dict[str, Any]:
    """Read a composition spec (YAML) from ``path``."""
    import yaml
    from pathlib import Path
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def main(argv: Optional[list[str]] = None) -> int:
    """``python -m calm_generation.composer [spec.yaml]``: compose and write ``templates/<RA>.json``."""
    import sys
    from pathlib import Path

    from .pattern_library import FRAMEWORK_ROOT, load_patterns
    args = argv if argv is not None else sys.argv[1:]
    spec_path = Path(args[0]) if args else FRAMEWORK_ROOT / "templates" / "RA03-LITE.compose.yaml"
    spec = load_spec(spec_path)
    res = compose(load_patterns(), spec)
    for c in res.conflicts:
        print(c, file=sys.stderr)
    for e in res.errors:
        print(f"error: {e}", file=sys.stderr)
    if not res.ok:
        return 1
    out = FRAMEWORK_ROOT / "templates" / f"{spec['ra_id']}.json"
    out.write_text(res.text, encoding="utf-8")
    print(f"{out.name} sha256={sha256_hex(res.text)[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())