"""MVP dashboard pages (Req 24.5, 25.1-25.6): server-rendered, read persisted records; only the review action writes (via HumanTaskStore)."""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from agip_shared.humantasks import HumanTaskError, HumanTaskStore, InvalidTaskTransition, NotAuthorized, TaskNotFound

from .. import mvp_data as md

router = APIRouter()
_TRACE = re.compile(r"^[0-9a-f]{32}$")
_ART = re.compile(r"^([0-9A-Za-z_-]+)/([a-z_]+)/([0-9A-Za-z_.-]+)$")
FILTERS = ("framework", "type", "status", "reviewer", "application", "priority")


def _render(request: Request, name: str, status: int = 200, **ctx) -> HTMLResponse:
    """Render a template with the app's Jinja environment and an optional status code."""
    return request.app.state.templates.TemplateResponse(request, name, ctx, status_code=status)


def _tasks(request: Request) -> HumanTaskStore:
    """Human task store rooted at the app's data dir."""
    return HumanTaskStore(request.app.state.data_dir)


def ref_link(request: Request, ref: str) -> str | None:
    """Resolve a reference string (trace id, artifact path, catalog id or source key) to the dashboard URL that shows it; None if nothing matches."""
    store = request.app.state.reports
    if _TRACE.match(ref) and ref in store.traces():
        return f"/assessments/{ref}"
    m = _ART.match(ref)
    if m and m[1] in store.traces() and m[3] in (store.kinds(m[1]).get(m[2]) or []):
        return f"/artifacts/{m[1]}/{m[2]}/{m[3]}"
    for kind in ("controls", "risks", "patterns", "ras"):
        if any(r["id"] == ref for r in md.registry_rows(kind, store)):
            return f"/registry/{kind}/{ref}"
    if ":" in ref and md.lineage_source(store, ref):
        return f"/lineage/source/{ref}"
    return None


# ---------------------------------------------------------------- 25.1 overview and the old assessments list
@router.get("/", response_class=HTMLResponse)
@router.get("/overview", response_class=HTMLResponse)
def overview(request: Request):
    """Overview page: counts of catalog entries, assessment runs, failing controls and triggered risks."""
    store = request.app.state.reports
    gaps = risks = failing = triggered = 0
    for tr in store.traces():
        cg, rp = store.get(tr, "control_gap"), store.get(tr, "risk_profile")
        if cg:
            gaps += 1
            failing += any(c.get("status") == "FAIL" for c in cg.get("controls") or [])
        if rp:
            risks += 1
            triggered += len(rp.get("risks") or [])
    return _render(request, "overview.html", m={"controls": len(md.catalog_items("controls")), "risks": len(md.catalog_items("risks")),
                                                "patterns": len(md.patterns()), "ras": len(md.ras()), "gap_runs": gaps, "gap_failing": failing,
                                                "risk_runs": risks, "risks_triggered": triggered})

# ---------------------------------------------------------------- 24.5 review queue
@router.get("/review", response_class=HTMLResponse)
def review(request: Request):
    """Human review queue. Filter by framework, type, status, reviewer (matches the claiming actor or the required role), application and priority."""
    q = {k: (request.query_params.get(k) or "").strip() or None for k in FILTERS}
    st = _tasks(request)
    if q["reviewer"]:  # reviewer matches the claiming actor or the required role
        by = {t.task_id: t for t in st.list(framework=q["framework"], task_type=q["type"], status=q["status"], actor=q["reviewer"],
                                            app=q["application"], priority=q["priority"])}
        by.update({t.task_id: t for t in st.list(framework=q["framework"], task_type=q["type"], status=q["status"], role=q["reviewer"],
                                                 app=q["application"], priority=q["priority"])})
        tasks = list(by.values())
    else:
        tasks = st.list(framework=q["framework"], task_type=q["type"], status=q["status"], app=q["application"], priority=q["priority"])
    everything = st.list()
    opts = {"framework": sorted({t.framework for t in everything}), "type": sorted({t.task_type for t in everything}),
            "status": sorted({t.status for t in everything}), "priority": ["LOW", "NORMAL", "HIGH", "CRITICAL"]}
    return _render(request, "review.html", tasks=sorted(tasks, key=lambda t: t.created, reverse=True), q={k: v or "" for k, v in q.items()}, opts=opts)


