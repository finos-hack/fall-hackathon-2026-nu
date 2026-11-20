"""HTML pages (Req 13.7, 15.5, 22.5, 25.2-25.6). Read persisted artifacts only."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from ...units.risk_assessment import load_scoring
from .. import data, portal

router = APIRouter()
STATIC = Path(__file__).resolve().parents[1] / "static"


def _store(request: Request) -> data.ReportStore:
    """The app's read-only report store."""
    return request.app.state.reports


def _render(request: Request, name: str, **ctx) -> HTMLResponse:
    """Render a template with the app's Jinja environment."""
    return request.app.state.templates.TemplateResponse(request, name, ctx)


def _bundle(request: Request, trace: str) -> dict:
    """Load all artifacts of an assessment. Raises HTTP 404 if the trace is unknown."""
    store = _store(request)
    if trace not in store.traces():
        raise HTTPException(404, "assessment not found")
    return store.bundle(trace)


def report_context(request: Request, trace: str) -> dict:
    """Build the template context shared by the report page and its panels: summary, artifact bundle, fact groups, matrix, diagrams and Decider calls."""
    b = _bundle(request, trace)
    s = _store(request).summary(trace)
    scoring = load_scoring()
    tid = (b.get("versions") or {}).get("template_id")
    ra = {"id": tid, "patterns": data.compose_spec(tid).get("_source_patterns") or []}
    facts = (b.get("facts") or {}).get("facts") or []
    calls = b.get("decider_calls") or []
    return {"s": s, "b": b, "ra": ra, "scoring_label": scoring.get("label"),
            "matrix": data.risk_matrix(b, scoring) if b.get("risk_profile") else None,
            "unmapped": [f for f in facts if f["mapping_status"] in ("UNMAPPED", "UNKNOWN") and f["mapping_status"] == "UNMAPPED"],
            "unknown": [f for f in facts if f["mapping_status"] == "UNKNOWN"],
            "inferred": [f for f in facts if f["mapping_status"] == "INFERRED"],
            "decider_unavailable": [c for c in calls if c.get("outcome") == "ERROR"],
            "decider_calls": calls,
            "arch": data.architecture_mermaid(b) if b.get("app_model") else "",
            "flow": data.flow_mermaid(b, s["executor"] or "?"),
            "pending": pending_tasks(request, trace),
            "reassess": data.reassessable(s), "supersedes": s["supersedes"], "superseded_by": _store(request).superseded_by(trace),
            "kinds": _store(request).kinds(trace)}


OPEN_TASK = ("OPEN", "ASSIGNED", "CLAIMED", "CHANGES_REQUESTED")


def pending_tasks(request: Request, trace: str) -> list:
    """Open human review tasks of this assessment (MVP: decided with one Approve button in the report)."""
    from agip_shared.humantasks import HumanTaskStore
    try:
        return [t for t in HumanTaskStore(request.app.state.data_dir).list(trace_id=trace) if t.status in OPEN_TASK]
    except Exception:  # noqa: BLE001 - a missing store means nothing is pending
        return []


def _listing(request: Request, title: str, subtitle: str, columns: list[str], rows: list[dict],
             facets: list[tuple[str, str]], defaults: dict | None = None, hint: str = "",
             tabs: list | None = None) -> HTMLResponse:
    """Render the shared listing page: apply search, filters and pagination (invalid ``page`` falls back to 1)."""
    params = dict(request.query_params)
    try:
        page = int(params.get("page") or 1)
    except ValueError:
        page = 1
    listing = portal.build_listing(rows, params, request.url.path, facets, page, defaults)
    return _render(request, "listing.html", title=title, subtitle=subtitle, columns=columns, pg=listing, hint=hint, tabs=tabs)


@router.get("/assessments", response_class=HTMLResponse)
def index(request: Request):
    """List all assessments with filters for decision, status and application."""
    return _listing(request, "Assessments", "Every assessment run. Expand a row to read the report; click a control, risk or "
                    "pattern ID in it to open the matching catalog entry.",
                    ["Application", "Decision", "Status", "CALM", "Time", "Trace"], portal.assessment_rows(_store(request)),
                    [("decision", "Decision"), ("status", "Status"), ("application", "Application")],
                    hint="No assessments yet. Run <code>bash scripts/demo.sh</code>.")


