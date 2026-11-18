"""Build Pattern and Build Reference Architecture (MVP dashboard workflows).

* Build Pattern: write (or let the Strands agent draft from a description) a structured pattern spec, save it as a
  DRAFT pattern (validated, hash rule), approve it in the CALM Patterns Catalog to publish it.
* Build Reference Architecture: pick published patterns, edit the compose spec, the requirement questions and the
  consistency rules, preview (composer + calm validate -p + question checks), save as a DRAFT RA, approve to publish.
  A published RA is offered by Generate CALM.
"""
from __future__ import annotations

import json
from typing import Any, Optional
from urllib.parse import parse_qs

import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

router = APIRouter()
EXAMPLE_PATTERN = "P13"


def _render(request: Request, name: str, status: int = 200, **ctx) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, name, ctx, status_code=status)


async def _form(request: Request) -> dict[str, list[str]]:
    return parse_qs((await request.body()).decode("utf-8", "replace"), keep_blank_values=True)


def _dirs():
    """Current CALM generation locations (read at call time, so tests can point them elsewhere)."""
    from calm_generation import lifecycle as lc, pattern_library as pl

    from ...units import calm_builder
    return pl.PATTERN_DIR, calm_builder.TEMPLATE_DIR, lc.REGISTRY


def _patterns() -> list[dict[str, Any]]:
    from calm_generation import lifecycle as lc, pattern_library as pl
    pdir, _, reg = _dirs()
    entries = lc.load(reg).get("entries") or {}
    return [{"id": pid, "title": p.get("title"), "description": p.get("description"),
             "version": (p.get("metadata") or {}).get("version"), "state": (entries.get(pid) or {}).get("state")}
            for pid, p in sorted(pl.load_patterns(pdir).items())]


def _dump(spec: Any) -> str:
    return yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=120)


# ---------------------------------------------------------------- Build Pattern
def _catalog_ids() -> tuple[list[str], list[str]]:
    from calm_generation import lifecycle as lc
    c, r = lc._catalog_ids(lc.CATALOGS)
    return sorted(c), sorted(r)


def _pattern_page(request: Request, spec_text: str, status: int = 200, **ctx) -> HTMLResponse:
    controls, risks = _catalog_ids()
    return _render(request, "pattern_build.html", status=status, spec_text=spec_text, patterns=_patterns(),
                   controls=controls, risks=risks, ai=_ai_label(request), **ctx)


@router.get("/patterns/new", response_class=HTMLResponse)
def new_pattern(request: Request, start: str = ""):
    """Pattern editor; ``start=<pattern id>`` copies an existing pattern as the starting point."""
    from calm_generation import pattern_builder as pb, pattern_library as pl
    pdir, _, _ = _dirs()
    pats = pl.load_patterns(pdir)
    if start and start not in pats:
        raise HTTPException(404, "unknown pattern")
    if start:
        spec = pb.spec_of(pats[start])
    else:
        spec = pb.spec_of(pats[EXAMPLE_PATTERN]) if EXAMPLE_PATTERN in pats else {}
        spec.update(pattern_id=pb.next_id(pdir), slug="new-pattern", title="New Pattern", description="<what this building block is>")
    return _pattern_page(request, _dump(spec), start=start, description="")


def _ai_label(request: Request) -> Optional[str]:
    s = request.app.state.settings
    return f"Bedrock {s.bedrock_model_id}" if s.model_provider == "bedrock" and s.bedrock_model_id else None


PATTERN_PROMPT = """You are drafting one reusable CALM 1.2 architecture pattern as a structured spec.
A pattern is a small vendor-neutral building block (no product or cloud names). Return ONE JSON object only, with:
pattern_id, slug (lowercase-kebab), title, description, nodes, relationships, related_controls, related_risks.
Each node: id (lowercase-kebab), type (one of: {types}), name, description, and either metadata or port: true.
metadata maps lower_snake_case field names to a JSON schema: {{"enum": [...]}} for a choice (at least two values),
{{"const": value}} for a fixed value, or {{"type": "string"|"number"|"integer"|"boolean"}} (numbers may add minimum/maximum).
A port is a connection point another component fills (no metadata). Relationships: id, description, from, to (node ids).
Fields that already exist in the library MUST be reused with exactly the same schema (or given a new name):
{library}
New fields get new lower_snake_case names.
related_controls must be chosen only from: {controls}. related_risks only from: {risks}.
Example spec (pattern {example}):
{example_spec}
"""


