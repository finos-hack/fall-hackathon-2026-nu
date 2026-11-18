"""Standalone governance CLI (task 23.9).

``python -m governance_execution assess <calm.json> [--mode normal|no-llm|replay] [--data-dir DIR]
[--catalogs DIR --rulesets DIR] [--template ID] [--cli real|replay]``, ``resume <trace>``, ``replay <trace>`` and ``show <trace>``.

It assesses an existing CALM file against the approved catalogs and compiled rulesets. It never imports
``calm_generation`` or ``rule_authoring`` (``--debug-modules`` reports whether either is loaded). The model and
Decider providers come from settings (``MODEL_PROVIDER``, ``DECIDER_PROVIDER``, ``DECIDER_URL``), so a remote
endpoint is configured by environment, not code. ``--mode replay`` uses recordings only.

Output is one JSON object. Exit code: 0 COMPLETED, 3 BLOCKED, 4 WAITING_FOR_HUMAN, 2 FAILED or usage error, 1 for a
replay that differs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from agip_shared.settings import Settings, get_settings

from .core import catalogs as catalogs_mod
from .exec import factory
from .obs.replay import ReplayFailed, replay

EXIT = {"COMPLETED": 0, "BLOCKED": 3, "WAITING_FOR_HUMAN": 4, "FAILED": 2}
FORBIDDEN_MODULES = ("calm_generation", "rule_authoring")

Builder = Callable[..., tuple[Any, Any]]


def _settings(mode: str, decider: Optional[str]) -> Settings:
    """Copy of the global settings adjusted for ``mode``; replay forces fixture Decider and replay model providers."""
    base = get_settings()
    kw: dict[str, Any] = {"data_dir": base.data_dir}
    if mode == "replay":
        kw.update(decider_provider="fixture", model_provider="replay")
    elif decider:
        kw["decider_provider"] = decider
    return base.model_copy(update=kw)


def build_runtime(mode: str, *, data_dir: Optional[Path], catalogs: Optional[Path], rulesets: Optional[Path],
                  cli: str = "real", decider: Optional[str] = None) -> tuple[Any, Any]:
    """Coordinator and executor for the approved catalogs and compiled rulesets (frozen: nothing is regenerated)."""
    s = _settings(mode, decider)
    data = Path(data_dir or s.data_dir)
    coord, ex = factory.build(mode, settings=s, data_dir=data, cli=cli)
    ctx = coord.ctx
    if catalogs is not None:
        ctx.config = {**ctx.config, "controls": catalogs_mod.load("controls", catalogs), "risks": catalogs_mod.load("risks", catalogs)}
    if rulesets is not None:
        ctx.rulesets = {lane: Path(rulesets) / f"{lane}.spectral.yaml" for lane in ("controls", "risks")}
    return coord, ex


def _result(out: Any, coord: Any, debug_modules: bool) -> dict[str, Any]:
    """Flatten a coordinator outcome into the JSON-serialisable result printed by ``assess`` and ``resume``."""
    res: dict[str, Any] = {"trace_id": out.trace_id, "assessment_status": out.status,
                           "validation_status": out.validation_status, "decision": out.decision, "mode": out.mode,
                           "executor": out.executor, "pending_human_tasks": out.pending_human_tasks, "error": out.error,
                           "data_dir": str(coord.ctx.sink.files.data_dir)}
    if debug_modules:
        res["loaded_forbidden_modules"] = sorted(m for m in sys.modules if m.split(".")[0] in FORBIDDEN_MODULES)
    return res


def cmd_assess(args: argparse.Namespace, builder: Builder) -> tuple[dict[str, Any], int]:
    """Run a full assessment of a CALM file; return (result, exit code). An unreadable or non-object file gives FAILED, exit 2."""
    path = Path(args.calm)
    try:
        app = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(app, dict):
            raise ValueError("CALM file must contain a JSON object")
    except (OSError, ValueError) as exc:
        return {"assessment_status": "FAILED", "decision": None, "error": f"cannot read CALM file: {exc}"}, 2
    coord, ex = builder(args.mode, data_dir=args.data_dir, catalogs=args.catalogs, rulesets=args.rulesets, cli=args.cli,
                        decider=args.decider)
    out = coord.run(app, executor=ex, template_id=args.template, source={"app_id": path.stem, "file": path.name})
    return _result(out, coord, args.debug_modules), EXIT.get(out.status, 2)


def cmd_resume(args: argparse.Namespace, builder: Builder) -> tuple[dict[str, Any], int]:
    """Continue a WAITING_FOR_HUMAN assessment after its HumanTasks were decided (task 24.3)."""
    from .exec.coordinator import ResumeError
    coord, ex = builder(args.mode, data_dir=args.data_dir, catalogs=args.catalogs, rulesets=args.rulesets, cli=args.cli,
                        decider=None)
    try:
        out = coord.resume(args.trace, executor=ex)
    except ResumeError as exc:
        return {"trace_id": args.trace, "assessment_status": "FAILED", "decision": None, "error": str(exc)}, 2
    return _result(out, coord, False), EXIT.get(out.status, 2)


def cmd_replay(args: argparse.Namespace, builder: Builder) -> tuple[dict[str, Any], int]:
    """Re-run a stored trace from recordings and compare decisions; exit 0 if identical, 1 if different, 2 if replay fails."""
    coord, ex = builder("replay", data_dir=args.data_dir, catalogs=None, rulesets=None, cli=args.cli, decider=None)
    llm_records = coord.ctx.sink.files.data_dir / "llm-records"
    if coord.ctx.gateway is not None and llm_records.is_dir():   # outputs recorded by a normal run in this data dir
        coord.ctx.gateway.recorder.root = llm_records
    try:
        rep = replay(args.trace, coord, ex)
    except ReplayFailed as exc:
        return {"original_trace": args.trace, "error": str(exc), "identical": False}, 2
    return {"original_trace": rep.original_trace, "replay_trace": rep.replay_trace, "identical": rep.identical,
            "decision_original": rep.decision_original, "decision_replay": rep.decision_replay,
            "differences": rep.differences}, (0 if rep.identical else 1)


def cmd_show(args: argparse.Namespace, builder: Builder) -> tuple[dict[str, Any], int]:
    """Summarise a stored assessment from its artifact files without running anything; exit 2 if the trace is unknown."""
    from .dashboard.data import ReportStore   # file reader only; no web framework import
    s = _settings("no-llm", None)
    store = ReportStore(args.data_dir or s.data_dir)
    if args.trace not in store.traces():
        return {"trace_id": args.trace, "error": "assessment not found"}, 2
    versions = store.get(args.trace, "versions") or {}
    record = store.get(args.trace, "assessment_record") or {}
    decision = store.get(args.trace, "decision")
    return {"trace_id": args.trace, "assessment_status": record.get("assessment_status") or versions.get("assessment_status"),
            "validation_status": record.get("validation_status") or versions.get("validation_status"),
            "decision": record.get("decision"), "mode": record.get("mode"), "error": record.get("error"),
            "pending_human_tasks": record.get("pending_human_tasks") or [],
            "gates_fired": [g["id"] for g in (decision or {}).get("gates_evaluated", []) if g.get("fired")],
            "steps": (store.get(args.trace, "trace") or {}).get("steps", []),
            "artifacts": store.kinds(args.trace), "versions": versions}, 0


def parser() -> argparse.ArgumentParser:
    """Build the argparse parser with the assess, resume, replay and show subcommands."""
    ap = argparse.ArgumentParser(prog="governance_execution", description="Standalone governance assessment CLI")
    sub = ap.add_subparsers(dest="command", required=True)
    a = sub.add_parser("assess", help="assess a CALM file")
    a.add_argument("calm", help="path to the CALM architecture JSON")
    a.add_argument("--mode", choices=("normal", "no-llm", "replay"), default="normal")
    a.add_argument("--catalogs", type=Path, default=None, help="approved catalogs directory (default: repo catalogs)")
    a.add_argument("--rulesets", type=Path, default=None, help="compiled rulesets directory (default: repo rulesets)")
    a.add_argument("--template", default=None, help="CALM pattern/template id to validate against (optional)")
    a.add_argument("--decider", choices=("http", "fixture"), default=None, help="override DECIDER_PROVIDER")
    a.add_argument("--debug-modules", action="store_true", help="report whether calm_generation or rule_authoring is loaded")
    u = sub.add_parser("resume", help="resume a WAITING_FOR_HUMAN assessment after human review")
    u.add_argument("trace")
    u.add_argument("--mode", choices=("normal", "no-llm", "replay"), default="no-llm")
    u.add_argument("--catalogs", type=Path, default=None)
    u.add_argument("--rulesets", type=Path, default=None)
    r = sub.add_parser("replay", help="replay a stored assessment from recordings")
    r.add_argument("trace")
    s = sub.add_parser("show", help="show a stored assessment")
    s.add_argument("trace")
    for p in (a, u, r, s):
        p.add_argument("--data-dir", type=Path, default=None)
    for p in (a, u, r):
        p.add_argument("--cli", choices=("real", "replay"), default="real", help="calm/spectral: run the tools or replay recorded outputs")
    return ap


def main(argv: Optional[list[str]] = None, *, builder: Builder = build_runtime) -> int:
    """Parse ``argv``, run the chosen subcommand, print its result as JSON and return the exit code.

    ``builder`` is injectable so tests can supply a stub runtime.
    """
    args = parser().parse_args(argv)
    fn = {"assess": cmd_assess, "resume": cmd_resume, "replay": cmd_replay, "show": cmd_show}[args.command]
    result, code = fn(args, builder)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
