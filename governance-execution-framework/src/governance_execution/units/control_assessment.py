"""Control Assessment unit: Spectral results -> control statuses and Gap_Level (Req 17).

Join by Rule_Code. PASS means no finding and is labelled design-level evidence only. A control whose
Spectral run returned ERROR is ERROR, never PASS. FAIL carries the catalog remediation.
"""
from __future__ import annotations

from typing import Any

from agip_shared.contracts import ControlGapAssessment, ControlResult, SpectralRun

from ..core import catalogs
from ..core.gap import gap_level

DESIGN_ONLY = "design-level evidence only"
_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _path(p: list[Any]) -> str:
    """Render a Spectral path list as a JSONPath-like string, e.g. ``$.nodes[0].metadata``."""
    return "$" + "".join(f"[{x}]" if str(x).isdigit() else f".{x}" for x in p)


def assess(run: SpectralRun, controls_catalog: dict[str, Any], app_model: dict[str, Any],
           gap_rule: dict[str, Any]) -> ControlGapAssessment:
    """Evaluate every APPROVED control against the Spectral run.

    Each control becomes ERROR (run failed), NOT_APPLICABLE (none of its facts apply), PASS (no matching findings, design-level evidence only) or FAIL (worst configuration severity plus remediation text). Returns the results with the overall gap level.
    """
    facts = catalogs.applicability(app_model)
    by_code: dict[str, list[Any]] = {}
    for r in run.results:
        by_code.setdefault(r.code, []).append(r)
    results: list[ControlResult] = []
    for item in sorted(catalogs.approved(controls_catalog), key=lambda i: i["control_id"]):
        cfgs = item.get("configurations") or []
        codes = sorted({c for cfg in cfgs for c in cfg.get("rule_codes") or []})
        base = {"control_id": item["control_id"], "title": item.get("title"), "rule_codes": codes,
                "mandatory": any(cfg.get("mandatory") for cfg in cfgs), "source": item.get("source") or {}}
        needed = set((item.get("applicability") or {}).get("facts") or [])
        if run.status == "ERROR":
            results.append(ControlResult(status="ERROR", evidence=f"spectral run failed: {run.error}", **base))
            continue
        if needed and not (needed & facts):
            results.append(ControlResult(status="NOT_APPLICABLE", **base))
            continue
        failed = [cfg for cfg in cfgs if any(c in by_code for c in cfg.get("rule_codes") or [])]
        if not failed:
            results.append(ControlResult(status="PASS", evidence=DESIGN_ONLY, **base))
            continue
        worst = max(failed, key=lambda c: _RANK[c["severity"]])
        findings = [{"rule_code": r.code, "path": _path(r.path), "message": r.message}
                    for c in codes for r in by_code.get(c, [])]
        results.append(ControlResult(status="FAIL", gap_contribution=worst["severity"],
                                     remediation=" ".join(c["remediation"] for c in failed), findings=findings, **base))
    level = gap_level([(r.status, r.gap_contribution) for r in results], gap_rule)
    return ControlGapAssessment(controls=results, gap_level=level, gap_rule_version=gap_rule.get("version"))