def _detail(request: Request, task_id: str, message: str = "", ok: bool = True, status: int = 200):
    """Render one review task with its outcome history, links and permitted actions. Raises HTTP 404 for an unknown or invalid task id."""
    st = _tasks(request)
    try:
        t = st.get(task_id)
    except TaskNotFound:
        raise HTTPException(404, "task not found")
    except HumanTaskError:
        raise HTTPException(404, "invalid task id")
    links = [(r, ref_link(request, r)) for r in t.subject_refs]
    trace = t.trace_id or t.context.get("trace_id")
    lineage = [f"/assessments/{trace}/trace"] if trace and trace in request.app.state.reports.traces() else []
    lineage += [l for _, l in links if l and l.startswith("/lineage/")]
    return _render(request, "review_detail.html", status=status, t=t, links=links, lineage=lineage, outcomes=st.outcomes(task_id),
                   allowed=sorted(st._allowed_roles(t)), message=message, ok=ok, actions=t.permitted_actions)


@router.get("/review/{task_id}", response_class=HTMLResponse)
def review_detail(request: Request, task_id: str):
    """Show one human review task with its subject links, history and permitted actions."""
    return _detail(request, task_id)


async def _payload(request: Request) -> tuple[dict, bool]:
    """Parse the request body as JSON or form data. Returns (data, is_json); a malformed or non-object JSON body gives an empty dict."""
    body = await request.body()
    if "json" in (request.headers.get("content-type") or ""):
        try:
            d = json.loads(body or b"{}")
        except ValueError:
            d = {}
        return (d if isinstance(d, dict) else {}), True
    return {k: v[0] for k, v in parse_qs(body.decode("utf-8", "replace")).items()}, False


@router.post("/api/review/{task_id}/act")
async def act(request: Request, task_id: str):
    """Record a reviewer action (claim, approve, reject and so on) on a review task. Needs actor, role, action and rationale. Responds 403 if the role is not allowed, 404 for an unknown task, 409 for an invalid transition and 422 for missing or invalid fields. Returns JSON for JSON requests, otherwise the updated task page."""
    d, is_json = await _payload(request)
    actor, role, action, why = (str(d.get(k) or "").strip() for k in ("actor", "role", "action", "rationale"))
    value = str(d.get("value") or "").strip() or None  # reviewer's chosen value (e.g. a classification); stored as the outcome
    code, msg, out = 200, "recorded", None
    if not (actor and role and action and why):
        code, msg = 422, "actor, role, action and rationale are required"
    else:
        try:
            out = _tasks(request).act(task_id, actor, role, action, why, outcome_artifact_id=value)  # type: ignore[arg-type]
            msg = f"{action} recorded: {out.previous_state} -> {out.resulting_state}"
        except TaskNotFound:
            code, msg = 404, "task not found"
        except NotAuthorized as exc:
            code, msg = 403, str(exc)
        except InvalidTaskTransition as exc:
            code, msg = 409, str(exc)
        except (HumanTaskError, ValueError) as exc:
            code, msg = 422, str(exc)
    if is_json:
        body = {"ok": code == 200, "message": msg}
        if out:
            body.update(previous_state=out.previous_state, resulting_state=out.resulting_state)
        return JSONResponse(body, status_code=code)
    if code == 404:
        raise HTTPException(404, msg)
    return _detail(request, task_id, message=msg, ok=code == 200, status=code)


@router.post("/api/assessments/{trace_id}/resume")
async def resume_assessment(request: Request, trace_id: str):
    """Continue a WAITING_FOR_HUMAN assessment after its review tasks were decided (same path as the CLI `resume`)."""
    from ...exec.coordinator import ResumeError
    d, is_json = await _payload(request)
    mode = str(d.get("mode") or "no-llm")
    cli = str(d.get("cli") or "real")
    if mode not in ("normal", "no-llm", "replay") or cli not in ("real", "replay"):
        raise HTTPException(422, "mode must be normal|no-llm|replay and cli real|replay")
    build = request.app.state.build
    try:
        coord, ex = build(mode, cli=cli)
    except TypeError:                     # a custom build(mode) without the cli keyword
        coord, ex = build(mode)
    try:
        out = coord.resume(trace_id, executor=ex)
    except ResumeError as exc:
        if is_json:
            return JSONResponse({"ok": False, "message": str(exc)}, status_code=409)
        raise HTTPException(409, str(exc))
    if is_json:
        return JSONResponse({"ok": True, "trace_id": out.trace_id, "assessment_status": out.status,
                             "decision": out.decision})
    return RedirectResponse(f"/assessments/{out.trace_id}", status_code=303)