@router.get("/assessments/{trace}", response_class=HTMLResponse)
def report(request: Request, trace: str, partial: int = 0):
    """Full assessment report. With ``partial=1`` returns only the body used for expanding a row in the assessments list."""
    ctx = report_context(request, trace)
    if partial:  # the expandable report inside the Assessments list
        return _render(request, "_report_body.html", export=False, partial=True, **ctx)
    return _render(request, "report.html", export=False, **ctx)


@router.get("/assessments/{trace}/flow", response_class=HTMLResponse)
def flow(request: Request, trace: str):
    """Diagram of the assessment pipeline with each step's status."""
    ctx = report_context(request, trace)
    return _render(request, "diagram.html", title="Pipeline flow", diagram=ctx["flow"], s=ctx["s"])


@router.get("/assessments/{trace}/architecture", response_class=HTMLResponse)
def architecture(request: Request, trace: str):
    """Architecture diagram of the assessed CALM model, coloured by worst finding."""
    ctx = report_context(request, trace)
    return _render(request, "diagram.html", title="Architecture (coloured by worst finding)", diagram=ctx["arch"], s=ctx["s"])


@router.get("/assessments/{trace}/risk-matrix", response_class=HTMLResponse)
def risk_matrix(request: Request, trace: str):
    """Likelihood and impact matrix showing where each triggered risk falls."""
    return _render(request, "panel.html", panel="matrix", **report_context(request, trace))


@router.get("/assessments/{trace}/decider", response_class=HTMLResponse)
def decider(request: Request, trace: str):
    """Decider calls made for this assessment and the facts they classified."""
    return _render(request, "panel.html", panel="decider", **report_context(request, trace))


@router.get("/assessments/{trace}/trace", response_class=HTMLResponse)
def explorer(request: Request, trace: str, node: str = "decision"):
    """Trace explorer: show one node of the evidence graph (default: the decision) with its incoming and outgoing links. Responds 404 for an unknown node."""
    b = _bundle(request, trace)
    g = data.graph(b)
    if node not in g.nodes:
        raise HTTPException(404, "trace node not found")
    return _render(request, "trace.html", s=_store(request).summary(trace), node=g.nodes[node],
                   outgoing=[(g.nodes[n], l) for n, l in g.outgoing(node) if n in g.nodes],
                   incoming=[(g.nodes[n], l) for n, l in g.incoming(node) if n in g.nodes],
                   all_nodes=sorted(g.nodes.values(), key=lambda n: (n["kind"], n["id"])))


@router.get("/assessments/{trace}/export", response_class=HTMLResponse)
def export(request: Request, trace: str):
    """Download the assessment report as one self-contained HTML file (CSS and diagram script embedded)."""
    ctx = report_context(request, trace)
    html = request.app.state.templates.get_template("report.html").render(
        request=request, export=True, css=(STATIC / "app.css").read_text(encoding="utf-8"),
        mermaid_js=(STATIC / "mermaid.min.js").read_text(encoding="utf-8"), **ctx)
    return HTMLResponse(html, headers={"Content-Disposition": f'attachment; filename="assessment-{trace}.html"'})


@router.get("/artifacts/{trace}/{kind}/{aid}")
def artifact(request: Request, trace: str, kind: str, aid: str):
    """Download one stored artifact as JSON. Responds 404 if it does not exist."""
    store = _store(request)
    if trace not in store.traces() or aid not in (store.kinds(trace).get(kind) or []):
        raise HTTPException(404, "artifact not found")
    return JSONResponse(store.get(trace, kind, aid),
                        headers={"Content-Disposition": f'attachment; filename="{trace}-{kind}-{aid}.json"'})


@router.get("/catalogs/file/{name}")
def catalog_file(name: str):
    """Serve a CALM pattern / RA template JSON file for viewing in a new tab."""
    from .. import mvp_data
    if name != Path(name).name or not name.endswith(".json"):
        raise HTTPException(404, "file not found")
    for sub in ("patterns", "templates"):
        f = mvp_data.CG / sub / name
        if f.is_file():
            return Response(f.read_text(encoding="utf-8"), media_type="application/json",
                            headers={"Content-Disposition": "inline"})
    raise HTTPException(404, "file not found")