@router.post("/patterns/new", response_class=HTMLResponse)
async def save_pattern(request: Request):
    """``action=draft``: the Strands agent proposes a spec from the description (shown for editing, not saved).
    ``action=save``: validate and store the spec as a DRAFT pattern (hash rule)."""
    from calm_generation import pattern_builder as pb
    f = {k: v[0] for k, v in (await _form(request)).items()}
    action, spec_text, description = f.get("action", "save"), f.get("spec", ""), f.get("description", "").strip()
    if action == "draft":
        if not description:
            return _pattern_page(request, spec_text, 422, description=description, errors=["describe the pattern first"])
        spec, problems = _ai_pattern(request, description, spec_text)
        return _pattern_page(request, _dump(spec) if spec else spec_text, 200 if spec else 422, description=description,
                             errors=problems, drafted=bool(spec))
    try:
        spec = yaml.safe_load(spec_text)
    except yaml.YAMLError as exc:
        return _pattern_page(request, spec_text, 422, description=description, errors=[f"invalid YAML: {str(exc).splitlines()[0]}"])
    pdir, _, reg = _dirs()
    from calm_generation import lifecycle as lc
    res = pb.save(spec, patterns_dir=pdir, registry=reg, by="dashboard-architect", catalogs=lc.CATALOGS)
    if res["action"] == "rejected":
        return _pattern_page(request, spec_text, 422, description=description, errors=res["errors"])
    if res["action"] == "revised":
        res["stale_ras"] = _ras_using(res["pattern_id"], res.get("version"))
    return _pattern_page(request, spec_text, description=description, saved=res)


def _ras_using(pid: str, version: Any) -> list[str]:
    """Reference architectures composed from an older version of the pattern (they need to be recomposed)."""
    _, tdir, _ = _dirs()
    out = []
    for f in sorted(tdir.glob("*.json")):
        try:
            md = json.loads(f.read_text(encoding="utf-8")).get("metadata") or {}
        except ValueError:
            continue
        if any(p.get("id") == pid and p.get("version") != version for p in md.get("source-patterns") or []):
            out.append(md.get("ra-id") or f.stem)
    return out


def _ai_pattern(request: Request, description: str, spec_text: str) -> tuple[Optional[dict[str, Any]], list[str]]:
    """Strands agent (Bedrock, temperature 0.1) drafts a spec; steering retries until ``check_spec`` passes."""
    if _ai_label(request) is None:
        return None, ["no model configured (MODEL_PROVIDER=bedrock and BEDROCK_MODEL_ID are needed)"]
    from pathlib import Path

    from agip_shared.gateway import ModelGateway, Recorder
    from agip_shared.gateway.model_gateway import ModelUnavailableError, _parse_output
    from agip_shared.gateway.runtime_strands import StrandsRuntime
    from calm_generation import pattern_builder as pb, pattern_library as pl
    pdir, _, _ = _dirs()
    pats = pl.load_patterns(pdir)
    controls, risks = _catalog_ids()
    try:
        current = yaml.safe_load(spec_text) or {}
    except yaml.YAMLError:
        current = {}
    pid = current.get("pattern_id") if isinstance(current, dict) and current.get("pattern_id") else pb.next_id(pdir)

    def check(text: str) -> Optional[str]:
        out = _parse_output(text)
        errs = pb.check_spec(out) if isinstance(out, dict) else ["reply was not a JSON object"]
        if isinstance(out, dict) and not errs:
            errs += pb.field_conflicts({**out, "pattern_id": pid}, pats)
        bad = [c for c in (out.get("related_controls") or []) if c not in controls] + \
              [r for r in (out.get("related_risks") or []) if r not in risks] if isinstance(out, dict) else []
        errs += [f"unknown catalog id {b}" for b in bad]
        return "; ".join(errs[:8]) or None
    check.fingerprint = "pattern-spec-v1"  # type: ignore[attr-defined]
    s = request.app.state.settings
    prompt = PATTERN_PROMPT.format(types=", ".join(pb.NODE_TYPES),
                                   library="\n".join(f"  {f}: {json.dumps(sch)}" for f, (_, sch) in sorted(pb.library_fields(pats, pid).items())),
                                   controls=", ".join(controls), risks=", ".join(risks), example=EXAMPLE_PATTERN,
                                   example_spec=json.dumps(pb.spec_of(pats[EXAMPLE_PATTERN]), indent=1) if EXAMPLE_PATTERN in pats else "{}")
    gw = ModelGateway("bedrock", s.bedrock_model_id, s.aws_region,
                      Recorder(Path(request.app.state.data_dir) / "llm-records"),
                      StrandsRuntime(profile=s.aws_profile, temperature=0.1, steering=check, steering_retries=2))
    try:
        rec = gw.complete("pattern-spec", "v1", {"pattern_id": pid, "description": description}, prompt=prompt, item_id=pid)
    except ModelUnavailableError as exc:
        return None, [f"model unavailable: {exc}"]
    out = rec.output if isinstance(rec.output, dict) else None
    if out is None:
        return None, ["the model did not return a JSON spec"]
    out["pattern_id"] = pid
    problems = check(json.dumps(out))
    return out, ([f"the draft still has problems, fix them before saving: {problems}"] if problems else [])


# ---------------------------------------------------------------- Build Reference Architecture
def _ra_page(request: Request, compose: str, questions: str, consistency: str, status: int = 200, **ctx) -> HTMLResponse:
    return _render(request, "ra_build.html", status=status, compose=compose, questions=questions, consistency=consistency,
                   patterns=_patterns(), **ctx)


