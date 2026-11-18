"""Standalone CLI: ``python -m calm_generation <command>``. Needs no governance execution package."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

import yaml

from agip_shared.contracts import InvalidTransition
from agip_shared.hashing import canonical_json, sha256_hex

from . import attributes as attrs
from . import composer, lifecycle as lc, pattern_library as pl
from .calm_cli import CalmUnavailable, RealCalm
from .placeholders import fill

ROOT = pl.FRAMEWORK_ROOT
TEMPLATES = ROOT / "templates"
STEPS = {"submit": "IN_REVIEW", "approve": "APPROVED", "publish": "PUBLISHED", "reject": "REJECTED",
         "deprecate": "DEPRECATED"}


def _p(*a: Any) -> None:
    """Print to stdout."""
    print(*a)


def _err(*a: Any) -> int:
    """Print to stderr and return exit code 1, so commands can ``return _err(...)``."""
    print(*a, file=sys.stderr)
    return 1


def cmd_patterns(a, ctx) -> int:
    """List library patterns with version and lifecycle state (UNREGISTERED if absent from the registry)."""
    reg = lc.load(ctx["registry"])["entries"]
    for pid, p in pl.load_patterns().items():
        _p(f"{pid}\tv{p['metadata']['version']}\t{reg.get(pid, {}).get('state', 'UNREGISTERED')}\t{p.get('title', '')}")
    return 0


def cmd_versions(a, ctx) -> int:
    """List registry entries; for RA templates every recorded version, older ones shown as SUPERSEDED."""
    for key, e in sorted(lc.load(ctx["registry"])["entries"].items()):
        if e["kind"] == "ra":
            for v in e["versions"]:
                _p(f"{key}\tv{v['version']}\t{e['state'] if v['version'] == e['version'] else 'SUPERSEDED'}\t{v['composed_sha256']}")
        else:
            _p(f"{key}\tv{e['version']}\t{e['state']}\t{e['sha256']}")
    return 0


def cmd_compose(a, ctx) -> int:
    """Compose a template from a spec after checking the patterns are composable, record it in the registry and write the template file. Returns 1 on any refusal."""
    spec = composer.load_spec(a.spec)
    pats = pl.load_patterns()
    try:
        lc.composable_patterns(spec, pats, ctx["registry"])
    except lc.NotComposable as e:
        return _err(f"not composable: {e}")
    res = composer.compose(pats, spec)
    for c in res.conflicts:
        print(c, file=sys.stderr)
    for e in res.errors:
        print(f"error: {e}", file=sys.stderr)
    if not res.ok:
        return 1
    out = Path(a.out) if a.out else TEMPLATES / f"{spec['ra_id']}.json"
    try:
        lc.record_composition(spec["ra_id"], int(spec["version"]), res.text, res.template, by=a.by or "cli", path=ctx["registry"])
    except ValueError as e:
        return _err(str(e))
    out.write_text(res.text, encoding="utf-8")
    _p(f"{spec['ra_id']} v{spec['version']} sha256={sha256_hex(res.text)}")
    return 0


def cmd_step(a, ctx) -> int:
    """Apply one lifecycle transition (submit/approve/publish/reject/deprecate); rejected transitions are reported as ``refused`` with exit 1."""
    target = STEPS[a.command]
    try:
        e = lc.transition(a.id, target, by=a.by, role=a.role, rationale=a.rationale, path=ctx["registry"])
    except (InvalidTransition, lc.PatternInvalid, ValueError, KeyError) as ex:
        return _err(f"refused: {ex}")
    _p(f"{a.id} -> {e['state']}")
    return 0


def _template(ra_id: str, reg_path: Path):
    """Load the template JSON for ``ra_id`` and return ``(parsed, raw text, lifecycle state)``; the raw text is kept for hashing."""
    state = lc.state_of(ra_id, reg_path)
    text = (TEMPLATES / f"{ra_id}.json").read_text(encoding="utf-8")
    return json.loads(text), text, state


def cmd_form(a, ctx) -> int:
    """Write (or print) the attributes form for a PUBLISHED template; refuses DRAFT templates."""
    try:
        tpl, text, state = _template(a.template, ctx["registry"])
        form = attrs.form_for(tpl, text, state)
    except (attrs.TemplateNotPublished, KeyError, OSError) as e:
        return _err(f"refused: {e}")
    out = yaml.safe_dump(form, sort_keys=False, allow_unicode=True)
    if a.out:
        Path(a.out).write_text(out, encoding="utf-8")
    else:
        sys.stdout.write(out)
    return 0


def cmd_instantiate(a, ctx) -> int:
    """Validate a filled form, run ``calm generate``, fill placeholders and ``calm validate`` the result; non-zero exit unless the App_Model is VALID."""
    form = yaml.safe_load(Path(a.form).read_text(encoding="utf-8"))
    try:
        tpl, text, state = _template(form["template"]["id"], ctx["registry"])
        attrs.form_for(tpl, text, state)  # refuses unless PUBLISHED
    except (attrs.TemplateNotPublished, KeyError, OSError) as e:
        return _err(f"refused: {e}")
    errs = attrs.validate(form, tpl, text)
    if errs:
        return _err("attributes rejected:\n" + "\n".join(f"  {e}" for e in errs))
    try:
        calm = ctx.get("calm") or RealCalm()
    except CalmUnavailable as e:
        return _err(f"error: {e}")
    gen = calm.generate(tpl, attrs.option_choices(form))
    if gen.status != "OK":
        return _err(f"calm generate: {gen.error}")
    filled = fill(gen.model, form, tpl)
    if filled.model is None:
        return _err("leftover placeholders:\n" + "\n".join(f"  {l}" for l in filled.leftovers))
    v = calm.validate(filled.model, tpl)
    sha = sha256_hex(canonical_json(filled.model))
    if a.out:
        Path(a.out).write_text(json.dumps(filled.model, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _p(f"{v.status} app={form['app']['id']} sha256={sha}")
    if v.status != "VALID":
        for e in v.errors:
            print(f"  {e.path}: {e.message}", file=sys.stderr)
        if v.error:
            print(f"  {v.error}", file=sys.stderr)
        return 1
    return 0


def cmd_validate(a, ctx) -> int:
    """Validate a pattern statically, or an architecture with ``calm validate`` against the chosen template pattern."""
    doc = json.loads(Path(a.file).read_text(encoding="utf-8"))
    if "properties" in doc:  # a pattern
        errs = lc.validate_pattern_shape(doc)
        for e in errs:
            print(f"  {e}", file=sys.stderr)
        _p("INVALID" if errs else "VALID (static pattern checks)")
        return 1 if errs else 0
    try:
        calm = ctx.get("calm") or RealCalm()
    except CalmUnavailable as e:
        return _err(f"error: {e}")
    pattern = None
    if a.template:   # `calm validate -a` alone fails on CALM 1.2 instances; validate against the template pattern
        try:
            pattern = _template(a.template, ctx["registry"])[0]
        except (KeyError, OSError) as e:
            return _err(f"unknown template {a.template}: {e}")
    v = calm.validate(doc, pattern)
    _p(v.status)
    for e in v.errors:
        print(f"  {e.path}: {e.message}", file=sys.stderr)
    return 0 if v.status == "VALID" else 1


def build() -> argparse.ArgumentParser:
    """Build the argparse parser with one sub-command per ``cmd_*`` handler (bound through ``fn``)."""
    ap = argparse.ArgumentParser(prog="calm_generation")
    ap.add_argument("--registry", default=str(lc.REGISTRY))
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("patterns").set_defaults(fn=cmd_patterns)
    sub.add_parser("versions").set_defaults(fn=cmd_versions)
    c = sub.add_parser("compose")
    c.add_argument("spec", nargs="?", default=str(TEMPLATES / "RA03-LITE.compose.yaml"))
    c.add_argument("--out")
    c.add_argument("--by")
    c.set_defaults(fn=cmd_compose)
    for name in STEPS:
        s = sub.add_parser(name)
        s.add_argument("id")
        for f in ("by", "role", "rationale"):
            s.add_argument(f"--{f}", required=True)
        s.set_defaults(fn=cmd_step)
    f = sub.add_parser("form")
    f.add_argument("template")
    f.add_argument("--out")
    f.set_defaults(fn=cmd_form)
    i = sub.add_parser("instantiate")
    i.add_argument("--form", required=True)
    i.add_argument("--out")
    i.set_defaults(fn=cmd_instantiate)
    v = sub.add_parser("validate")
    v.add_argument("file")
    v.add_argument("--template", default="RA03-LITE", help="pattern/template id to validate against (default RA03-LITE)")
    v.set_defaults(fn=cmd_validate)
    return ap


def main(argv: Optional[list[str]] = None, calm: Any = None) -> int:
    """Parse ``argv`` and run the command. ``calm`` may inject a fake CALM adapter (tests); returns the process exit code."""
    a = build().parse_args(argv)
    return a.fn(a, {"registry": Path(a.registry), "calm": calm})
