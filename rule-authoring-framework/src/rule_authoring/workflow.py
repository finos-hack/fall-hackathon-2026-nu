"""Rule Authoring lifecycle as discrete workflow steps (Knowledge Lifecycle in Fluxnova).

Each step works inside a run workspace (a copy of ``catalogs/`` and ``rulesets/``), so an orchestrated run never
changes the repository catalogs. Steps return small JSON-safe summaries; artifacts stay on disk in the workspace.
Order: ingest_sources -> extract_rules -> check_consistency -> (human review) -> record_review -> compile_rulesets.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from agip_shared.hashing import sha256_hex

from . import compile as compile_mod
from . import consistency
from . import extract_sources as es
from .ingest import _default_path, ingest, write_source_artifact
from .paths import FRAMEWORK_ROOT

CATALOG_DIR = FRAMEWORK_ROOT / "catalogs"
RULESET_DIR = FRAMEWORK_ROOT / "rulesets"
SOURCES = ("aigf", "ccc")


class Workspace:
    """Directory layout of a rule-authoring run: catalogs, sources, drafts and rulesets under one root."""
    def __init__(self, root: Path):
        """Derive the standard sub-paths from root."""
        self.root = Path(root)
        self.catalogs = self.root / "catalogs"
        self.sources = self.catalogs / "sources"
        self.drafts = self.catalogs / "drafts"
        self.rulesets = self.root / "rulesets"


def init_workspace(root: Path) -> Workspace:
    """Create the workspace, seeding catalogs (without drafts) and rulesets from the repo copies if not already present."""
    ws = Workspace(root)
    ws.root.mkdir(parents=True, exist_ok=True)
    if not ws.catalogs.exists():
        shutil.copytree(CATALOG_DIR, ws.catalogs, ignore=shutil.ignore_patterns("drafts"))
    if not ws.rulesets.exists():
        shutil.copytree(RULESET_DIR, ws.rulesets)
    return ws


def ingest_sources(ws: Workspace, sources: Sequence[str] = SOURCES) -> dict[str, Any]:
    """Ingest each source checkout into the workspace; raises FileNotFoundError for a missing checkout and ValueError if ingestion reported errors."""
    out: dict[str, Any] = {}
    for src in sources:
        root = Path(_default_path(src)).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"{src} checkout not found: {root}")
        doc = ingest(src, root, None)
        w = write_source_artifact(doc, ws.sources / f"{src}.json")
        if doc["errors"]:
            raise ValueError(f"{src}: {len(doc['errors'])} ingest error(s), first: {doc['errors'][0]}")
        out[src] = {"items": len(doc["items"]), "commit": doc.get("commit"), "version": w.version, "write": w.action}
    return out


def extract_rules(ws: Workspace, gateway: Any, ids: Optional[dict[str, list[str]]] = None, strict: bool = False,
                  scorer: Any = None) -> dict[str, Any]:
    """DRAFT rules via the ModelGateway (Strands + Bedrock live, or recordings). ``ids`` limits items per source.
    Rejected model outputs are reported, never dropped; ``strict`` fails the step on any rejection, otherwise the
    rejections go to the human review with their reasons (no DRAFT is written for them)."""
    out: dict[str, Any] = {}
    errors: list[str] = []
    for src in SOURCES:
        doc = json.loads((ws.sources / f"{src}.json").read_text(encoding="utf-8"))
        root = Path(_default_path(src)).resolve()
        want = (ids or {}).get(src)
        if ids is not None and not want:
            continue
        s = es.extract_items(doc, root, gateway, drafts_dir=ws.drafts, dimensions=es.load_dimensions(), ids=want,
                             catalog_dir=ws.catalogs, scorer=scorer if src == "aigf" else None)
        out[src] = {"drafted": s.drafted, "inexpressible": [k for k, _ in s.inexpressible], "missing": s.missing,
                    "unchanged": s.unchanged, "versions": s.versions,
                    "errors": [f"{k}: {m}" for k, m in s.errors]}
        errors += out[src]["errors"]
    if errors and strict:
        raise RuntimeError(f"extraction errors: {errors[:3]}")
    out["rejected"] = errors
    out["drafts"] = sorted(p.stem for p in ws.drafts.glob("*.json")) if ws.drafts.exists() else []
    return out


def check_consistency(ws: Workspace) -> dict[str, Any]:
    """Check the workspace catalogs; raises ValueError listing up to three errors."""
    paths = [ws.catalogs / "controls.catalog.yaml", ws.catalogs / "risks.catalog.yaml"]
    errs = consistency.check(consistency.load_catalogs(paths), consistency.load_source_ids(ws.sources))
    if errs:
        raise ValueError(f"{len(errs)} consistency error(s): {[str(e) for e in errs[:3]]}")
    return {"consistent": True}


def record_review(ws: Workspace, by: str, role: str, outcome: str, rationale: str) -> dict[str, Any]:
    """Human review of the extracted drafts. Drafts are not merged into the approved catalogs automatically:
    an editor copies reviewed drafts in (walkthrough step 2); this record is the reviewer's decision."""
    drafts = sorted(p.stem for p in ws.drafts.glob("*.json")) if ws.drafts.exists() else []
    rec = {"by": by, "role": role, "outcome": outcome, "rationale": rationale, "drafts": drafts,
           "at": datetime.now(timezone.utc).isoformat()}
    (ws.root / "rule-review.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
    if outcome != "APPROVED":
        raise ValueError(f"rule review outcome {outcome}: compile not allowed")
    return {"review": outcome, "drafts_reviewed": len(drafts)}


def compile_rulesets(ws: Workspace) -> dict[str, Any]:
    """Compile the workspace catalogs into rulesets and report each ruleset's hash, rule count and whether it matches the repo copy."""
    res = compile_mod.compile_all(ws.catalogs, ws.rulesets)
    repo = {k: sha256_hex((RULESET_DIR / f"{k}.spectral.yaml").read_bytes()) for k in res}
    return {k: {"sha256": c.sha256, "rules": len(c.rule_codes), "matches_repo": sha256_hex(c.text.encode("utf-8")) == repo[k],
                "path": str(ws.rulesets / f"{k}.spectral.yaml")} for k, c in res.items()}