QUESTIONS_STUB = """# Requirement questions asked by Generate CALM. Each answer sets template attributes (set) or option choices (options).
questions: []
#  - id: example_question
#    label: How must ... be authorised?
#    answers:
#      choice-a: {label: "...", set: {ATTRIBUTE_NAME: value}}
#      choice-b: {label: "...", options: {option-id: choice-slug}}
#  - {id: limit, label: "What is the largest ...?", type: number, attribute: ATTRIBUTE_NAME}
"""
CONSISTENCY_STUB = """# Attributes that must follow a chosen option (optional).
rules: []
#  - {option: option-id, choice: choice-slug, requires: {ATTRIBUTE_NAME: value}}
"""


@router.get("/architectures/new", response_class=HTMLResponse)
def new_architecture(request: Request, start: str = ""):
    """Step 1: choose patterns (or ``start=<RA id>`` to edit an existing reference architecture)."""
    if start:
        _, tdir, _ = _dirs()
        files = {k: tdir / f"{start}.{k}.yaml" for k in ("compose", "questions", "consistency")}
        if not files["compose"].is_file():
            raise HTTPException(404, "unknown reference architecture")
        read = lambda k: files[k].read_text(encoding="utf-8") if files[k].is_file() else ""  # noqa: E731
        return _ra_page(request, read("compose"), read("questions") or QUESTIONS_STUB, read("consistency") or CONSISTENCY_STUB,
                        start=start)
    _, tdir, _ = _dirs()
    ras = sorted(p.name[:-len(".compose.yaml")] for p in tdir.glob("*.compose.yaml"))
    return _render(request, "ra_start.html", patterns=_patterns(), errors=[], ras=ras)


@router.post("/architectures/generate", response_class=HTMLResponse)
async def generate_architecture(request: Request):
    """The Strands agent composes an RA from a description using only published patterns (Composer + calm validate
    in the loop); the result opens in the editor for review. Nothing is saved until the architect saves it."""
    import re
    from pathlib import Path

    from agip_shared.gateway import ModelGateway, Recorder
    from agip_shared.gateway.runtime_strands import StrandsRuntime
    from calm_generation import ra_agent
    f = await _form(request)
    ra_id = (f.get("ra_id") or [""])[0].strip().upper()
    description = (f.get("description") or [""])[0].strip()
    chosen = [p for p in f.get("patterns", []) if p]
    _, tdir, _ = _dirs()
    ras = sorted(p.name[:-len(".compose.yaml")] for p in tdir.glob("*.compose.yaml"))
    errs = [] if re.fullmatch(r"RA[0-9A-Z][0-9A-Z-]{1,40}", ra_id) else ["the id must look like RA05-CYBER"]
    errs += [] if description else ["describe the application the reference architecture is for"]
    errs += [] if _ai_label(request) else ["no model configured (MODEL_PROVIDER=bedrock and BEDROCK_MODEL_ID are needed)"]
    if errs:
        return _render(request, "ra_start.html", status=422, patterns=_patterns(), errors=errs, ras=ras,
                       given={"ra_id": ra_id, "patterns": chosen, "description": description})
    s = request.app.state.settings
    gw = ModelGateway("bedrock", s.bedrock_model_id, s.aws_region, Recorder(Path(request.app.state.data_dir) / "llm-records"),
                      StrandsRuntime(max_tokens=8192, profile=s.aws_profile, temperature=0.1))
    pdir, tdir, reg = _dirs()
    coord, _ = request.app.state.build("no-llm")
    g = ra_agent.generate(description, ra_id,
                          lambda prompt, inp: gw.complete("ra-spec", "v1", inp, prompt=prompt, item_id=ra_id).output,
                          calm=coord.ctx.calm, pattern_ids=chosen or None, patterns_dir=pdir, registry=reg, templates_dir=tdir)
    return _ra_page(request, g.compose_text or "", g.questions_text or QUESTIONS_STUB, CONSISTENCY_STUB,
                    200 if g.ok else 422, pv=g.preview, generated=g, model=_ai_label(request))


@router.post("/architectures/new", response_class=HTMLResponse)
async def build_architecture(request: Request):
    """``action=preview``: compose and check, nothing written. ``action=save``: preview, then write and record as DRAFT."""
    from calm_generation import ra_builder as rb
    f = {k: v[0] for k, v in (await _form(request)).items()}
    compose, questions, consistency = f.get("compose", ""), f.get("questions", ""), f.get("consistency", "")
    pdir, tdir, reg = _dirs()
    coord, _ = request.app.state.build("no-llm")
    pv = rb.preview(compose, questions, consistency, patterns_dir=pdir, registry=reg, calm=coord.ctx.calm)
    saved = None
    if pv.ok and f.get("action") == "save":
        saved = rb.save(pv, compose, questions, consistency, by="dashboard-architect", templates_dir=tdir, registry=reg)
    return _ra_page(request, compose, questions, consistency, 200 if pv.ok else 422, pv=pv, saved=saved)
