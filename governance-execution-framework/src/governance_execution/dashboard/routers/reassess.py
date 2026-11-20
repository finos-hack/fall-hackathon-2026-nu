"""Re-assess an unsuccessful assessment with a corrected CALM model.

The developer fixes the model outside the dashboard and uploads it here. It goes through the normal assessment
flow (CALM validation, Spectral, gap, risk, decision, remediation) as a new run that records ``supersedes``.
The old run is left unchanged.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from agip_shared.hashing import canonical_json, sha256_hex

from ..data import reassessable
from .api import _body, _parse

router = APIRouter()
MODES = ("normal", "no-llm")


def _original(request: Request, trace: str) -> tuple[dict, dict]:
    """Return (summary, versions) of ``trace`` or raise 404; raise 409 if the assessment is not eligible for re-assessment."""
    store = request.app.state.reports
    if trace not in store.traces():
        raise HTTPException(404, "assessment not found")
    s = store.summary(trace)
    if not reassessable(s):
        raise HTTPException(409, "re-assessment is only available for BLOCKED, FAILED, REJECTED, RESTRICTED or INDETERMINATE assessments")
    return s, store.get(trace, "versions") or {}


@router.get("/assessments/{trace}/reassess", response_class=HTMLResponse)
def reassess_page(request: Request, trace: str):
    """Upload form for a corrected CALM model, with a link to download the model of the original run."""
    s, _ = _original(request, trace)
    store = request.app.state.reports
    ids = store.kinds(trace).get("app_model") or []
    return request.app.state.templates.TemplateResponse(
        request, "reassess.html", {"s": s, "model_url": f"/artifacts/{trace}/app_model/{ids[0]}" if ids else None, "modes": MODES})


@router.post("/assessments/{trace}/reassess")
async def reassess(request: Request, trace: str, mode: str = ""):
    """Assess the uploaded CALM model (raw JSON or YAML body, up to 1 MB) as a new run that supersedes ``trace``. Responds 409 if the original is not eligible, 422 for a non-CALM or unchanged model."""
    s, v = _original(request, trace)
    mode = mode or (s.get("mode") if s.get("mode") in MODES else "no-llm")
    if mode not in MODES:
        raise HTTPException(400, "mode must be normal or no-llm")
    doc = _parse(await _body(request))
    if not isinstance(doc, dict) or not isinstance(doc.get("nodes"), list):
        raise HTTPException(422, "a CALM model must be an object with a 'nodes' list")
    sha = sha256_hex(canonical_json(doc))
    old = request.app.state.reports.get(trace, "app_model")
    if old is not None and sha256_hex(canonical_json(old)) == sha:
        raise HTTPException(422, "the uploaded model is identical to the one already assessed; fix it before re-assessing")
    sink = request.app.state.sink
    up = f"upload-{sha[:16]}"
    sink.put(up, "app_model", "upload", doc)
    app_id = s.get("app_id") or trace
    coord, ex = request.app.state.build(mode)
    out = coord.run(doc, executor=ex, template_id=v.get("template_id"),
                    source={"app_id": app_id, "app_model_ref": f"{up}/app_model/upload", "supersedes": trace})
    return {"trace_id": out.trace_id, "status": out.status, "decision": out.decision, "error": out.error,
            "report": f"/assessments/{out.trace_id}"}
