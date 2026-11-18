"""Run the controls and risks rulesets in parallel through the Spectral_Adapter (Req 16.1, 16.5)."""
from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

from agip_shared.contracts import SpectralRun

RULESET_DIR = Path(__file__).resolve().parents[4] / "rule-authoring-framework" / "rulesets"
LANES = ("controls", "risks")


def raw_record(adapter: Any) -> dict[str, Any]:
    """Raw evidence of one lint call. Temp-file paths are removed so identical runs give identical artifacts."""
    rec = adapter.last
    if rec is None:
        return {}
    results: Any = None
    if rec.parsed is not None:
        results = [{k: v for k, v in r.items() if k != "source"} for r in rec.parsed]
    return {"tool": "spectral", "version": rec.version, "exit_code": rec.exit_code,
            "ruleset": Path(rec.args[3]).name if len(rec.args) > 3 else None,
            "results": results, "stderr": (rec.raw_stderr or "")[-2000:] if rec.parsed is None else ""}


def run_lanes(adapter: Any, app_model: dict[str, Any], rulesets: Optional[dict[str, Path]] = None,
              sink: Any = None, trace_id: str = "") -> dict[str, SpectralRun]:
    """Lint the app model with the controls and risks rulesets in parallel (two threads) and return the SpectralRun per lane."""
    rulesets = rulesets or {lane: RULESET_DIR / f"{lane}.spectral.yaml" for lane in LANES}
    text = json.dumps(app_model, sort_keys=True)   # serialise once; both lanes lint the same text

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="spectral") as pool:
        done = list(pool.map(lambda n: (n, run_one(adapter, text, n, rulesets[n], sink, trace_id)), LANES))
    return dict(done)


def run_one(adapter: Any, app: Any, lane: str, ruleset: Optional[Path] = None, sink: Any = None,
            trace_id: str = "") -> SpectralRun:
    """One lane. Uses a copy of the adapter so parallel lanes keep separate ``last`` records."""
    a = copy.copy(adapter)
    text = app if isinstance(app, str) else json.dumps(app, sort_keys=True)
    run = a.lint(text, str(ruleset or RULESET_DIR / f"{lane}.spectral.yaml"))
    if sink is not None:
        raw_a = sink.put(trace_id, f"spectral_{lane}_raw", "run", raw_record(a))
        parsed_a = sink.put(trace_id, f"spectral_{lane}_parsed", "run", json.loads(run.model_dump_json()))
        run = run.model_copy(update={"raw_artifact_id": raw_a.id, "parsed_artifact_id": parsed_a.id})
    return run
