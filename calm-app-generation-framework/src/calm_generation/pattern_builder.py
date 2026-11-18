"""Build a CALM 1.2 pattern from a structured spec ("Build Pattern" workflow), and the reverse.

Spec (YAML/dict)::

    pattern_id: P20                       # P<digits>
    slug: remediation-tool                # lowercase-kebab, used in the file name
    title: Remediation Tool
    description: Agent applies allow-listed fixes to tagged hosts.
    version: 1                            # optional; set by the hash rule on save
    nodes:
      - id: agent                         # unique-id inside the pattern
        type: ai:agent                    # CALM node-type
        name: Agent
        description: AI agent that applies remediation.
        metadata:                         # JSON-schema per field: {const}, {enum}, {type[, minimum, maximum]}
          remediation_scope: {enum: [allow-listed, any]}
      - id: target-host
        type: system
        name: Target Host
        port: true                        # connection point: a role another component fills, never emitted
    relationships:
      - {id: agent-remediates-host, description: Agent applies fixes, from: agent, to: target-host}
    related_controls: [AIGF-MI-018]
    related_risks: [AIGF-RI-024]

The output has the same shape as the seed library (``scripts/build_patterns.py``): every array pinned to its
entries, every identity field ``const``. Saving writes ``<pid>-<slug>.json`` and a DRAFT registry entry; unchanged
content is not rewritten, changed content is version + 1 (hash rule). Approval publishes it (lifecycle).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from agip_shared import versioned_write as vw
from agip_shared.hashing import sha256_hex

from . import lifecycle as lc
from . import pattern_library as pl

CORE = "https://calm.finos.org/release/1.2/meta/core.json#/defs/"
NODE_TYPES = ("actor", "ecosystem", "system", "service", "database", "network", "ldap", "webclient", "data-asset",
              "ai:agent", "ai:tool", "ai:llm")
_PID = re.compile(r"^P\d{2,3}$")
_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_FIELD = re.compile(r"^[a-z][a-z0-9_]*$")
_SCHEMA_KEYS = {"const", "enum", "type", "minimum", "maximum"}
_TYPES = {"string", "number", "integer", "boolean"}


def library_fields(patterns: dict[str, Any], exclude: str = "") -> dict[str, tuple[str, dict[str, Any]]]:
    """Metadata field name -> (first pattern id, schema) across the library (``exclude``: the pattern being edited)."""
    out: dict[str, tuple[str, dict[str, Any]]] = {}
    for pid, p in sorted(patterns.items()):
        if pid == exclude:
            continue
        for n in ((p.get("properties") or {}).get("nodes") or {}).get("prefixItems") or []:
            for f, sch in ((((n.get("properties") or {}).get("metadata") or {}).get("properties")) or {}).items():
                out.setdefault(f, (pid, sch))
    return out


def field_conflicts(spec: dict[str, Any], patterns: dict[str, Any]) -> list[str]:
    """A field name already used in the library must keep its schema, or composing the patterns conflicts."""
    lib = library_fields(patterns, str(spec.get("pattern_id") or ""))
    errs = []
    for n in spec.get("nodes") or []:
        for f, sch in ((n or {}).get("metadata") or {}).items():
            if f in lib and "const" not in sch and dict(sch) != lib[f][1] and "const" not in lib[f][1]:
                errs.append(f"field {f!r} already exists in {lib[f][0]} as {json.dumps(lib[f][1])}; reuse it exactly or use another name")
    return errs


def check_spec(spec: Any) -> list[str]:
    """Problems with a spec before building (shape, ids, field schemas, relationship endpoints)."""
    if not isinstance(spec, dict):
        return ["the spec must be a mapping"]
    errs = []
    if not _PID.match(str(spec.get("pattern_id") or "")):
        errs.append("pattern_id must look like P20")
    if not _SLUG.match(str(spec.get("slug") or "")):
        errs.append("slug must be lowercase-kebab-case")
    for k in ("title", "description"):
        if not str(spec.get(k) or "").strip():
            errs.append(f"{k} is required")
    nodes = spec.get("nodes") or []
    if not isinstance(nodes, list) or not nodes:
        return errs + ["at least one node is required"]
    ids = []
    for i, n in enumerate(nodes):
        where = f"nodes[{i}]"
        if not isinstance(n, dict):
            errs.append(f"{where} must be a mapping")
            continue
        if not _SLUG.match(str(n.get("id") or "")):
            errs.append(f"{where}.id must be lowercase-kebab-case")
        ids.append(n.get("id"))
        if n.get("type") not in NODE_TYPES:
            errs.append(f"{where}.type must be one of {', '.join(NODE_TYPES)}")
        if not str(n.get("name") or "").strip():
            errs.append(f"{where}.name is required")
        meta = n.get("metadata") or {}
        if n.get("port") and meta:
            errs.append(f"{where}: a port (connection point) has no metadata")
        if not isinstance(meta, dict):
            errs.append(f"{where}.metadata must be a mapping")
            continue
        for f, sch in meta.items():
            if not _FIELD.match(str(f)):
                errs.append(f"{where}.metadata.{f}: field names are lower_snake_case")
            if not isinstance(sch, dict) or not sch or set(sch) - _SCHEMA_KEYS:
                errs.append(f"{where}.metadata.{f}: use {{const: v}}, {{enum: [..]}} or {{type: string|number|integer|boolean}}")
                continue
            if "enum" in sch and (not isinstance(sch["enum"], list) or len(sch["enum"]) < 2):
                errs.append(f"{where}.metadata.{f}: enum needs at least two values")
            if "type" in sch and sch["type"] not in _TYPES:
                errs.append(f"{where}.metadata.{f}: type must be one of {sorted(_TYPES)}")
    if len(set(ids)) != len(ids):
        errs.append("node ids must be unique")
    if not any(not n.get("port") for n in nodes if isinstance(n, dict)):
        errs.append("at least one node must not be a port")
    for i, r in enumerate(spec.get("relationships") or []):
        if not isinstance(r, dict) or not _SLUG.match(str(r.get("id") or "")):
            errs.append(f"relationships[{i}].id must be lowercase-kebab-case")
            continue
        for end in ("from", "to"):
            if r.get(end) not in ids:
                errs.append(f"relationships[{i}].{end} must be one of the node ids {ids}")
    for k in ("related_controls", "related_risks"):
        if not isinstance(spec.get(k) or [], list):
            errs.append(f"{k} must be a list of catalog IDs")
    return errs


def _node(n: dict[str, Any]) -> dict[str, Any]:
    desc = str(n.get("description") or (f"{n['name']} (connection point)" if n.get("port") else n["name"]))
    props: dict[str, Any] = {"unique-id": {"const": n["id"]}, "node-type": {"const": n["type"]},
                             "name": {"const": n["name"]}, "description": {"const": desc}}
    required = ["unique-id", "node-type", "name", "description"]
    meta = n.get("metadata") or {}
    if meta and not n.get("port"):
        props["metadata"] = {"type": "object", "properties": {k: dict(v) for k, v in meta.items()}, "required": sorted(meta)}
        required.append("metadata")
    return {"$ref": CORE + "node", "type": "object", "properties": props, "required": required}


def _rel(r: dict[str, Any]) -> dict[str, Any]:
    return {"$ref": CORE + "relationship", "type": "object",
            "properties": {"unique-id": {"const": r["id"]}, "description": {"const": str(r.get("description") or r["id"])},
                           "relationship-type": {"const": {"connects": {"source": {"node": r["from"]},
                                                                         "destination": {"node": r["to"]}}}}},
            "required": ["unique-id", "description", "relationship-type"]}


def build(spec: dict[str, Any], status: str = "DRAFT") -> dict[str, Any]:
    """The CALM 1.2 pattern for a spec (call ``check_spec`` first)."""
    pid, nodes, rels = spec["pattern_id"], [_node(n) for n in spec["nodes"]], [_rel(r) for r in spec.get("relationships") or []]
    return {
        "$schema": lc.CALM_SCHEMA,
        "$id": f"https://agip.example/patterns/{pid}-{spec['slug']}.json",
        "title": f"{pid} {spec['title']}",
        "description": spec["description"],
        "metadata": {"pattern-id": pid, "version": int(spec.get("version") or 1), "status": status,
                     "related_controls": list(spec.get("related_controls") or []),
                     "related_risks": list(spec.get("related_risks") or [])},
        "type": "object",
        "properties": {
            "nodes": {"type": "array", "minItems": len(nodes), "maxItems": len(nodes), "prefixItems": nodes},
            "relationships": {"type": "array", "minItems": len(rels), "maxItems": len(rels), "prefixItems": rels},
        },
        "required": ["nodes", "relationships"],
    }


def spec_of(pattern: dict[str, Any]) -> dict[str, Any]:
    """The editable spec of an existing pattern (start a new pattern from it, or edit it)."""
    md = pattern.get("metadata") or {}
    pid = md.get("pattern-id") or ""
    title = re.sub(rf"^{re.escape(pid)}\s+", "", str(pattern.get("title") or pid))
    m = re.search(rf"/{re.escape(pid)}-([a-z0-9-]+)\.json$", str(pattern.get("$id") or ""))
    out: dict[str, Any] = {"pattern_id": pid, "slug": m.group(1) if m else re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-"),
                           "title": title, "description": pattern.get("description") or "", "nodes": [], "relationships": []}
    for n in ((pattern.get("properties") or {}).get("nodes") or {}).get("prefixItems") or []:
        p = n.get("properties") or {}
        meta = ((p.get("metadata") or {}).get("properties")) or {}
        node = {"id": p["unique-id"]["const"], "type": p["node-type"]["const"], "name": p["name"]["const"],
                "description": (p.get("description") or {}).get("const", "")}
        if meta:
            node["metadata"] = meta
        elif node["description"].endswith("(connection point)"):
            node["port"] = True
        out["nodes"].append(node)
    for r in ((pattern.get("properties") or {}).get("relationships") or {}).get("prefixItems") or []:
        p = r.get("properties") or {}
        c = ((p.get("relationship-type") or {}).get("const") or {}).get("connects") or {}
        out["relationships"].append({"id": p["unique-id"]["const"], "description": (p.get("description") or {}).get("const", ""),
                                     "from": (c.get("source") or {}).get("node"), "to": (c.get("destination") or {}).get("node")})
    out["related_controls"] = list(md.get("related_controls") or [])
    out["related_risks"] = list(md.get("related_risks") or [])
    return out


def _content(pattern: dict[str, Any]) -> str:
    """Hash input: the pattern without version, status and approver (lifecycle fields)."""
    p = json.loads(json.dumps(pattern))
    for k in ("version", "status", "approved_by"):
        p["metadata"].pop(k, None)
    return pl.dumps(p)


def save(spec: dict[str, Any], *, patterns_dir: Path = pl.PATTERN_DIR, registry: Path = lc.REGISTRY,
         by: str = "dashboard", catalogs: Path = lc.CATALOGS) -> dict[str, Any]:
    """Validate and store a pattern as DRAFT. Returns {pattern_id, action, version, state, errors, path}.

    Hash rule: identical content -> unchanged (no write, no state change); changed content -> version + 1 and DRAFT
    again (the published file is replaced only on save; templates already composed keep their own copy)."""
    errs = check_spec(spec)
    if errs:
        return {"pattern_id": spec.get("pattern_id") if isinstance(spec, dict) else None, "action": "rejected", "errors": errs}
    pid = spec["pattern_id"]
    reg = lc.load(registry)
    prev = (reg.get("entries") or {}).get(pid)
    if prev is not None and prev.get("kind") != "pattern":
        return {"pattern_id": pid, "action": "rejected", "errors": [f"{pid} is already used by a {prev.get('kind')}"]}
    existing = pl.load_patterns(patterns_dir).get(pid)
    clash = field_conflicts(spec, pl.load_patterns(patterns_dir))
    if clash:
        return {"pattern_id": pid, "action": "rejected", "errors": clash}
    draft = build({**spec, "version": 1})
    same = existing is not None and _content(existing) == _content(draft)
    if same:
        return {"pattern_id": pid, "action": "unchanged", "version": existing["metadata"].get("version"),
                "state": (prev or {}).get("state"), "errors": [], "path": None}
    version = int((existing or {}).get("metadata", {}).get("version") or 0) + 1 if existing else 1
    pattern = build({**spec, "version": version})
    entry = {"kind": "pattern", "source": f"dashboard:{by}", "version": version}
    shape = lc.validate_pattern_shape(pattern, entry, catalogs)
    if shape:
        return {"pattern_id": pid, "action": "rejected", "errors": shape}
    for old in patterns_dir.glob(f"{pid}-*.json"):          # slug may have changed: one file per pattern id
        if old.name != f"{pid}-{spec['slug']}.json":
            old.unlink()
    path = patterns_dir / f"{pid}-{spec['slug']}.json"
    text = pl.dumps(pattern)
    vw.write(path, text, content_hash=sha256_hex(_content(pattern)), version=version)
    history = list((prev or {}).get("history") or [])
    history.append({"from": (prev or {}).get("state"), "to": "DRAFT", "by": by, "role": "pattern-author",
                    "rationale": "new pattern" if prev is None else f"revised to version {version}", "at": lc.now()})
    reg.setdefault("entries", {})[pid] = {"kind": "pattern", "state": "DRAFT", "source": entry["source"], "version": version,
                                          "sha256": sha256_hex(text), "history": history}
    lc.save(reg, registry)
    return {"pattern_id": pid, "action": "created" if prev is None else "revised", "version": version, "state": "DRAFT",
            "errors": [], "path": str(path)}


def mark_approved(pid: str, by: str, *, patterns_dir: Path = pl.PATTERN_DIR, registry: Path = lc.REGISTRY) -> None:
    """After a pattern is APPROVED/PUBLISHED, record the approver in its file (as the seed library does) and refresh
    the registry hash. Lifecycle fields are not content, so the version does not change."""
    pats = pl.load_patterns(patterns_dir)
    p = pats.get(pid)
    reg = lc.load(registry)
    e = (reg.get("entries") or {}).get(pid)
    if p is None or e is None or e.get("state") not in lc.COMPOSABLE:
        return
    md = p["metadata"]
    if md.get("status") == "APPROVED" and md.get("approved_by"):
        return
    md.update(status="APPROVED", approved_by=by)
    path = next(patterns_dir.glob(f"{pid}-*.json"))
    text = pl.dumps(p)
    vw.write(path, text, content_hash=sha256_hex(_content(p)), version=int(md.get("version") or 1))
    e["sha256"] = sha256_hex(text)
    lc.save(reg, registry)


def next_id(patterns_dir: Path = pl.PATTERN_DIR) -> str:
    """The next free pattern id (P<max+1>)."""
    nums = [int(k[1:]) for k in pl.load_patterns(patterns_dir) if _PID.match(k)]
    return f"P{(max(nums) + 1) if nums else 1:02d}"
