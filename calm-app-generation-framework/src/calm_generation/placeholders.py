"""Placeholder_Fill: replace ``calm generate`` placeholders with validated attribute values (Req 10.2, 10.3).

Pure. ``calm generate`` 1.60.1 writes ``[[ NAME ]]`` for strings, ``[[ BOOLEAN_X ]]`` for booleans and
``-1`` for numbers, and omits ``enum`` properties; omitted properties are added from the attributes.
After filling, any remaining placeholder, or any required metadata property still missing, is a
leftover reported with its JSON path, and no App_Model is returned.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .attributes import OMITTED, iter_node_defs

CALM_SCHEMA = "https://calm.finos.org/release/1.2/meta/calm.json"
_PH = re.compile(r"^\[\[ .+ \]\]$")


@dataclass(frozen=True)
class Leftover:
    """A placeholder or missing required property that remained after filling, with its JSON path."""
    json_path: str
    placeholder: str

    def __str__(self) -> str:
        """Render as ``path: placeholder``."""
        return f"{self.json_path}: {self.placeholder}"


@dataclass
class FillResult:
    """Outcome of :func:`fill`. ``model`` is None when ``leftovers`` is non-empty; ``fill_record`` lists each substitution made."""
    model: Optional[dict[str, Any]]
    fill_record: list[dict[str, Any]] = field(default_factory=list)
    leftovers: list[Leftover] = field(default_factory=list)


def is_placeholder(v: Any) -> bool:
    """True for ``[[ ... ]]`` strings and the numeric placeholder -1 (booleans are never placeholders)."""
    return (isinstance(v, str) and bool(_PH.match(v))) or (isinstance(v, (int, float)) and not isinstance(v, bool) and v == -1)


def _scan(obj: Any, path: str, out: list[Leftover]) -> None:
    """Recursively append a Leftover for every placeholder under ``obj``; keys that are not identifiers use bracket notation in the path."""
    if isinstance(obj, dict):
        for k in sorted(obj):
            _scan(obj[k], f"{path}.{k}" if re.fullmatch(r"[A-Za-z_][\w]*", k) else f"{path}['{k}']", out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _scan(v, f"{path}[{i}]", out)
    elif is_placeholder(obj):
        out.append(Leftover(path, str(obj)))


def fill(generated: dict[str, Any], form: dict[str, Any], template: dict[str, Any]) -> FillResult:
    """Substitute form values into the generated architecture and report leftovers.

    Pure: the input is deep-copied. Attributes whose node is absent (optional components) are skipped.
    """
    model = copy.deepcopy(generated)
    values = form.get("values") or {}
    index = {n.get("unique-id"): i for i, n in enumerate(model.get("nodes") or [])}
    record: list[dict[str, Any]] = []
    for a in sorted(form.get("attributes") or [], key=lambda a: a["name"]):
        name, tgt = a["name"], a.get("target") or {}
        # Skip unanswered attributes and optional nodes that calm generate did not emit.
        if name not in values or tgt.get("node") not in index:
            continue
        i = index[tgt["node"]]
        meta = model["nodes"][i].setdefault("metadata", {})
        before = meta.get(tgt["field"], OMITTED)
        meta[tgt["field"]] = values[name]
        record.append({"json_path": f"$.nodes[{i}].metadata.{tgt['field']}", "placeholder": before, "attribute": name})
    model["$schema"] = CALM_SCHEMA

    leftovers: list[Leftover] = []
    _scan(model, "$", leftovers)
    required = {d["properties"]["unique-id"]["const"]: (d["properties"].get("metadata") or {}).get("required") or []
                for d, _ in iter_node_defs(template)}
    for nid, i in sorted(index.items(), key=lambda kv: kv[1]):
        meta = model["nodes"][i].get("metadata") or {}
        for prop in required.get(nid, []):
            if prop not in meta:
                leftovers.append(Leftover(f"$.nodes[{i}].metadata.{prop}", OMITTED))
    if leftovers:
        return FillResult(None, record, leftovers)
    return FillResult(model, record, [])
