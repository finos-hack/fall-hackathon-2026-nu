"""Extraction over ingested source items (task 21.2): AIGF risks/mitigations, CCC controls/threats.

Takes the ingest artifact (``catalogs/sources/<source>.json``) plus the checkout, calls extraction
through the ModelGateway and writes each DRAFT, with its Extraction_Record fields, to
``catalogs/drafts/<id>.json``. Items that fail are reported, never dropped:

* ``drafted``       DRAFT with a candidate rule.
* ``inexpressible`` DRAFT without a rule (stored, with the reason).
* ``errors``        schema-invalid model output or model unavailable (nothing stored).
* ``missing``       replay found no recording for the input hash (nothing stored).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

import yaml

from agip_shared import versioned_write as vw
from agip_shared.gateway import ModelGateway
from agip_shared.gateway.model_gateway import ModelUnavailableError, RecordingMissingError

from . import extraction as ex
from . import versioning
from .paths import FRAMEWORK_ROOT

DRAFTS_DIR = FRAMEWORK_ROOT / "catalogs" / "drafts"
CATALOG_DIR = FRAMEWORK_ROOT / "catalogs"
TAXONOMY = FRAMEWORK_ROOT.parent / "governance-execution-framework" / "config" / "taxonomy.yaml"
CCC_KINDS = ("control", "threat")
AIGF_KINDS = ("risk", "mitigation")


def load_dimensions(path: Path = TAXONOMY) -> Optional[list[str]]:
    """Scoring dimension names, read as data (no governance_execution import). None if unavailable."""
    try:
        dims = yaml.safe_load(path.read_text(encoding="utf-8")).get("dimensions")
    except (OSError, yaml.YAMLError, AttributeError):
        return None
    return [str(d) for d in dims] if isinstance(dims, list) and dims else None


def _ids(blocks: Any) -> list[str]:
    """Reference ids found in a list of reference blocks."""
    return [e["reference-id"] for b in blocks or [] if isinstance(b, dict)
            for e in b.get("entries") or [] if isinstance(e, dict) and "reference-id" in e]


def _yaml_list(path: Path, key: str) -> list[dict[str, Any]]:
    """Dict entries under `key` in a YAML file."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [e for e in doc.get(key, []) if isinstance(e, dict)]


def ccc_detail(root: Path, item: dict[str, Any]) -> dict[str, Any]:
    """Structured CCC input (objective, assessment requirements, threat mappings) from the checkout."""
    src = root / item["path"]
    key = "controls" if item["kind"] == "control" else "threats"
    entry = next(e for e in _yaml_list(src, key) if e.get("id") == item["id"])
    if item["kind"] == "threat":
        return {"objective": " ".join(str(entry.get("description", "")).split()),
                "assessment_requirements": [], "threat_mappings": []}
    titles: dict[str, str] = {}
    tpath = src.with_name("threats.yaml")
    if tpath.is_file():
        titles = {e["id"]: e.get("title", "") for e in _yaml_list(tpath, "threats") if "id" in e}
    return {
        "objective": " ".join(str(entry.get("objective", "")).split()),
        "assessment_requirements": [{"id": a["id"], "text": " ".join(str(a.get("text", "")).split())}
                                    for a in entry.get("assessment-requirements") or [] if "id" in a],
        "threat_mappings": [{"id": t, "title": titles.get(t, "")} for t in sorted(set(_ids(entry.get("threats"))))],
    }


@dataclass
class Summary:
    """Outcome counts and lists for an extraction run; lines() renders them for the CLI."""
    drafted: list[str] = field(default_factory=list)
    inexpressible: list[tuple[str, str]] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)    # same content as the catalog entry or the stored draft
    versions: dict[str, int] = field(default_factory=dict)
    skipped: int = 0

    def lines(self) -> list[str]:
        """Report lines; missing recordings are capped at 10 entries."""
        out = [f"extraction: drafted={len(self.drafted)} inexpressible={len(self.inexpressible)} "
               f"errors={len(self.errors)} missing-recording={len(self.missing)} unchanged={len(self.unchanged)} "
               f"skipped={self.skipped}"]
        out += [f"  DRAFT {i} v{self.versions[i]}" for i in self.drafted + [k for k, _ in self.inexpressible]
                if i in self.versions]
        out += [f"  UNCHANGED {i}" for i in self.unchanged]
        out += [f"  INEXPRESSIBLE {i}: {r}" for i, r in self.inexpressible]
        out += [f"  ERROR {i}: {r}" for i, r in self.errors]
        out += [f"  MISSING-RECORDING {i}" for i in self.missing[:10]]
        if len(self.missing) > 10:
            out.append(f"  ... {len(self.missing) - 10} more without recording")
        return out


