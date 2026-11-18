"""Attributes_Form: generate from a PUBLISHED template and validate a filled form (Req 9.1-9.4).

The form lists one attribute per free (non-``const``) metadata property of each template component,
plus one entry per ``options`` relationship. Validation checks presence, type, allowed values,
lower bounds and placeholder coverage. It never calls the Decider. Other schema constraints (for
example upper bounds) are enforced by ``calm validate`` on the generated App_Model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from agip_shared.hashing import canonical_hash, sha256_hex

OMITTED = "(omitted by calm generate)"


class TemplateNotPublished(Exception):
    """Raised when a form is requested for a template whose status is not PUBLISHED."""
    pass


@dataclass(frozen=True)
class FieldError:
    """One validation problem: the form field (or attribute/option name) and a human-readable message."""
    field: str
    message: str

    def __str__(self) -> str:
        """Render as ``field: message``."""
        return f"{self.field}: {self.message}"


def _slug(text: str) -> str:
    """Lower-case ``text`` and collapse runs of non-alphanumerics into single dashes (used for option choice keys)."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def attr_name(node_id: str, prop: str) -> str:
    """Attribute name for a node metadata property: ``<NODE_ID>_<PROP>`` upper-cased, non-alphanumerics replaced by ``_``."""
    return re.sub(r"[^A-Z0-9]+", "_", f"{node_id}_{prop}".upper()).strip("_")


def iter_node_defs(template: dict[str, Any]):
    """(node definition, optional) for every node the template can emit."""
    for item in template["properties"]["nodes"]["prefixItems"]:
        for key in ("oneOf", "anyOf"):
            if key in item:
                for d in item[key]:
                    yield d, True
                break
        else:
            yield item, False


def iter_options(template: dict[str, Any]):
    """Yield ``(option unique-id, 'oneOf'|'anyOf', prompt, [choice descriptions])`` for each ``options`` relationship in the template."""
    for item in template["properties"]["relationships"]["prefixItems"]:
        props = item.get("properties") or {}
        opts = ((props.get("relationship-type") or {}).get("properties") or {}).get("options")
        if opts:
            entry = opts["prefixItems"][0]
            kind = "oneOf" if "oneOf" in entry else "anyOf"
            yield props["unique-id"]["const"], kind, props["description"]["const"], \
                [d["properties"]["description"]["const"] for d in entry[kind]]


def _placeholder(prop: str, schema: dict[str, Any]) -> Any:
    """Value ``calm generate`` is expected to emit for a free property of this schema: OMITTED for enums, ``[[ ... ]]`` markers for strings/booleans, -1 for numbers."""
    t = schema.get("type")
    if "enum" in schema:
        return OMITTED
    if t == "boolean":
        return f"[[ BOOLEAN_{prop.upper()} ]]"
    if t in ("number", "integer"):
        return -1
    return f"[[ {prop.upper()} ]]"


def free_fields(template: dict[str, Any]) -> list[dict[str, Any]]:
    """List the attribute definitions for every non-``const`` metadata property of every node the template can emit, sorted by property name per node."""
    out = []
    for d, optional in iter_node_defs(template):
        nid = d["properties"]["unique-id"]["const"]
        meta = (d["properties"].get("metadata") or {})
        for prop, schema in sorted((meta.get("properties") or {}).items()):
            if "const" in schema:
                continue
            a: dict[str, Any] = {"name": attr_name(nid, prop), "required": prop in (meta.get("required") or []),
                                 "target": {"node": nid, "field": prop}, "placeholder": _placeholder(prop, schema)}
            if "enum" in schema:
                a.update(type="enum", allowed=list(schema["enum"]))
            else:
                a["type"] = schema.get("type", "string")
            if "minimum" in schema:
                a["min"] = schema["minimum"]
            if optional:
                a["only_if_node_present"] = True
            out.append(a)
    return out


def form_for(template: dict[str, Any], template_text: str, status: str) -> dict[str, Any]:
    """YAML-ready form for a PUBLISHED template. Refuses DRAFT (Req 9.2)."""
    if status != "PUBLISHED":
        raise TemplateNotPublished(f"template status is {status}; only PUBLISHED templates can be instantiated")
    md = template["metadata"]
    return {
        "template": {"id": md["ra-id"], "version": md["ra-version"], "status": status, "sha256": sha256_hex(template_text)},
        "app": {"id": "", "name": ""},
        "attributes": free_fields(template),
        "options": [{"unique_id": oid, "type": kind, "prompt": prompt,
                     "choices": {_slug(c): c for c in choices}, "selected": None}
                    for oid, kind, prompt, choices in iter_options(template)],
        "values": {},
    }


def _type_ok(value: Any, a: dict[str, Any]) -> Optional[str]:
    """Return an error message if ``value`` violates the attribute's type, enum or minimum; None when it is acceptable."""
    t = a["type"]
    if t == "enum":
        return None if value in a["allowed"] else f"{value!r} is not one of {a['allowed']}"
    if t == "boolean":
        return None if isinstance(value, bool) else "must be a boolean"
    if t in ("number", "integer"):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or (t == "integer" and not isinstance(value, int)):
            return f"must be a {t}"
        if "min" in a and value < a["min"]:
            return f"must be >= {a['min']}"
        return None
    if t == "string":
        return None if isinstance(value, str) and value.strip() and not value.startswith("[[") else "must be a non-empty string"
    return None


