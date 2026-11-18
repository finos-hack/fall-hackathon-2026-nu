"""Uploaded control documents -> source items for extraction ("Generate Rules").

Supported input (``SUPPORTED``), at most ``MAX_BYTES`` per file, UTF-8:

* ``.md`` / ``.markdown``
  - AIGF file (name ``ri-<n>*.md`` / ``mi-<n>*.md``): read like the AIGF checkout; keeps the AIGF ID (``AIGF-RI-001``).
  - any other Markdown: optional YAML front matter (``title``, ``type: risk|mitigation|control``, ``id``,
    ``<framework>_references: [...]``); without front matter the first ``# heading`` is the title and the whole
    text is the prose. ID: ``UPL-<slug>`` from ``id``, else the title.
* ``.yaml`` / ``.yml``: CCC catalog fragment with ``controls:`` and/or ``threats:`` (CCC IDs kept).

Every item records the file name and its SHA-256, so an unchanged document is recognised (hash rule).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

import yaml

from agip_shared.hashing import sha256_hex

from .extraction import body_of_markdown
from .sources_aigf import _NAME_RE as AIGF_NAME, _frontmatter, _id_list

SUPPORTED = (".md", ".markdown", ".yaml", ".yml")
MAX_BYTES = 1_000_000
MAX_ITEMS = 20


@dataclass
class UploadItem:
    framework: str                      # AIGF | UPL | CCC
    native_id: str
    kind: str                           # risk | mitigation | control | threat
    title: str
    filename: str
    sha256: str
    prose: str = ""                     # Markdown items
    ccc: Optional[dict[str, Any]] = None  # CCC items: objective, assessment_requirements, threat_mappings
    references: dict[str, list[str]] = field(default_factory=dict)

    @property
    def key(self) -> str:
        from .extraction import item_key
        return item_key(self.framework, self.native_id)


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)[:48].strip("-")
    return s if "-" in s or not s else f"{s}-doc"   # rule codes need at least one dash


def _refs(meta: dict[str, Any]) -> dict[str, list[str]]:
    out = {}
    for k in sorted(meta):
        if k.endswith("_references"):
            vals = _id_list(meta[k])
            if vals:
                out[k] = vals
    return out


def _markdown(name: str, text: str, sha: str) -> tuple[list[UploadItem], list[str]]:
    meta, err = _frontmatter(text)
    m = AIGF_NAME.match(name)
    if m:
        if meta is None:
            return [], [f"{name}: AIGF file name but {err or 'no front matter'}"]
        nid = m.group("id")
        kind = "risk" if nid.startswith("ri-") else "mitigation"
        title = str(meta.get("title") or nid).strip()
        return [UploadItem("AIGF", nid, kind, title, name, sha, body_of_markdown(text), references=_refs(meta))], []
    meta = meta or {}
    body = body_of_markdown(text) if meta else text
    heading = next((l.lstrip("# ").strip() for l in body.splitlines() if l.startswith("# ")), "")
    title = str(meta.get("title") or heading or re.sub(r"\.[a-z]+$", "", name)).strip()
    if not body.strip():
        return [], [f"{name}: no text to extract rules from"]
    nid = slug(meta.get("id") or title)
    if not nid:
        return [], [f"{name}: cannot derive an id; add 'id:' or a title"]
    kind = str(meta.get("type") or meta.get("kind") or "document").lower()   # "document": the model decides control/risk
    kind = kind if kind in ("risk", "mitigation", "control") else "document"
    return [UploadItem("UPL", nid, kind, title, name, sha, body, references=_refs(meta))], []


def _ccc(name: str, text: str, sha: str) -> tuple[list[UploadItem], list[str]]:
    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        return [], [f"{name}: invalid YAML ({str(exc).splitlines()[0]})"]
    if not isinstance(doc, dict) or not (doc.get("controls") or doc.get("threats")):
        return [], [f"{name}: expected a CCC catalog with 'controls:' or 'threats:'"]
    flat = lambda s: " ".join(str(s or "").split())  # noqa: E731
    titles = {t["id"]: t.get("title", "") for t in doc.get("threats") or [] if isinstance(t, dict) and "id" in t}
    items, errs = [], []
    for key, kind in (("controls", "control"), ("threats", "threat")):
        for e in doc.get(key) or []:
            if not isinstance(e, dict) or not e.get("id") or not e.get("title"):
                errs.append(f"{name}: a {kind} entry needs 'id' and 'title'")
                continue
            if kind == "threat":
                detail = {"objective": flat(e.get("description")), "assessment_requirements": [], "threat_mappings": []}
            else:
                threats = sorted({x["reference-id"] for b in e.get("threats") or [] if isinstance(b, dict)
                                  for x in b.get("entries") or [] if isinstance(x, dict) and "reference-id" in x})
                detail = {"objective": flat(e.get("objective")),
                          "assessment_requirements": [{"id": a["id"], "text": flat(a.get("text"))}
                                                      for a in e.get("assessment-requirements") or [] if isinstance(a, dict) and "id" in a],
                          "threat_mappings": [{"id": t, "title": titles.get(t, "")} for t in threats]}
            items.append(UploadItem("CCC", str(e["id"]), kind, str(e["title"]).strip(), name, sha, ccc=detail))
    return items, errs


def parse_upload(name: str, data: bytes) -> tuple[list[UploadItem], list[str]]:
    """Source items in one uploaded file, plus problems (never raises for bad input)."""
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1])[:120] or "upload"
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if ext not in SUPPORTED:
        return [], [f"{name}: unsupported file type; use {', '.join(SUPPORTED)}"]
    if len(data) > MAX_BYTES:
        return [], [f"{name}: larger than {MAX_BYTES // 1000} KB"]
    try:
        text = data.decode("utf-8").lstrip("\ufeff")
    except UnicodeDecodeError:
        return [], [f"{name}: not UTF-8 text"]
    sha = sha256_hex(data)
    return _markdown(name, text, sha) if ext in (".md", ".markdown") else _ccc(name, text, sha)