# ---------------------------------------------------------------- MVP one-click approvals (role checks: backlog)
MVP_ACTOR, MVP_ROLE = "dashboard-reviewer", "governance_admin"
MVP_RATIONALE = "approved in dashboard (MVP, no role check)"


@router.post("/api/assessments/{trace_id}/approve")
async def approve_assessment(request: Request, trace_id: str):
    """MVP: approve every open review task of a WAITING_FOR_HUMAN assessment with the value chosen in the report
    (form field ``value__<task_id>``), then resume it. Claim + complete are recorded under a fixed MVP reviewer."""
    from .pages import pending_tasks
    d, is_json = await _payload(request)
    st = _tasks(request)
    done = []
    for t in pending_tasks(request, trace_id):
        value = str(d.get(f"value__{t.task_id}") or "").strip() or None
        allowed = t.context.get("allowed_values") or []
        if allowed and value not in allowed:
            raise HTTPException(422, f"{t.task_id}: choose one of {allowed}")
        try:
            if t.status != "CLAIMED":
                st.act(t.task_id, MVP_ACTOR, MVP_ROLE, "CLAIM", MVP_RATIONALE)
            st.act(t.task_id, MVP_ACTOR, MVP_ROLE, "COMPLETE", MVP_RATIONALE, outcome_artifact_id=value)
        except (InvalidTaskTransition, NotAuthorized, HumanTaskError) as exc:
            raise HTTPException(409, f"{t.task_id}: {exc}")
        done.append(t.task_id)
    return await _resume(request, trace_id, is_json, done)


async def _resume(request: Request, trace_id: str, is_json: bool, approved: list[str]):
    from ...exec.coordinator import ResumeError
    build = request.app.state.build
    try:
        coord, ex = build("no-llm", cli="real")
    except TypeError:
        coord, ex = build("no-llm")
    try:
        out = coord.resume(trace_id, executor=ex)
    except ResumeError as exc:
        if is_json:
            return JSONResponse({"ok": False, "approved": approved, "message": str(exc)}, status_code=409)
        raise HTTPException(409, str(exc))
    if is_json:
        return JSONResponse({"ok": True, "approved": approved, "assessment_status": out.status, "decision": out.decision})
    return RedirectResponse(f"/assessments/{out.trace_id}", status_code=303)


