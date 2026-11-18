"""Build a reference architecture (RA) template from published patterns ("Build Reference Architecture").

Inputs, all YAML text edited by the architect:

* compose spec (``templates/<ra>.compose.yaml``, see ``composer``): patterns, components, bind, relationships, options;
* requirement questions (``<ra>.questions.yaml``, see ``questions``): what Generate CALM asks the user;
* consistency rules (``<ra>.consistency.yaml``, optional): attributes that follow an option.

``preview`` composes without writing anything and reports every problem (YAML, composition conflicts, CALM
``validate -p`` of the template, questions/consistency against the template's form, fields no question covers).
``save`` writes the four files and records the composition as a DRAFT RA in the lifecycle registry; unchanged
content is not rewritten, changed content is ra-version + 1 (hash rule). Approval publishes it (lifecycle), and only
PUBLISHED templates are offered by Generate CALM. Patterns are reused as they are; the Composer never adds metadata.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from agip_shared import versioned_write as vw
from agip_shared.hashing import sha256_hex

from . import attributes as attrs
from . import composer
from . import lifecycle as lc
from . import pattern_library as pl
from . import questions as qmod

_RA = re.compile(r"^RA[0-9A-Z][0-9A-Z-]{1,40}$")


@dataclass
class Preview:
    ok: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    spec: Optional[dict[str, Any]] = None
    template: Optional[dict[str, Any]] = None
    text: str = ""
    form: Optional[dict[str, Any]] = None
    questions: list[dict[str, Any]] = field(default_factory=list)
    rules: list[dict[str, Any]] = field(default_factory=list)
    version: int = 1


def _yaml(text: str, what: str, errs: list[str]) -> Any:
    try:
        return yaml.safe_load(text or "") if (text or "").strip() else None
    except yaml.YAMLError as exc:
        errs.append(f"{what}: invalid YAML ({str(exc).splitlines()[0]})")
        return None


def preview(compose_text: str, questions_text: str = "", consistency_text: str = "", *,
            patterns_dir: Path = pl.PATTERN_DIR, registry: Path = lc.REGISTRY, calm: Any = None) -> Preview:
    """Compose and check everything; nothing is written."""
    pv = Preview()
    spec = _yaml(compose_text, "compose spec", pv.errors)
    qdoc = _yaml(questions_text, "questions", pv.errors)
    cdoc = _yaml(consistency_text, "consistency rules", pv.errors)
    if pv.errors:
        return pv
    if not isinstance(spec, dict):
        pv.errors.append("compose spec must be a mapping")
        return pv
    rid = str(spec.get("ra_id") or "")
    if not _RA.match(rid):
        pv.errors.append("ra_id must look like RA05-CYBER (upper case, starts with RA)")
        return pv
    prev = (lc.load(registry).get("entries") or {}).get(rid)
    if prev is not None and prev.get("kind") != "ra":
        pv.errors.append(f"{rid} is already used by a {prev.get('kind')}")
        return pv
    pats = pl.load_patterns(patterns_dir)
    try:
        lc.composable_patterns(spec, pats, registry)
    except lc.NotComposable as exc:
        pv.errors.append(str(exc))
        return pv
    spec = {**spec, "version": int(spec.get("version") or 1)}
    try:
        res = composer.compose(pats, spec)
    except (KeyError, TypeError, ValueError) as exc:
        pv.errors.append(f"compose spec is incomplete: {type(exc).__name__} {exc}")
        return pv
    pv.errors += [str(c) for c in res.conflicts] + list(res.errors)
    if pv.errors:
        return pv
    # hash rule: an identical composition keeps its version, a changed one is max + 1
    if prev and prev.get("composed_sha256") != sha256_hex(res.text):
        spec["version"] = max([int(v["version"]) for v in prev.get("versions") or []] + [int(prev["version"])]) + 1
        res = composer.compose(pats, spec)
    elif prev:
        spec["version"] = int(prev["version"])
        res = composer.compose(pats, spec)
    pv.spec, pv.template, pv.text, pv.version = spec, res.template, res.text, int(spec["version"])
    if calm is not None and hasattr(calm, "validate_pattern"):
        v = calm.validate_pattern(res.template)
        if getattr(v, "status", "VALID") != "VALID":
            pv.errors += [f"calm validate -p: {getattr(e, 'message', e)}" for e in (getattr(v, "errors", None) or [getattr(v, "error", "invalid")])]
    pv.form = attrs.form_for(res.template, res.text, "PUBLISHED")       # the form Generate CALM will show
    pv.questions = list((qdoc or {}).get("questions") or []) if isinstance(qdoc, dict) else []
    if qdoc is not None and not isinstance(qdoc, dict):
        pv.errors.append("questions must be a mapping with 'questions:'")
    pv.errors += [f"questions: {e}" for e in qmod.check_questions(pv.questions, pv.form)]
    pv.rules = list((cdoc or {}).get("rules") or []) if isinstance(cdoc, dict) else []
    names = {a["name"]: a for a in pv.form["attributes"]}
    opts = {o["unique_id"]: o for o in pv.form["options"]}
    for r in pv.rules:
        o = opts.get(r.get("option"))
        if o is None or r.get("choice") not in o["choices"]:
            pv.errors.append(f"consistency: {r.get('option')} = {r.get('choice')} is not an option choice of the template")
        for k, v in (r.get("requires") or {}).items():
            a = names.get(k)
            if a is None or (a.get("type") == "enum" and v not in a["allowed"]):
                pv.errors.append(f"consistency: {k} = {v!r} is not a template attribute value")
    q_attrs, q_opts = qmod.covered(pv.questions)
    implied = {k for r in pv.rules for k in (r.get("requires") or {})}
    open_attrs = [a["name"] for a in pv.form["attributes"] if a["name"] not in q_attrs | implied]
    open_opts = [o["unique_id"] for o in pv.form["options"] if o["unique_id"] not in q_opts]
    if open_attrs or open_opts:
        pv.warnings.append("not covered by any question (Generate CALM shows them under Advanced): "
                           + ", ".join(open_attrs + open_opts))
    pv.ok = not pv.errors
    return pv


def save(pv: Preview, compose_text: str, questions_text: str, consistency_text: str, *, by: str = "dashboard",
         templates_dir: Optional[Path] = None, registry: Path = lc.REGISTRY) -> dict[str, Any]:
    """Write the RA files and record the composition as DRAFT (call after a successful ``preview``)."""
    if not pv.ok or pv.spec is None:
        return {"action": "rejected", "errors": pv.errors or ["preview first"]}
    tdir = Path(templates_dir or pl.FRAMEWORK_ROOT / "templates")
    rid = pv.spec["ra_id"]
    prev = (lc.load(registry).get("entries") or {}).get(rid)
    unchanged = bool(prev and prev.get("composed_sha256") == sha256_hex(pv.text))
    spec_text = re.sub(r"(?m)^version:.*$", f"version: {pv.version}", compose_text, count=1) \
        if re.search(r"(?m)^version:", compose_text) else f"version: {pv.version}\n{compose_text}"
    files = {f"{rid}.json": pv.text, f"{rid}.compose.yaml": spec_text}
    if questions_text.strip():
        files[f"{rid}.questions.yaml"] = questions_text
    if consistency_text.strip():
        files[f"{rid}.consistency.yaml"] = consistency_text
    for name, text in files.items():
        p = tdir / name
        vw.write(p, text, content_hash=sha256_hex(text), version=vw.version_for(p, sha256_hex(text), initial=pv.version))
    e = lc.record_composition(rid, pv.version, pv.text, pv.template, by=by, path=registry)
    return {"ra_id": rid, "version": pv.version, "state": e["state"], "errors": [],
            "action": "unchanged" if unchanged else ("created" if prev is None else "revised")}