@router.get("/catalogs/{kind}", response_class=HTMLResponse)
def catalog(request: Request, kind: str):
    """Browse the controls, risks or CALM patterns catalog. The ``templates`` view is the patterns list filtered to RA templates."""
    store = _store(request)
    if kind == "controls":
        return _listing(request, "Controls Catalog", "Approved controls. Expand a row for configurations, rule codes and remediation.",
                        ["ID", "Title", "Status", "Severity", "Mandatory", "Source"], portal.control_rows(store),
                        [("status", "Status"), ("severity", "Severity"), ("mandatory", "Mandatory"), ("source", "Source")])
    if kind == "risks":
        return _listing(request, "Risk Profile Catalog", "Approved risks with likelihood and impact. Expand a row for details.",
                        ["ID", "Title", "Status", "Likelihood x Impact", "Dimension", "Source"], portal.risk_rows(store),
                        [("status", "Status"), ("dimension", "Dimension"), ("source", "Source")])
    if kind in ("patterns", "templates"):  # RA templates are part of the CALM patterns catalog
        return _listing(request, "CALM Patterns Catalog", "Reusable CALM patterns and the assessment-requirement (RA) templates built from them.",
                        ["ID", "Title", "Type", "Status", "Version"], portal.pattern_rows(store),
                        [("type", "Type"), ("status", "Status")],
                        defaults={"type": portal.RA_TYPE} if kind == "templates" else None)
    raise HTTPException(404, "unknown catalog")

@router.get("/source-registry", response_class=HTMLResponse)
@router.get("/source-registry/{section}", response_class=HTMLResponse)
def source_registry(request: Request, section: str = "sources"):
    """Source registry: extraction sources, risk dimensions, scoring and config files, or design decisions (ADRs), selected by section."""
    store = _store(request)
    tabs = [(label, f"/source-registry/{key}", key == section) for key, label in portal.SECTIONS]
    if section == "sources":
        return _listing(request, "Source Registry", "Extraction sources: the AIGF and CCC items that rules are authored from.",
                        ["ID", "Title", "Type", "Framework", "File"], portal.source_rows(store),
                        [("type", "Type"), ("framework", "Framework")], tabs=tabs)
    if section == "dimensions":
        return _listing(request, "Source Registry", "Risk dimensions: the taxonomy attributes and the risks that belong to each dimension.",
                        ["Dimension", "Taxonomy attributes", "Risks"], portal.dimension_rows(store),
                        [("in_taxonomy", "In taxonomy"), ("has_risks", "Has risks")], tabs=tabs)
    if section == "scoring":
        return _listing(request, "Source Registry", "Scoring profile, decision logic, taxonomy and policy files. Expand a row to read the file.",
                        ["Name", "Type", "Version", "Label", "SHA-256"], portal.scoring_rows(store), [("type", "Type")], tabs=tabs)
    if section == "adrs":
        return _listing(request, "Source Registry", "Design decisions and deliberate changes. Expand a row for the summary and the full text.",
                        ["ID", "Decision", "Status", "Document"], portal.adr_rows(),
                        [("status", "Status"), ("document", "Document")], tabs=tabs)
    raise HTTPException(404, "unknown source registry section")

@router.get("/versions", response_class=HTMLResponse)
def versions(request: Request):
    """Versions recorded by each assessment."""
    store = _store(request)
    rows = [(s, store.get(s["trace_id"], "versions")) for s in store.assessments()]
    return _render(request, "versions.html", rows=rows)


@router.get("/variants", response_class=HTMLResponse)
def variants(request: Request):
    """Latest non-replay assessment per application, compared by gap level, risk level, tier, failed controls and triggered risks."""
    store = _store(request)
    latest: dict[str, dict] = {}
    for s in store.assessments():  # newest first
        if s["app_id"] and not s["replay_of"] and s["app_id"] not in latest:
            b = store.bundle(s["trace_id"])
            latest[s["app_id"]] = {"s": s, "gap": (b.get("control_gap") or {}).get("gap_level"),
                                   "profile": (b.get("risk_profile") or {}).get("profile_level"),
                                   "tier": (b.get("risk_profile") or {}).get("tier"),
                                   "failed": [c["control_id"] for c in (b.get("control_gap") or {}).get("controls") or [] if c["status"] == "FAIL"],
                                   "risks": [r["risk_id"] for r in (b.get("risk_profile") or {}).get("risks") or []],
                                   "calm": (b.get("calm_validation") or {}).get("status")}
    return _render(request, "variants.html", rows=[latest[k] for k in sorted(latest)])


@router.get("/healthz")
def healthz() -> Response:
    """Liveness check; returns plain text ``ok``."""
    return Response("ok", media_type="text/plain")