@router.post("/catalogs/{kind}/{item_id:path}/approve")
async def approve_catalog_item(request: Request, kind: str, item_id: str):
    """MVP one-click approval of a catalog record pending human review (direct path; role checks are backlog).

    * controls / risks: DRAFT or IN_REVIEW -> APPROVED in the YAML catalog. For a risk, the click also records the
      reviewer's confirmation of the proposed likelihood and impact (the approval gate requires it).
    * patterns / templates (RA): DRAFT or IN_REVIEW -> APPROVED -> PUBLISHED in the CALM lifecycle registry
      (pattern shape is re-validated on the way).
    Redirects back to the catalog page focused on the item; JSON callers get the new state."""
    d, is_json = await _payload(request)
    try:
        state = _approve(request, kind, item_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        if is_json:
            return JSONResponse({"ok": False, "id": item_id, "message": str(exc)}, status_code=409)
        raise HTTPException(409, str(exc))
    if is_json:
        return JSONResponse({"ok": True, "id": item_id, "status": state})
    nxt = str(d.get("next") or "")
    if re.fullmatch(r"/rules/runs/\d{8}T\d{6}-[0-9a-f]{6}", nxt):   # back to the Generate Rules run (same-site paths only)
        return RedirectResponse(nxt, status_code=303)
    page = "patterns" if kind in ("patterns", "templates", "ras") else kind
    return RedirectResponse(f"/catalogs/{page}?focus={item_id}", status_code=303)


def _approve(request: Request, kind: str, item_id: str) -> str:
    """Apply the MVP approval; LookupError when the item is unknown, ValueError when it cannot be approved."""
    if kind in ("controls", "risks"):
        from rule_authoring import approval
        for path in request.app.state.catalog_paths:
            try:
                e = approval.approve_in_catalog(path, item_id, MVP_ACTOR, confirm_scores=(kind == "risks"))
                return str(e["status"])
            except approval.ApprovalError as exc:
                if "not found" in str(exc):
                    continue
                raise ValueError(str(exc)) from exc
        raise LookupError(f"{item_id} not found in the catalogs")
    if kind in ("patterns", "templates", "ras"):
        from calm_generation import lifecycle as lc
        reg = lc.load(lc.REGISTRY)
        if item_id not in (reg.get("entries") or {}):
            raise LookupError(f"{item_id} is not in the lifecycle registry")
        state = reg["entries"][item_id]["state"]
        path = {"DRAFT": ["IN_REVIEW", "APPROVED", "PUBLISHED"], "IN_REVIEW": ["APPROVED", "PUBLISHED"],
                "APPROVED": ["PUBLISHED"]}.get(state)
        if not path:
            raise ValueError(f"{item_id} is {state}; nothing to approve")
        try:
            pats = None
            if reg["entries"][item_id].get("kind") == "pattern":
                from calm_generation import pattern_library as pl
                pats = pl.load_patterns(pl.PATTERN_DIR)
            for target in path:
                state = lc.transition(item_id, target, by=MVP_ACTOR, role=MVP_ROLE, rationale=MVP_RATIONALE,
                                      path=lc.REGISTRY, patterns=pats)["state"]
            if pats is not None:
                from calm_generation import pattern_builder as pb
                pb.mark_approved(item_id, MVP_ACTOR, patterns_dir=pl.PATTERN_DIR, registry=lc.REGISTRY)
        except Exception as exc:  # noqa: BLE001 - InvalidTransition / PatternInvalid shown to the reviewer
            raise ValueError(f"{item_id}: {exc}") from exc
        return state
    raise LookupError(f"unknown catalog {kind}")


# ---------------------------------------------------------------- MVP: user requirements -> CALM -> assessment
def _tdir():
    from ...units import calm_builder
    return calm_builder.TEMPLATE_DIR


def _published():
    from calm_generation import lifecycle as lc

    from ...units.calm_builder import TEMPLATE_DIR
    return lc.published_templates(TEMPLATE_DIR, lc.REGISTRY)


def _new_app_form(template_id: str = "RA03-LITE"):
    """Template, its text and the blank attributes form; 404 unless the template is PUBLISHED."""
    from calm_generation import attributes as attrs

    from ...units.calm_builder import load_template
    if template_id not in {t["id"] for t in _published()}:
        raise HTTPException(404, f"{template_id} is not a PUBLISHED reference architecture template")
    tpl, text = load_template(template_id, _tdir())
    return tpl, text, attrs.form_for(tpl, text, "PUBLISHED")


@router.get("/applications/new", response_class=HTMLResponse)
def new_application(request: Request):
    """Step 1: describe the application and choose (or let the Decider choose) the reference architecture template."""
    return _render(request, "new_app_start.html", templates=_published(), given={}, errors=[])


@router.post("/applications/new/template", response_class=HTMLResponse)
async def choose_application_template(request: Request):
    """Step 2: resolve the template (user choice, the only published one, or the Decider from the description) and
    show its requirement questions with the step-1 inputs carried over."""
    from ...units.requirements import choose_template
    one = {k: v[0].strip() for k, v in parse_qs((await request.body()).decode("utf-8", "replace")).items() if v}
    templates = _published()
    tid, prov = one.get("template_id") or None, {"source": "user"}
    if tid is None:
        coord, _ = request.app.state.build("no-llm")
        tid, prov, problem = choose_template(templates, one.get("purpose", ""), coord.ctx.decider)
        if problem:
            return _render(request, "new_app_start.html", status=422, templates=templates, given=one, errors=[problem])
    return _step2(request, tid, one, prov)


def _step2(request: Request, tid: str, given: dict, template_choice: dict, errors: list | None = None,
           guidance: list | None = None, status: int = 200) -> HTMLResponse:
    """Render the requirement questions of a template; template fields the questions do not cover go under Advanced."""
    from calm_generation import attributes as attrs, questions as qmod
    _, _, form = _new_app_form(tid)
    qs = qmod.load_questions(tid, _tdir())
    bad = qmod.check_questions(qs, form)
    if bad:
        raise HTTPException(500, f"{tid}.questions.yaml does not match the template: {'; '.join(bad[:5])}")
    q_attrs, q_opts = qmod.covered(qs)
    implied = {k for r in attrs.load_consistency(tid, _tdir()) for k in (r.get("requires") or {})}
    template = next((t for t in _published() if t["id"] == tid), {"id": tid})
    return _render(request, "new_app.html", status=status, form=form, given=given, errors=errors or [], guidance=guidance or [],
                   template_choice=template_choice, template=template, questions=qs,
                   extra_attributes=[a for a in form["attributes"] if a["name"] not in q_attrs | implied],
                   extra_options=[o for o in form["options"] if o["unique_id"] not in q_opts])


def _coerce(a: dict, raw: str):
    if a.get("type") in ("number", "integer"):
        try:
            return int(raw) if a["type"] == "integer" or raw.isdigit() else float(raw)
        except ValueError:
            return raw          # attrs.validate reports the type error
    if a.get("type") == "boolean":
        return raw.lower() in ("true", "yes", "1", "on")
    return raw


@router.post("/applications/new", response_class=HTMLResponse)
async def create_application(request: Request):
    """Generate a CALM model from the answers (requirement questions -> template attributes and options; the Decider
    maps "not sure" descriptions onto an answer), then run the governance assessment and open its report.
    Problems re-render the questions with the reasons."""
    import uuid

    from calm_generation import attributes as attrs, questions as qmod

    from ...units.calm_builder import instantiate
    from ...units.requirements import answer_questions, infer_values
    body = parse_qs((await request.body()).decode("utf-8", "replace"))
    one = {k: v[0].strip() for k, v in body.items() if v}
    tid = one.get("template_id") or "RA03-LITE"
    tpl, text, form = _new_app_form(tid)
    template_choice = {"id": tid, "source": one.get("template_source") or "user",
                       **({"confidence": float(one["template_confidence"])} if one.get("template_confidence") else {})}
    form["app"] = {"id": one.get("app_id", ""), "name": one.get("app_name", "")}
    by_name = {a["name"]: a for a in form["attributes"]}
    form["values"] = {n: _coerce(by_name[n], one[f"value__{n}"]) for n in by_name if one.get(f"value__{n}")}
    for o in form["options"]:
        sel = [s for s in body.get(f"option__{o['unique_id']}", []) if s]
        o["selected"] = (sel[0] if sel else None) if o["type"] == "oneOf" else sel
    coord, ex = request.app.state.build("no-llm")
    gen_trace = f"gen-{uuid.uuid4().hex[:12]}"
    # 1. requirement questions -> attribute values and option choices
    qs = qmod.load_questions(tid, _tdir())
    chosen = {q["id"]: (_coerce(by_name[q["attribute"]], one[f"q__{q['id']}"]) if q.get("type") == "number"
                        else one[f"q__{q['id']}"]) for q in qs if one.get(f"q__{q['id']}")}
    described = {q["id"]: one[f"qd__{q['id']}"] for q in qs if one.get(f"qd__{q['id']}") and not one.get(f"q__{q['id']}")}
    qinf, answers = answer_questions(qs, chosen, described, coord.ctx.decider, trace_id=gen_trace)
    for q in qs:
        if q.get("type") != "number" and q["id"] not in chosen and q["id"] not in described:
            qinf.unresolved.append(f"{q['label']} choose an answer, or describe your case")
    form["values"].update(qinf.values)
    for o in form["options"]:
        if o["unique_id"] in qinf.options:
            o["selected"] = qinf.options[o["unique_id"]]
    purpose = one.get("purpose", "")
    requirements = "\n".join(x for x in (purpose, qmod.summary(qs, answers)) if x)
    # 2. attributes implied by the options; anything still open is inferred from the description
    rules = attrs.load_consistency(form["template"]["id"], _tdir())
    inf = infer_values(form, requirements, coord.ctx.decider, trace_id=gen_trace, rules=rules)
    form["values"].update(inf.values)
    for o in form["options"]:
        if o["unique_id"] in inf.options:
            o["selected"] = inf.options[o["unique_id"]]
    provenance = {**qinf.provenance, **inf.provenance}
    form["requirements"] = {"text": requirements, "answers": answers, "inferred": provenance, "template": template_choice}
    errors = list(qinf.unresolved) + list(inf.unresolved) + [str(e) for e in attrs.consistency_errors(form, rules)]
    guidance: list = []
    r = None
    if not errors:
        r = instantiate(form, template=tpl, template_text=text, template_status="PUBLISHED", calm=coord.ctx.calm,
                        sink=request.app.state.sink, trace_id=gen_trace)
        if r.app_model is None:
            errors, guidance = r.errors, r.guidance
    if errors:
        return _step2(request, tid, one, template_choice, errors, guidance, status=422)
    source = {"app_id": r.app_id, "app_model_ref": f"{gen_trace}/app_model/{r.app_id}", "name": form["app"]["name"],
              "requirements": requirements, "answers": answers, "template": template_choice,
              "inputs": {"values": form["values"], "options": {o["unique_id"]: o["selected"] for o in form["options"]},
                         "inferred": provenance}, "generation": {"trace_id": gen_trace, "status": r.status}}
    out = coord.run(r.app_model, executor=ex, template_id=tid, source=source)
    return RedirectResponse(f"/assessments/{out.trace_id}", status_code=303)


# ---------------------------------------------------------------- 25.2 workbenches
@router.get("/workbench/{name}", response_class=HTMLResponse)
def workbench(request: Request, name: str):
    """Workbench page listing the CLI commands for a framework and its change history."""
    if name not in md.WORKBENCH:
        raise HTTPException(404, "unknown workbench")
    return _render(request, "workbench.html", key=name, wb=md.WORKBENCH[name], history=md.workbench_history(name, request.app.state.reports))


# ---------------------------------------------------------------- 25.3 / 25.6 registry
@router.get("/registry/{kind}", response_class=HTMLResponse)
def registry(request: Request, kind: str):
    """List all entries of one registry kind with their provenance and relationships."""
    if kind not in md.KINDS:
        raise HTTPException(404, "unknown registry kind")
    return _render(request, "registry.html", kind=kind, kinds=md.KINDS, rows=md.registry_rows(kind, request.app.state.reports))


@router.get("/registry/{kind}/{rid:path}", response_class=HTMLResponse)
def registry_detail(request: Request, kind: str, rid: str):
    """Show one registry entry with its raw record and the assessments that used it, flagging those recorded against an older version."""
    if kind not in md.KINDS:
        raise HTTPException(404, "unknown registry kind")
    store = request.app.state.reports
    row = next((r for r in md.registry_rows(kind, store) if r["id"] == rid), None)
    if row is None:
        raise HTTPException(404, "registry entry not found")
    extra = (f"rulesetsha:{row['raw'].get('sha256')}",) if kind == "rulesets" else ()
    used = md.used_by(store, row["token"], row["current"], extra) if row["token"] else []
    lineage = f"/lineage/source/{rid}" if kind == "sources" else None
    return _render(request, "registry_detail.html", kind=kind, row=row, used=used, lineage=lineage,
                   raw=json.dumps(row["raw"], indent=2, default=str, ensure_ascii=False))


# ---------------------------------------------------------------- 25.4 execution view
@router.get("/assessments/{trace}/execution", response_class=HTMLResponse)
def execution(request: Request, trace: str):
    """Execution timeline of one assessment: steps, recorded versions, Decider outcomes and related human tasks."""
    store = request.app.state.reports
    if trace not in store.traces():
        raise HTTPException(404, "assessment not found")
    return _render(request, "execution.html", s=store.summary(trace), x=md.execution(store, trace, _tasks(request).list()))


# ---------------------------------------------------------------- 25.5 lineage (source -> decisions)
@router.get("/lineage/source/{sid:path}", response_class=HTMLResponse)
def lineage_source(request: Request, sid: str):
    """Lineage of one source: the controls, risks, patterns, RA templates and assessments that derive from it."""
    lin = md.lineage_source(request.app.state.reports, sid)
    if lin is None:
        raise HTTPException(404, "source not found")
    return _render(request, "lineage.html", lin=lin)
