"""JSON API (Req 4.3, 9.1, 12.1-12.4, 20.4, 24.2). Uploads are data only; all paths go through resolve_within."""
from __future__ import annotations

import json
import uuid
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from agip_shared.hashing import canonical_json, sha256_hex
from agip_shared.paths import PathEscapeError, resolve_within
from calm_generation import attributes as attrs
from rule_authoring import approval

from ...obs.replay import ReplayFailed, replay
from ...units.calm_builder import instantiate, load_template

router = APIRouter(prefix="/api")
MAX_UPLOAD = 1024 * 1024


def _parse(body: bytes) -> Any:
    """Decode an upload as JSON, falling back to YAML. Raises HTTP 415 if it is not UTF-8 or not valid JSON/YAML."""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(415, "upload must be UTF-8 JSON or YAML")
    try:
        return json.loads(text)
    except ValueError:
        pass
    try:
        return yaml.safe_load(text)  # safe loader: data only, never executed
    except yaml.YAMLError:
        raise HTTPException(415, "upload must be valid JSON or YAML")


async def _body(request: Request) -> bytes:
    """Read the request body, rejecting it with HTTP 413 if it exceeds MAX_UPLOAD."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD:
        raise HTTPException(413, "upload larger than 1 MB")
    body = await request.body()
    if len(body) > MAX_UPLOAD:
        raise HTTPException(413, "upload larger than 1 MB")
    return body


def _app_ref(request: Request, ref: str) -> tuple[str, str, str]:
    """Split and validate an ``<trace>/<kind>/<id>`` artifact reference. Raises HTTP 400 if malformed or if it escapes the data dir."""
    parts = ref.split("/")
    if len(parts) != 3 or not all(parts):
        raise HTTPException(400, "app_model_ref must be <trace>/<kind>/<id>")
    try:
        resolve_within(request.app.state.data_dir, f"artifacts/{ref}.json")
    except PathEscapeError:
        raise HTTPException(400, "invalid reference")
    return parts[0], parts[1], parts[2]


@router.post("/upload")
async def upload(request: Request):
    """Upload a CALM model (JSON or YAML, up to 1 MB) and store it as an artifact. Returns the reference to pass to the assess endpoint and the SHA-256. Responds 413, 415 or 422 for oversized, unparseable or non-CALM input."""
    doc = _parse(await _body(request))
    if not isinstance(doc, dict) or not isinstance(doc.get("nodes"), list):
        raise HTTPException(422, "a CALM model must be an object with a 'nodes' list")
    sink = request.app.state.sink
    trace = f"upload-{sha256_hex(canonical_json(doc))[:16]}"
    a = sink.put(trace, "app_model", "upload", doc)
    return {"app_model_ref": f"{trace}/app_model/upload", "sha256": a.sha256}


class AssessIn(BaseModel):
    """Request body for ``POST /assess``.

    ``app_model_ref`` is ``<trace>/app_model/<id>`` as returned by the upload endpoint.
    ``mode`` is one of ``normal``, ``no-llm`` or ``replay``; ``template_id`` optionally
    selects the RA template the assessment is composed from.
    """

    app_model_ref: str
    mode: str = "normal"
    template_id: str | None = None


@router.post("/assess")
def assess(request: Request, body: AssessIn):
    """Run a governance assessment on a previously uploaded CALM model. Returns the trace id, status, decision and a link to the report. Responds 400 for a bad reference or mode and 404 if the model is not found."""
    trace, kind, aid = _app_ref(request, body.app_model_ref)
    if kind != "app_model":
        raise HTTPException(400, "reference must point to an app_model artifact")
    try:
        app = request.app.state.sink.get(trace, kind, aid)
    except (KeyError, PathEscapeError, FileNotFoundError):
        raise HTTPException(404, "app model not found")
    if body.mode not in ("normal", "no-llm", "replay"):
        raise HTTPException(400, "mode must be normal, no-llm or replay")
    coord, ex = request.app.state.build(body.mode)
    out = coord.run(app, executor=ex, template_id=body.template_id,
                    source={"app_id": aid if aid != "upload" else trace, "app_model_ref": body.app_model_ref})
    return {"trace_id": out.trace_id, "status": out.status, "decision": out.decision, "error": out.error,
            "executor": out.executor, "report": f"/assessments/{out.trace_id}"}


class ApproveIn(BaseModel):
    """Request body for ``POST /rules/{item_id}/approve``; ``by`` is the approver recorded on the catalog entry."""

    by: str
    confirm_scores: bool = False   # for risks: approver confirms the model-proposed likelihood/impact


@router.post("/rules/{item_id}/approve")
def approve_rule(request: Request, item_id: str, body: ApproveIn):
    """Approve a draft control or risk in the catalogs, recording who approved it. Responds 404 if the item is not found and 409 if it cannot be approved in its current state."""
    for path in request.app.state.catalog_paths:
        try:
            e = approval.approve_in_catalog(path, item_id, body.by, confirm_scores=body.confirm_scores)
            return {"id": item_id, "status": e["status"], "approved_by": e["approved_by"], "approved_at": e["approved_at"]}
        except approval.ApprovalError as exc:
            if "not found" in str(exc):
                continue
            raise HTTPException(409, str(exc))
    raise HTTPException(404, f"{item_id} not found")


def _template(template_id: str):
    """Load a CALM template; only PUBLISHED reference architecture templates are exposed (else HTTP 404)."""
    from calm_generation import lifecycle as lc

    from ...units.calm_builder import TEMPLATE_DIR
    if template_id not in {t["id"] for t in lc.published_templates(TEMPLATE_DIR, lc.REGISTRY)}:
        raise HTTPException(404, "unknown template")
    return load_template(template_id)


@router.get("/attributes-form/{template_id}", response_class=PlainTextResponse)
def attributes_form(template_id: str):
    """Download the blank attributes form (YAML) for a CALM template. Fill it in and post it to the instantiate endpoint."""
    tpl, text = _template(template_id)
    return yaml.safe_dump(attrs.form_for(tpl, text, "PUBLISHED"), sort_keys=False)


@router.post("/instantiate")
async def instantiate_api(request: Request):
    """Generate and validate a CALM model from a filled attributes form (JSON or YAML). Returns the status, the reference to the generated model when one was stored, errors, correction guidance and the generation manifest."""
    form = _parse(await _body(request))
    if not isinstance(form, dict):
        raise HTTPException(422, "form must be a mapping")
    tpl_id = (form.get("template") or {}).get("id", "")
    tpl, text = _template(tpl_id)
    coord, _ = request.app.state.build("no-llm")
    r = instantiate(form, template=tpl, template_text=text, template_status="PUBLISHED", calm=coord.ctx.calm,
                    sink=request.app.state.sink, trace_id=f"gen-{uuid.uuid4().hex[:12]}")
    ref = f"{r.trace_id}/app_model/{r.app_id}" if r.artifact_ids.get("app_model") else None
    return {"status": r.status, "app_model_ref": ref, "errors": r.errors, "guidance": r.guidance,
            "manifest": r.manifest, "template_id": tpl_id}


@router.post("/replay/{trace}")
def replay_api(request: Request, trace: str):
    """Replay a stored assessment from its recordings and report whether the result is identical to the original, with any differences. Responds 409 if the replay cannot be performed."""
    coord, ex = request.app.state.build("replay")
    try:
        rep = replay(trace, coord, ex)
    except ReplayFailed as exc:
        raise HTTPException(409, str(exc))
    return {"original": rep.original_trace, "replay": rep.replay_trace, "identical": rep.identical,
            "differences": rep.differences, "decision": rep.decision_replay}