def validate(form: dict[str, Any], template: dict[str, Any], template_text: str) -> list[FieldError]:
    """Check a filled form against the template and return all problems (empty list when valid).

    Covers template identity/revision, ``app.id`` format, unknown/missing/mistyped attribute values,
    placeholder coverage and option selections. Never calls the Decider or the CALM CLI.
    """
    errors: list[FieldError] = []
    md = template["metadata"]
    t = form.get("template") or {}
    if t.get("id") != md["ra-id"] or t.get("version") != md["ra-version"]:
        errors.append(FieldError("template", f"form is for {t.get('id')} v{t.get('version')}, not {md['ra-id']} v{md['ra-version']}"))
    if t.get("sha256") and t["sha256"] != sha256_hex(template_text):
        errors.append(FieldError("template.sha256", "form was generated for a different template revision"))
    app = form.get("app") or {}
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", str(app.get("id") or "")):
        errors.append(FieldError("app.id", "required: lowercase letters, digits and dashes"))

    attrs = {a["name"]: a for a in form.get("attributes") or []}
    values = form.get("values") or {}
    for name in sorted(set(values) - set(attrs)):
        errors.append(FieldError(name, "unknown attribute"))
    for name, a in attrs.items():
        if name not in values or values[name] is None:
            if a.get("required"):
                errors.append(FieldError(name, "required"))
            continue
        why = _type_ok(values[name], a)
        if why:
            errors.append(FieldError(name, why))

    expected = {(f["target"]["node"], f["target"]["field"]) for f in free_fields(template)}
    covered = {(a["target"]["node"], a["target"]["field"]) for a in attrs.values() if "target" in a}
    for node, fld in sorted(expected - covered):
        errors.append(FieldError(attr_name(node, fld), f"placeholder for {node}.metadata.{fld} is not covered by any attribute"))

    tpl_opts = {oid: (kind, choices) for oid, kind, _, choices in iter_options(template)}
    form_opts = {o["unique_id"]: o for o in form.get("options") or []}
    for oid, (kind, choices) in sorted(tpl_opts.items()):
        o = form_opts.get(oid)
        sel = (o or {}).get("selected")
        if o is None or sel in (None, "", []):
            errors.append(FieldError(oid, "a choice is required"))
            continue
        sels = sel if isinstance(sel, list) else [sel]
        if kind == "oneOf" and len(sels) != 1:
            errors.append(FieldError(oid, "oneOf option takes exactly one choice"))
        for s in sels:
            if s not in (o.get("choices") or {}) or o["choices"][s] not in choices:
                errors.append(FieldError(oid, f"{s!r} is not a choice of this option"))
    for oid in sorted(set(form_opts) - set(tpl_opts)):
        errors.append(FieldError(oid, "unknown option"))
    return errors


def option_choices(form: dict[str, Any]) -> dict[str, Any]:
    """Option unique-id -> choice description (list for anyOf), as ``calm generate --option-choices`` expects."""
    out: dict[str, Any] = {}
    for o in sorted(form.get("options") or [], key=lambda o: o["unique_id"]):
        sel = o["selected"]
        out[o["unique_id"]] = [o["choices"][s] for s in sel] if isinstance(sel, list) else (
            [o["choices"][sel]] if o["type"] == "anyOf" else o["choices"][sel])
    return out


def attributes_hash(form: dict[str, Any]) -> str:
    """Canonical hash of the user-supplied inputs (app, values, selected options); used as part of the instantiation inputs hash."""
    return canonical_hash({"app": form.get("app"), "values": form.get("values") or {},
                           "options": {o["unique_id"]: o.get("selected") for o in form.get("options") or []}})


# ---- option -> attribute consistency (templates/<ra>.consistency.yaml) -------------------------------------
def load_consistency(ra_id: str, directory: Optional[Any] = None) -> list[dict[str, Any]]:
    """Rules {option, choice, requires: {ATTRIBUTE: value}} for a template; empty when the RA has no rules file."""
    import yaml
    from pathlib import Path

    from .pattern_library import FRAMEWORK_ROOT
    f = Path(directory or FRAMEWORK_ROOT / "templates") / f"{ra_id}.consistency.yaml"
    if not f.is_file():
        return []
    return list((yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("rules") or [])


def _chosen(form: dict[str, Any]) -> dict[str, set]:
    out = {}
    for o in form.get("options") or []:
        sel = o.get("selected")
        out[o["unique_id"]] = set(sel if isinstance(sel, list) else ([sel] if sel else []))
    return out


def implied_values(form: dict[str, Any], rules: list[dict[str, Any]]) -> dict[str, Any]:
    """Attribute values implied by the chosen options (only for attributes not set yet)."""
    chosen, values, out = _chosen(form), form.get("values") or {}, {}
    for r in rules:
        if r["choice"] in chosen.get(r["option"], set()):
            out.update({k: v for k, v in (r.get("requires") or {}).items() if values.get(k) in (None, "")})
    return out


def consistency_errors(form: dict[str, Any], rules: list[dict[str, Any]]) -> list[FieldError]:
    """Attributes that contradict the chosen option (same design decision recorded twice)."""
    chosen, values, errs = _chosen(form), form.get("values") or {}, []
    for r in rules:
        if r["choice"] not in chosen.get(r["option"], set()):
            continue
        for k, v in (r.get("requires") or {}).items():
            if values.get(k) not in (None, "") and values[k] != v:
                errs.append(FieldError(k, f"{values[k]!r} contradicts option {r['option']} = {r['choice']} (requires {v!r})"))
    return errs
