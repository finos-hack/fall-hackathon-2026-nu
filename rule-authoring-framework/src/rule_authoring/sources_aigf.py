"""AIGF Source_Adapter: reads ``ri-*.md`` / ``mi-*.md`` frontmatter.

Contract: ``read(paths) -> (items, errors)``. Deterministic: inputs are
expanded, de-duplicated and sorted; output is sorted by native ID.
Malformed files are skipped and reported with path and field.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

_NAME_RE = re.compile(r"^(?P<id>(?:ri|mi)-\d+)(?:_.*)?\.md$")
_REL_KEYS = ("mitigates", "related_mitigations", "related_risks", "mitigated_by")


@dataclass(frozen=True)
class SourceItem:
    """One AIGF risk or mitigation read from a markdown file, with its external references and cross-links."""
    framework: str
    id: str  # native ID, e.g. "mi-24"
    kind: str  # "risk" | "mitigation"
    title: str
    path: str
    references: dict[str, list[str]] = field(default_factory=dict)  # external framework refs
    relations: dict[str, list[str]] = field(default_factory=dict)  # AIGF cross-links


@dataclass(frozen=True)
class SourceError:
    """A problem found while reading a source file: path, field and message."""
    path: str
    field: str
    message: str


def _expand(paths: Iterable[str | Path]) -> list[Path]:
    """Files to read: markdown files named like ri-/mi- entries under directories, or the given file paths, sorted."""
    found: set[Path] = set()
    for p in paths:
        p = Path(p)
        if p.is_dir():
            found.update(f for f in p.rglob("*.md") if _NAME_RE.match(f.name))
        else:
            found.add(p)
    return sorted(found, key=lambda x: x.as_posix())


def _frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    """Split YAML frontmatter from a markdown text. Returns (data, body) or (None, error text)."""
    text = text.lstrip("\ufeff")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, "frontmatter"
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            try:
                data = yaml.safe_load("\n".join(lines[1:i]))
            except yaml.YAMLError as exc:
                return None, f"frontmatter: invalid YAML ({str(exc).splitlines()[0]})"
            if not isinstance(data, dict):
                return None, "frontmatter: not a mapping"
            return data, ""
    return None, "frontmatter: missing closing '---'"


def _id_list(value: Any) -> list[str] | None:
    """Sorted, de-duplicated string ids from a list value; [] for None, None if the value is malformed."""
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, (str, int)) for v in value):
        return None
    return sorted({str(v) for v in value})


def _parse(path: Path) -> tuple[SourceItem | None, list[SourceError]]:
    """Parse one file into a SourceItem, or return the list of SourceErrors explaining why not."""
    sp = path.as_posix()
    m = _NAME_RE.match(path.name)
    if not m:
        return None, [SourceError(sp, "filename", "expected ri-<n>*.md or mi-<n>*.md")]
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, [SourceError(sp, "file", f"unreadable: {exc}")]

    data, ferr = _frontmatter(text)
    if data is None:
        field_name, _, msg = ferr.partition(": ")
        return None, [SourceError(sp, field_name, msg or "missing or malformed frontmatter")]

    errors: list[SourceError] = []
    native_id = m.group("id")

    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append(SourceError(sp, "title", "missing or not a non-empty string"))

    seq = data.get("sequence")
    expected = int(native_id.split("-")[1])
    if seq is not None and seq != expected:
        errors.append(SourceError(sp, "sequence", f"{seq!r} does not match filename ID {native_id}"))

    references: dict[str, list[str]] = {}
    relations: dict[str, list[str]] = {}
    for key in sorted(data):
        if key.endswith("_references") or key in _REL_KEYS:
            vals = _id_list(data[key])
            if vals is None:
                errors.append(SourceError(sp, key, "must be a list of identifiers"))
            elif key in _REL_KEYS:
                relations[key] = vals
            else:
                references[key] = vals

    if errors:
        return None, errors
    kind = "risk" if native_id.startswith("ri-") else "mitigation"
    return SourceItem("AIGF", native_id, kind, title.strip(), sp, references, relations), []


def read(paths: Iterable[str | Path]) -> tuple[list[SourceItem], list[SourceError]]:
    """Read all AIGF items under the given paths. Returns items sorted by kind, number and path, plus any errors."""
    items: list[SourceItem] = []
    errors: list[SourceError] = []
    for path in _expand(paths):
        item, errs = _parse(path)
        if item:
            items.append(item)
        errors.extend(errs)
    items.sort(key=lambda i: (i.kind, int(i.id.split("-")[1]), i.path))
    return items, errors
