"""Source adapter for FINOS Common Cloud Controls (CCC) catalogs.

Contract: ``read(paths, control_ids=None) -> (items, errors)``.

``paths`` may be catalog directories (``catalogs/core/core``,
``catalogs/ai-ml/multi-agent-refarch``) or single ``controls.yaml`` /
``threats.yaml`` / ``capabilities.yaml`` files. For a directory, files in its
``mappings/`` folder (Gemara mapping documents) are read too.

``SourceItem`` has the same shape as the AIGF adapter (``framework, id, kind,
title, path, references, relations``) plus ``catalog`` and ``group``:

* ``references``: mappings kept from the source, ``{reference-set-id: [entry ids]}``
  (e.g. ``finos-air`` -> AIGF mitigation guidelines, ``air-vec``, ``CCM``,
  ``MITRE-ATT&CK``, and any NIST set if a catalog carries one).
* ``relations``: CCC-internal links, ``{threats|capabilities|controls: [ids]}``;
  forward links come from the source, reverse links (``controls`` on a threat,
  ``threats`` on a capability) are derived.

Malformed files/entries are skipped and reported as
``SourceError(path, field, message)``; unknown fields are ignored. Output is
sorted and has no timestamps.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

MVP_CATALOGS = ("core/core", "ai-ml/multi-agent-refarch")

_KINDS = (
    ("controls.yaml", "controls", "control"),
    ("threats.yaml", "threats", "threat"),
    ("capabilities.yaml", "capabilities", "capability"),
)
_FILE_TO_KIND = {fname: (key, kind) for fname, key, kind in _KINDS}
_KIND_ORDER = {kind: i for i, (_, _, kind) in enumerate(_KINDS)}
_LINK_KEYS = ("threats", "capabilities")  # internal links
_MAPPING_KEYS = ("guidelines", "vectors")  # external mappings


@dataclass(frozen=True)
class SourceError:
    """A problem found while reading a source file: path, field and message."""
    path: str
    field: str
    message: str


@dataclass(frozen=True)
class SourceItem:
    """One CCC control, threat or capability with its references and relations."""
    framework: str  # always "CCC"
    id: str  # native ID, e.g. "CCC.Core.CN01"
    kind: str  # control | threat | capability
    title: str
    path: str
    references: dict[str, list[str]] = field(default_factory=dict)
    relations: dict[str, list[str]] = field(default_factory=dict)
    catalog: str = ""  # e.g. "core/core"
    group: str | None = None

    @property
    def native_id(self) -> str:
        """Alias of id, the native CCC identifier."""
        return self.id


def _posix(p: Path) -> str:
    """POSIX form of a path, for stable output across platforms."""
    return p.as_posix()


def _catalog_name(p: Path) -> str:
    """Catalog name from the file location, '<parent dir>/<dir>'."""
    return f"{p.parent.parent.name}/{p.parent.name}"


def _blocks(entry: dict[str, Any], key: str) -> dict[str, list[str]] | None:
    """``[{reference-id, entries: [{reference-id}]}]`` -> ``{set: sorted ids}``; None if malformed."""
    raw = entry.get(key)
    if raw is None:
        return {}
    if not isinstance(raw, list):
        return None
    out: dict[str, set[str]] = {}
    for block in raw:
        if not isinstance(block, dict) or not isinstance(block.get("reference-id"), str):
            return None
        ids = out.setdefault(block["reference-id"], set())
        for sub in block.get("entries") or []:
            if not isinstance(sub, dict) or not isinstance(sub.get("reference-id"), str):
                return None
            ids.add(sub["reference-id"])
    return {k: sorted(v) for k, v in sorted(out.items())}


def _expand(paths: Iterable[str | Path]) -> list[Path]:
    """Catalog files to read: known file names inside directories, or the given file paths, sorted."""
    files: set[Path] = set()
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for fname, _, _ in _KINDS:
                if (p / fname).is_file():
                    files.add(p / fname)
        else:
            files.add(p)
    return sorted(files, key=_posix)


def _load(p: Path) -> tuple[Any, SourceError | None]:
    """Read and parse a YAML file. Returns (document, None) or (None, SourceError)."""
    path = _posix(p)
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, SourceError(path, "<file>", f"cannot read file: {exc}")
    try:
        return yaml.safe_load(text), None
    except yaml.YAMLError as exc:
        return None, SourceError(path, "<document>", f"invalid YAML: {str(exc).splitlines()[0]}")


def _read_file(p: Path, control_ids: set[str] | None) -> tuple[list[SourceItem], list[SourceError]]:
    """Parse one catalog file into SourceItems and errors, optionally limited to control_ids."""
    path = _posix(p)
    spec = _FILE_TO_KIND.get(p.name)
    if spec is None:
        return [], [SourceError(path, "<file>", "unsupported file name (expected controls/threats/capabilities.yaml)")]
    key, kind = spec
    doc, err = _load(p)
    if err:
        return [], [err]
    if not isinstance(doc, dict) or not isinstance(doc.get(key), list):
        return [], [SourceError(path, key, f"expected top-level list '{key}'")]

    items: list[SourceItem] = []
    errors: list[SourceError] = []
    seen: set[str] = set()
    catalog = _catalog_name(p)
    for i, entry in enumerate(doc[key]):
        loc = f"{key}[{i}]"
        if not isinstance(entry, dict):
            errors.append(SourceError(path, loc, "entry is not a mapping"))
            continue
        bad = False
        for fld in ("id", "title"):
            v = entry.get(fld)
            if not isinstance(v, str) or not v.strip():
                errors.append(SourceError(path, f"{loc}.{fld}", f"missing or empty '{fld}'"))
                bad = True
        relations: dict[str, list[str]] = {}
        references: dict[str, list[str]] = {}
        for k in (*_LINK_KEYS, *_MAPPING_KEYS):
            if k not in entry:
                continue
            blocks = _blocks(entry, k)
            if blocks is None:
                errors.append(SourceError(path, f"{loc}.{k}", "expected list of {reference-id, entries[{reference-id}]}"))
                bad = True
            elif k in _LINK_KEYS:
                relations[k] = sorted({x for v in blocks.values() for x in v})
            else:
                for setid, ids in blocks.items():
                    references.setdefault(setid, [])
                    references[setid] = sorted(set(references[setid]) | set(ids))
        if bad:
            continue
        nid = entry["id"].strip()
        if nid in seen:
            errors.append(SourceError(path, f"{loc}.id", f"duplicate id '{nid}'"))
            continue
        seen.add(nid)
        if kind == "control" and control_ids is not None and nid not in control_ids:
            continue
        group = entry.get("group")
        items.append(
            SourceItem("CCC", nid, kind, entry["title"].strip(), path,
                       dict(sorted(references.items())), dict(sorted(relations.items())),
                       catalog, group if isinstance(group, str) else None)
        )
    return items, errors


def _read_mapping_doc(p: Path) -> tuple[dict[str, dict[str, list[str]]], list[SourceError]]:
    """Gemara mapping document -> ``{source entry id: {target set id: [entry ids]}}``."""
    path = _posix(p)
    doc, err = _load(p)
    if err:
        return {}, [err]
    if not isinstance(doc, dict) or not isinstance(doc.get("mappings"), list):
        return {}, [SourceError(path, "mappings", "expected top-level list 'mappings'")]
    target = (doc.get("target-reference") or {}).get("reference-id") if isinstance(doc.get("target-reference"), dict) else None
    if not isinstance(target, str) or not target:
        return {}, [SourceError(path, "target-reference.reference-id", "missing target reference id")]
    out: dict[str, dict[str, set[str]]] = {}
    errors: list[SourceError] = []
    for i, m in enumerate(doc["mappings"]):
        loc = f"mappings[{i}]"
        if not isinstance(m, dict) or not isinstance(m.get("source"), str):
            errors.append(SourceError(path, f"{loc}.source", "missing or not a string"))
            continue
        targets = m.get("targets")
        if not isinstance(targets, list) or not all(isinstance(t, dict) and isinstance(t.get("entry-id"), (str, int)) for t in targets):
            errors.append(SourceError(path, f"{loc}.targets", "expected list of {entry-id}"))
            continue
        out.setdefault(m["source"], {}).setdefault(target, set()).update(str(t["entry-id"]) for t in targets)
    return {s: {k: sorted(v) for k, v in d.items()} for s, d in out.items()}, errors


def _link(items: list[SourceItem]) -> list[SourceItem]:
    """Add derived reverse links: controls on threats, threats on capabilities."""
    rev: dict[tuple[str, str], set[str]] = {}
    for it in items:
        if it.kind == "control":
            for t in it.relations.get("threats", []):
                rev.setdefault(("controls", t), set()).add(it.id)
        elif it.kind == "threat":
            for c in it.relations.get("capabilities", []):
                rev.setdefault(("threats", c), set()).add(it.id)
    out = []
    for it in items:
        key = {"threat": "controls", "capability": "threats"}.get(it.kind)
        extra = rev.get((key, it.id)) if key else None
        if extra:
            it = dataclasses.replace(it, relations=dict(sorted({**it.relations, key: sorted(extra)}.items())))
        out.append(it)
    return out


def read(
    paths: Iterable[str | Path],
    control_ids: Iterable[str] | None = None,
) -> tuple[list[SourceItem], list[SourceError]]:
    """Read CCC catalogs. Returns (items, errors); never raises on bad input."""
    wanted = set(control_ids) if control_ids is not None else None
    items: list[SourceItem] = []
    errors: list[SourceError] = []
    for p in _expand(paths):
        i, e = _read_file(p, wanted)
        items.extend(i)
        errors.extend(e)

    # Mapping documents (directory inputs only), merged into references by source id.
    maps: dict[tuple[str, str], dict[str, list[str]]] = {}
    for raw in paths:
        d = Path(raw)
        if d.is_dir() and (d / "mappings").is_dir():
            cat = f"{d.parent.name}/{d.name}"
            for mp in sorted((d / "mappings").glob("*.yaml"), key=_posix):
                m, e = _read_mapping_doc(mp)
                errors.extend(e)
                for src, tgt in m.items():
                    cur = maps.setdefault((cat, src), {})
                    for k, v in tgt.items():
                        cur[k] = sorted(set(cur.get(k, [])) | set(v))
    if maps:
        merged = []
        for it in items:
            extra = maps.get((it.catalog, it.id))
            if extra:
                refs = {k: sorted(set(it.references.get(k, [])) | set(extra.get(k, []))) for k in {*it.references, *extra}}
                it = dataclasses.replace(it, references=dict(sorted(refs.items())))
            merged.append(it)
        items = merged

    items = _link(items)
    items.sort(key=lambda x: (x.catalog, _KIND_ORDER[x.kind], x.id, x.path))
    errors.sort(key=lambda x: (x.path, x.field, x.message))
    return items, errors