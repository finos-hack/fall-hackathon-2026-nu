"""CALM Generation lifecycle as discrete workflow steps (Architecture Lifecycle in Fluxnova).

Order: draft_patterns (Strands agent + CALM AI skills) -> (human pattern review) -> approve_patterns ->
compose_template -> (human template review) -> publish_template -> instantiate_app.

Every step works in a run workspace (copies of ``patterns/``, ``registry/lifecycle.yaml`` and the compose spec), so an
orchestrated run never changes the repository library. AI drafts enter as DRAFT/CANDIDATE and need a named human
approver before they are composable; a draft that fails validation falls back to the canonical pattern and says so.
"""
from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

import yaml

from agip_shared import versioned_write as vw
from agip_shared.hashing import canonical_json, sha256_hex

from . import attributes as attrs
from . import composer
from . import lifecycle as lc
from . import pattern_library as pl
from .placeholders import fill

TEMPLATES = pl.FRAMEWORK_ROOT / "templates"
SPEC = TEMPLATES / "RA03-LITE.compose.yaml"


class Workspace:
    """Paths of one run's private copy of patterns, registry, compose spec, templates and generated apps."""
    def __init__(self, root: Path):
        """Derive all paths from ``root``; nothing is created on disk."""
        self.root = Path(root)
        self.patterns = self.root / "patterns"
        self.registry = self.root / "lifecycle.yaml"
        self.spec = self.root / SPEC.name
        self.templates = self.root / "templates"
        self.apps = self.root / "apps"


def init_workspace(root: Path) -> Workspace:
    """Create the workspace directories and seed the registry and spec from the repository copies if missing (existing files are kept)."""
    ws = Workspace(root)
    for d in (ws.root, ws.patterns, ws.templates, ws.apps):
        d.mkdir(parents=True, exist_ok=True)
    if not ws.registry.exists():
        shutil.copy(lc.REGISTRY, ws.registry)
    if not ws.spec.exists():
        shutil.copy(SPEC, ws.spec)
    return ws


def _spec(ws: Workspace) -> dict[str, Any]:
    """Load the workspace compose spec."""
    return composer.load_spec(ws.spec)


def draft_patterns(ws: Workspace, agent: Optional[Any], *, workers: int = 4) -> dict[str, Any]:
    """Draft every pattern the compose spec selects. ``agent`` None copies the canonical library (no AI)."""
    canon = pl.load_patterns()
    pids = list(_spec(ws)["patterns"])

    def one(pid: str) -> dict[str, Any]:
        """Draft (or copy, when no agent) a single pattern. A failed AI draft is replaced by the canonical pattern marked as candidate."""
        if agent is None:
            return {"pid": pid, "source": "CANONICAL", "pattern": pl.as_candidate(canon[pid]), "rounds": 0, "errors": []}
        r = agent.draft(pid, canon[pid])
        pat = r.pattern if r.source == "AI" else pl.as_candidate(canon[pid])
        return {"pid": pid, "source": r.source, "pattern": pat, "rounds": r.rounds, "errors": r.errors[:5], "model": r.model,
                "reused": getattr(r, "reused", False)}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(one, pids))
    reg = lc.load(ws.registry)
    report = {}
    for r in results:
        text = pl.dumps(r["pattern"])
        vw.write(ws.patterns / f"{r['pid']}.json", text, content_hash=sha256_hex(text),
                 version=vw.version_for(ws.patterns / f"{r['pid']}.json", sha256_hex(text)))
        # Revision increases only when the drafted text differs from what the registry last recorded.
        prev = reg["entries"].get(r["pid"]) or {}
        rev = int(prev.get("revision", 1)) if prev.get("sha256") in (None, sha256_hex(text)) else int(prev.get("revision", 1)) + 1
        src = f"ai-draft:{r.get('model', '')}" if r["source"] == "AI" else "canonical-library"
        reg["entries"][r["pid"]] = {"kind": "pattern", "state": "DRAFT", "source": src, "version": r["pattern"]["metadata"]["version"],
                                    "revision": rev, "sha256": sha256_hex(text), "history": [
                                        {"from": None, "to": "DRAFT", "by": "pattern-draft-agent" if r["source"] == "AI" else "workflow",
                                         "role": "drafter", "rationale": f"{r['source']} draft, {r['rounds']} round(s)", "at": lc.now()}]}
        report[r["pid"]] = {"source": r["source"], "rounds": r["rounds"], "errors": r["errors"], "sha256": sha256_hex(text),
                            "revision": rev, "unchanged": prev.get("sha256") == sha256_hex(text), "reused": r.get("reused", False)}
    lc.save(reg, ws.registry)
    pats = pl.load_patterns(ws.patterns)
    for pid in pids:
        lc.transition(pid, "IN_REVIEW", by="workflow", role="drafter", rationale="submitted for review", path=ws.registry, patterns=pats)
    (ws.root / "pattern-drafts.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return {"drafted": report, "ai": sum(1 for v in report.values() if v["source"] == "AI"), "total": len(report)}


def approve_patterns(ws: Workspace, by: str, role: str, rationale: str, approved: bool = True) -> dict[str, Any]:
    """Record the human decision on the drafted patterns.

    Rejection moves them to REJECTED and raises ValueError. Approval writes the approver into each pattern file, refreshes its registry hash, then moves it APPROVED -> PUBLISHED.
    """
    pids = list(_spec(ws)["patterns"])
    if not approved:
        for pid in pids:
            lc.transition(pid, "REJECTED", by=by, role=role, rationale=rationale, path=ws.registry, patterns=pl.load_patterns(ws.patterns))
        raise ValueError("pattern review rejected the drafts")
    for pid in pids:      # the approver is recorded in the pattern file, as for the seed library
        p = ws.patterns / f"{pid}.json"
        pat = json.loads(p.read_text(encoding="utf-8"))
        pat["metadata"].update(status="APPROVED", approved_by=by)
        text = pl.dumps(pat)
        p.write_text(text, encoding="utf-8")
        reg = lc.load(ws.registry)
        reg["entries"][pid]["sha256"] = sha256_hex(text)
        lc.save(reg, ws.registry)
    pats = pl.load_patterns(ws.patterns)
    for pid in pids:
        lc.transition(pid, "APPROVED", by=by, role=role, rationale=rationale, path=ws.registry, patterns=pats)
        lc.transition(pid, "PUBLISHED", by=by, role=role, rationale=rationale, path=ws.registry, patterns=pats)
    return {"published": pids}


def compose_template(ws: Workspace, by: str = "workflow") -> dict[str, Any]:
    """Compose the template from the workspace patterns. If the registry holds a different composition for this RA, bump the spec version first (a changed hash needs a new ra-version). Returns the hash and whether it equals the repository template."""
    spec = _spec(ws)
    pats = pl.load_patterns(ws.patterns)
    lc.composable_patterns(spec, pats, ws.registry)
    res = composer.compose(pats, spec)
    if not res.ok:
        raise ValueError(f"compose failed: conflicts={[str(c) for c in res.conflicts][:3]} errors={res.errors[:3]}")
    prev = lc.load(ws.registry)["entries"].get(spec["ra_id"])
    if prev and prev.get("composed_sha256") != sha256_hex(res.text):   # new patterns -> new RA version (lifecycle rule)
        spec["version"] = max([int(v["version"]) for v in prev.get("versions", [])] + [int(prev["version"])]) + 1
        ws.spec.write_text(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True), encoding="utf-8")
        res = composer.compose(pats, spec)
        if not res.ok:
            raise ValueError(f"compose failed: {res.errors[:3]}")
    lc.record_composition(spec["ra_id"], int(spec["version"]), res.text, res.template, by=by, path=ws.registry)
    out = ws.templates / f"{spec['ra_id']}.json"
    vw.write(out, res.text, content_hash=sha256_hex(res.text), version=int(spec["version"]))
    repo = (TEMPLATES / f"{spec['ra_id']}.json")
    return {"ra_id": spec["ra_id"], "sha256": sha256_hex(res.text), "path": str(out),
            "matches_repo_template": repo.exists() and sha256_hex(repo.read_text(encoding="utf-8")) == sha256_hex(res.text)}