def write_draft(item: dict[str, Any], drafts_dir: Path, catalog_dir: Path = CATALOG_DIR) -> Optional[Path]:
    """Write a DRAFT under the hash rule. Returns None (nothing written) when its content equals the catalog entry.

    Version: unchanged content keeps the stored version; changed content is +1. A new draft for an item already
    in the catalog starts at the catalog version + 1."""
    entry = ex.to_catalog_entry(item)
    existing = versioning.find_entry(item["id"], catalog_dir)
    if existing is not None and versioning.content_hash(existing) == versioning.content_hash(entry):
        return None
    path = drafts_dir / f"{item['id']}.json"
    ch = vw.hash_content({k: v for k, v in item.items() if k != "version"})
    initial = int(existing.get("version", 1)) + 1 if existing is not None else 1
    item["version"] = str(vw.version_for(path, ch, initial=initial))
    text = json.dumps(item, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    vw.write(path, text, content_hash=ch, version=int(item["version"]),
             inputs_hash=(item["body"].get("extraction_record") or {}).get("input_hash"))
    return path


def extract_items(doc: dict[str, Any], root: Path, gateway: ModelGateway, *, drafts_dir: Path = DRAFTS_DIR,
                  dimensions: Optional[Sequence[str]] = None, ids: Optional[Sequence[str]] = None,
                  catalog_dir: Path = CATALOG_DIR, scorer: Any = None) -> Summary:
    """Run extraction over the items of an ingested source document through the gateway and store drafts, returning a Summary. Items outside the source's kinds or not in `ids` are counted as skipped."""
    s = Summary()
    source_version = doc.get("commit", "unknown")
    for it in doc["items"]:
        if it["kind"] not in (CCC_KINDS if doc["source"] == "ccc" else AIGF_KINDS) or (ids and it["id"] not in ids):
            s.skipped += 1
            continue
        key = ex.item_key(it["framework"], it["id"])
        try:
            if it["framework"] == "CCC":
                d = ccc_detail(root, it)
                res = ex.extract_ccc(gateway, native_id=it["id"], kind=it["kind"], title=it["title"],
                                     references=it.get("references") or {}, source_path=it["path"],
                                     dimensions=dimensions, source_version=source_version, **d)
            else:
                prose = ex.body_of_markdown((root / it["path"]).read_text(encoding="utf-8"))
                res = ex.extract(gateway, framework=it["framework"], native_id=it["id"], title=it["title"],
                                 prose=prose, source_path=it["path"], dimensions=dimensions,
                                 source_version=source_version, references=it.get("references") or {}, scorer=scorer)
        except RecordingMissingError:
            s.missing.append(key)
            continue
        except (ModelUnavailableError, OSError, StopIteration, KeyError, yaml.YAMLError) as exc:
            s.errors.append((key, f"{type(exc).__name__}: {str(exc)[:120]}"))
            continue
        if not res.ok or res.item is None:
            s.errors.append((key, res.reason or "rejected"))
            continue
        store_result(s, key, res, drafts_dir, catalog_dir)
    return s


def store_result(s: Summary, key: str, res: Any, drafts_dir: Path, catalog_dir: Path = CATALOG_DIR) -> None:
    """Record one ok extraction in the summary and write its DRAFT under the hash rule."""
    if write_draft(res.item, drafts_dir, catalog_dir) is None:
        s.unchanged.append(key)
        return
    s.versions[key] = int(res.item["version"])
    if res.inexpressible:
        s.inexpressible.append((key, res.item["body"]["extraction"].get("inexpressible_reason") or ""))
    else:
        s.drafted.append(key)


def extract_uploads(items: Sequence[Any], gateway: ModelGateway, *, drafts_dir: Path, catalog_dir: Path = CATALOG_DIR,
                    dimensions: Optional[Sequence[str]] = None, scorer: Any = None) -> Summary:
    """Extraction over uploaded documents (``upload.UploadItem``): same path and rules as ``extract_items``."""
    s = Summary()
    for it in items:
        key = it.key
        src_path, version = f"upload/{it.filename}", it.sha256[:12]
        try:
            if it.framework == "CCC":
                res = ex.extract_ccc(gateway, native_id=it.native_id, kind=it.kind, title=it.title, source_path=src_path,
                                     dimensions=dimensions, source_version=version, **(it.ccc or {}))
            else:
                res = ex.extract(gateway, framework=it.framework, native_id=it.native_id, title=it.title, prose=it.prose,
                                 source_path=src_path, dimensions=dimensions, source_version=version,
                                 references=it.references, scorer=scorer)
        except RecordingMissingError:
            s.missing.append(key)
            continue
        except (ModelUnavailableError, OSError, KeyError, ValueError) as exc:
            s.errors.append((key, f"{type(exc).__name__}: {str(exc)[:160]}"))
            continue
        if not res.ok or res.item is None:
            s.errors.append((key, res.reason or "rejected"))
            continue
        store_result(s, key, res, drafts_dir, catalog_dir)
    return s
