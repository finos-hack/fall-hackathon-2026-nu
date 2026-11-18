"""Generate Rules (MVP): upload control documents -> DRAFT rules in the main catalogs -> review/approve -> compile.

Same rule-authoring path as the CLI: Bedrock through Strands (temperature 0.1, steering), Rule_Codes and fields fixed
by code, Decider likelihood/impact for risks, hash rule (unchanged documents are not re-extracted), drafts merged into
the main catalogs as DRAFT (shown as PENDING HUMAN REVIEW), approval with the MVP button, then ruleset compile.
Each run is kept under ``<data>/rule-runs/<run_id>/`` (uploaded files, drafts, summary).
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.datastructures import UploadFile   # what request.form() returns (FastAPI's UploadFile subclasses it)

router = APIRouter()
_RUN = re.compile(r"^[0-9]{8}T[0-9]{6}-[0-9a-f]{6}$")


def _render(request: Request, name: str, status: int = 200, **ctx) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, name, ctx, status_code=status)


def _runs_dir(request: Request) -> Path:
    return Path(request.app.state.data_dir) / "rule-runs"


def _catalog_dir(request: Request) -> Path:
    return Path(request.app.state.catalog_paths[0]).parent


def _model(request: Request):
    """(gateway, scorer, mode label): live Bedrock + Decider when configured, else recordings only."""
    from agip_shared.gateway import ModelGateway, Recorder
    from rule_authoring import extract_sources as es, extraction as ex, scoring
    s = request.app.state.settings
    rec = Path(request.app.state.data_dir) / "llm-records"
    if s.model_provider == "bedrock" and s.bedrock_model_id:
        from agip_shared.gateway.runtime_strands import StrandsRuntime
        rt = StrandsRuntime(profile=s.aws_profile, temperature=0.1,
                            steering=ex.steering_check(es.load_dimensions(), ex.load_fields()))
        gw, label = ModelGateway("bedrock", s.bedrock_model_id, s.aws_region, Recorder(rec), rt), f"Bedrock {s.bedrock_model_id}"
    else:
        gw, label = ModelGateway("replay", recorder=Recorder(rec)), "recordings only (MODEL_PROVIDER is not bedrock)"
    scorer = scoring.from_settings(s, "http" if s.decider_provider == "http" else "replay", rec / "decider-scores")
    return gw, scorer, label


@router.get("/rules/new", response_class=HTMLResponse)
def new_rules(request: Request):
    """Upload page with the supported formats."""
    from rule_authoring import upload
    _, _, label = _model(request)
    runs = sorted((p.name for p in _runs_dir(request).glob("*") if _RUN.match(p.name)), reverse=True)[:10]
    return _render(request, "rules_new.html", supported=upload.SUPPORTED, max_kb=upload.MAX_BYTES // 1000,
                   max_items=upload.MAX_ITEMS, model=label, runs=runs, errors=[])


@router.post("/rules/new", response_class=HTMLResponse)
async def generate_rules(request: Request):
    """Parse the uploaded files, extract DRAFT rules, merge them into the main catalogs as DRAFT, open the run."""
    from rule_authoring import extract_sources as es, merge, upload
    form = await request.form()
    files = [f for f in form.getlist("files") if isinstance(f, UploadFile) and f.filename]
    if not files:
        raise HTTPException(422, "choose at least one file")
    items, problems, saved = [], [], []
    run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    run = _runs_dir(request) / run_id
    (run / "uploads").mkdir(parents=True)
    for f in files:
        data = await f.read(upload.MAX_BYTES + 1)
        got, errs = upload.parse_upload(f.filename, data)
        problems += errs
        if got:
            (run / "uploads" / got[0].filename).write_bytes(data)
            saved.append({"file": got[0].filename, "sha256": got[0].sha256, "items": [i.key for i in got]})
        items += got
    if len(items) > upload.MAX_ITEMS:
        problems.append(f"{len(items)} items found; only the first {upload.MAX_ITEMS} are extracted in one run")
        items = items[:upload.MAX_ITEMS]
    gw, scorer, label = _model(request)
    drafts = run / "drafts"
    s = es.extract_uploads(items, gw, drafts_dir=drafts, catalog_dir=_catalog_dir(request),
                           dimensions=es.load_dimensions(), scorer=scorer)
    merged = merge.merge_drafts(drafts, _catalog_dir(request)) if drafts.is_dir() else {}
    summary = {"run_id": run_id, "created": datetime.now(timezone.utc).isoformat(), "model": label, "files": saved,
               "problems": problems, "items": [{"id": i.key, "framework": i.framework, "kind": i.kind, "title": i.title,
                                                 "file": i.filename} for i in items],
               "drafted": s.drafted, "inexpressible": dict(s.inexpressible), "errors": dict(s.errors), "missing": s.missing,
               "unchanged": s.unchanged, "versions": s.versions, "reused_model_answers": gw.reused,
               "merged": {k: {"action": a, "version": v} for k, (a, v) in merged.items()}}
    (run / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return RedirectResponse(f"/rules/runs/{run_id}", status_code=303)


def _summary(request: Request, run_id: str) -> dict[str, Any]:
    if not _RUN.match(run_id):
        raise HTTPException(404, "unknown run")
    f = _runs_dir(request) / run_id / "summary.json"
    if not f.is_file():
        raise HTTPException(404, "unknown run")
    return json.loads(f.read_text(encoding="utf-8"))


@router.get("/rules/runs/{run_id}", response_class=HTMLResponse)
def rules_run(request: Request, run_id: str):
    """Results of one Generate Rules run with the current catalog status of every item and the review actions."""
    from rule_authoring import versioning
    sm = _summary(request, run_id)
    rows = []
    for it in sm["items"]:
        e = versioning.find_entry(it["id"], _catalog_dir(request)) or {}
        kind = "risks" if "risk_id" in e else "controls"
        rule = next(iter((e.get("spectral_rules") or {}).items()), None)
        sc = e.get("scoring") or {}
        rows.append({**it, "status": e.get("status"), "version": e.get("version"), "catalog": kind, "in_catalog": bool(e),
                     "rule": rule, "likelihood": e.get("likelihood"), "impact": e.get("impact"), "scoring": sc,
                     "remediation": e.get("remediation") or next((c.get("remediation") for c in e.get("configurations") or []), None),
                     "inexpressible": sm["inexpressible"].get(it["id"]), "error": sm["errors"].get(it["id"]),
                     "missing": it["id"] in sm["missing"], "unchanged": it["id"] in sm["unchanged"],
                     "merge": (sm["merged"].get(it["id"]) or {}).get("action")})
    return _render(request, "rules_run.html", sm=sm, rows=rows, compiled=sm.get("compiled"))


@router.post("/rules/runs/{run_id}/compile")
def compile_run(request: Request, run_id: str):
    """Consistency check + compile the APPROVED catalog items into the Spectral rulesets (version bumps on change)."""
    from rule_authoring import compile as comp
    sm = _summary(request, run_id)
    rulesets = Path(request.app.state.catalog_paths[0]).parents[1] / "rulesets"
    try:
        res = comp.compile_all(_catalog_dir(request), rulesets)
        sm["compiled"] = {"ok": True, "at": datetime.now(timezone.utc).isoformat(),
                          "rulesets": {k: {"version": c.version, "rules": len(c.rule_codes), "sha256": c.sha256[:12],
                                           "unexpressible": [str(u) for u in c.unexpressible]} for k, c in res.items()}}
    except ValueError as exc:
        sm["compiled"] = {"ok": False, "at": datetime.now(timezone.utc).isoformat(), "error": str(exc)[:2000]}
    (_runs_dir(request) / run_id / "summary.json").write_text(json.dumps(sm, indent=2), encoding="utf-8")
    return RedirectResponse(f"/rules/runs/{run_id}", status_code=303)