def publish_template(ws: Workspace, by: str, role: str, rationale: str, approved: bool = True) -> dict[str, Any]:
    """Walk the RA through IN_REVIEW -> APPROVED -> PUBLISHED, or reject it (raises ValueError) when ``approved`` is False."""
    ra = _spec(ws)["ra_id"]
    if not approved:
        lc.transition(ra, "IN_REVIEW", by=by, role=role, rationale="submitted", path=ws.registry)
        lc.transition(ra, "REJECTED", by=by, role=role, rationale=rationale, path=ws.registry)
        raise ValueError("template review rejected the composition")
    for target in ("IN_REVIEW", "APPROVED", "PUBLISHED"):
        lc.transition(ra, target, by=by, role=role, rationale=rationale, path=ws.registry)
    return {"ra_id": ra, "state": lc.state_of(ra, ws.registry)}


def instantiate_app(ws: Workspace, attributes_file: Path, calm: Any) -> dict[str, Any]:
    """Fill the published template from an attributes file, run ``calm generate``, fill placeholders, ``calm validate``."""
    ra = _spec(ws)["ra_id"]
    text = (ws.templates / f"{ra}.json").read_text(encoding="utf-8")
    tpl = json.loads(text)
    form = attrs.form_for(tpl, text, lc.state_of(ra, ws.registry))     # refuses unless PUBLISHED
    given = yaml.safe_load(Path(attributes_file).read_text(encoding="utf-8"))
    form["app"], form["values"], form["options"] = given["app"], given["values"], given["options"]
    errs = attrs.validate(form, tpl, text)
    errs += attrs.consistency_errors(form, attrs.load_consistency(ra))
    if errs:
        raise ValueError("attributes rejected: " + "; ".join(str(e) for e in errs[:5]))
    gen = calm.generate(tpl, attrs.option_choices(form))
    if gen.status != "OK":
        raise RuntimeError(f"calm generate: {gen.error}")
    filled = fill(gen.model, form, tpl)
    if filled.model is None:
        raise ValueError(f"leftover placeholders: {filled.leftovers[:5]}")
    v = calm.validate(filled.model, tpl)
    app_id = form["app"]["id"]
    out = ws.apps / f"{app_id}.json"
    app_text = json.dumps(filled.model, indent=2, sort_keys=True) + "\n"
    ch = sha256_hex(canonical_json(filled.model))
    w = vw.write(out, app_text, content_hash=ch, version=vw.version_for(out, ch),
                 inputs_hash=vw.hash_inputs(template=sha256_hex(text), attributes=attrs.attributes_hash(form)))
    return {"app_id": app_id, "path": str(out), "sha256": ch, "version": w.version, "write": w.action,
            "validation": v.status,
            "errors": [f"{e.path}: {e.message}" for e in (v.errors or [])][:5]}
