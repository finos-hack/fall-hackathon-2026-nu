"""Risk Assessment unit: triggered risks, per-risk severity by matrix lookup, profile level (Req 18).

severity = severity_matrix[likelihood][impact] from the versioned Scoring_Profile. Never summed, never
taken from the approval tier. The Agent_Approval_Tier (risk_tier.py) is computed separately for the
approval path only. A mandatory trigger whose attribute is UNMAPPED or UNKNOWN makes the input
INDETERMINATE (``mandatory_trigger = UNEVALUABLE``).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agip_shared.contracts import FactSet, RiskProfile, RiskResult, SpectralRun

from .. import risk_tier
from ..core import catalogs

CONFIG = Path(__file__).resolve().parents[3] / "config" / "scoring_profile.yaml"
LEVELS = ["Low", "Medium", "High", "Critical"]


def load_scoring(path: Path = CONFIG) -> dict[str, Any]:
    """Load the versioned scoring profile (severity matrix) from YAML."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def matrix_lookup(scoring: dict[str, Any], likelihood: int, impact: int) -> str:
    """Severity label: ``severity_matrix[likelihood][impact - 1]`` from the scoring profile."""
    return scoring["severity_matrix"][int(likelihood)][int(impact) - 1]


def _path(p: list[Any]) -> str:
    """Render a Spectral path list as a JSONPath-like string, e.g. ``$.nodes[0].metadata``."""
    return "$" + "".join(f"[{x}]" if str(x).isdigit() else f".{x}" for x in p)


_AUTONOMY = {"supervised": 1, "semi-autonomous": 2, "autonomous": 4}
_PRIVILEGE = {"read-only": 1, "restricted-write": 3, "unrestricted-write": 4}
_ACTION = {"read-only": 1, "reversible-write": 2, "business-write": 3, "production-change": 4}   # rubric action-capability
_IMPACT = {"low": 1, "medium": 2, "high": 3, "financial": 4}
_DATA = {"public": 1, "internal": 2, "confidential": 3, "restricted": 4}


def _agent_autonomy(a: dict[str, Any]) -> int:
    """Rubric autonomy: an approval gate on high-impact actions means "human approves key actions" (2); without it,
    an agent that changes things on its own is at least "human on the loop" (3)."""
    score = _AUTONOMY.get(a.get("autonomy"), 4)
    path = a.get("action_approval_path")
    if path == "via-human-approval":
        return min(score, 2)
    if path == "direct":
        return max(score, 3)
    return score


def _agent_action(a: dict[str, Any]) -> int:
    """Rubric action capability: the higher of the declared action class and the write privilege (an agent declaring
    neither counts as the worst case, 4, as before)."""
    scores = []
    if "privilege" in a or "action_capability" not in a:
        scores.append(_PRIVILEGE.get(a.get("privilege"), 4))
    if "action_capability" in a:
        scores.append(_ACTION.get(a.get("action_capability"), 4))
    return max(scores)


def approval_tier_inputs(app_model: dict[str, Any], facts: FactSet) -> dict[str, Any]:
    """Inputs for risk_tier.classify_risk (1..4 per rubric dimension, worst over agents; scoring-rubric.json)."""
    agents = [n.get("metadata") or {} for n in app_model.get("nodes") or [] if n.get("node-type") == "ai:agent"]
    dbs = [f for f in facts.facts if f.attribute == "data_classification"]
    out = {
        "autonomy": max([_agent_autonomy(a) for a in agents] or [1]),
        "action_capability": max([_agent_action(a) for a in agents] or [1]),
        "decision_impact": max([_IMPACT.get(a.get("decision_impact"), 4) for a in agents] or [1]),
        "data_access": max([_DATA.get(str(f.normalized if f.mapping_status == "INFERRED" else f.raw), 4) for f in dbs] or [1]),
        "external_connectivity": 3 if any((n.get("metadata") or {}).get("exposure") == "external"
                                          for n in app_model.get("nodes") or []) else 1,
    }
    if any(f.mapping_status not in ("MAPPED", "INFERRED") for f in dbs):
        out["data_unclassified"] = True
    return out


def residual_severity(item: dict[str, Any], inherent: str, evidence: list[Any] | None,
                      requirements: list[Any] | None) -> str:
    """Residual = inherent unless a linked control has VALID IMPLEMENTATION/OPERATING evidence that PASSED.

    One ladder step down at most; scores are never subtracted. DESIGN-only or missing evidence never reduces.
    """
    linked = set(item.get("linked_controls") or [])
    if not linked or not evidence or not requirements:
        return inherent
    req_control = {r.requirement_id: r.control_id for r in requirements}
    for e in evidence:
        if (e.maturity in ("IMPLEMENTATION", "OPERATING") and e.evaluation_status == "PASS" and e.validity == "VALID"
                and req_control.get(e.requirement_id) in linked):
            return LEVELS[max(LEVELS.index(inherent) - 1, 0)]
    return inherent


def assess(run: SpectralRun, risks_catalog: dict[str, Any], facts: FactSet, app_model: dict[str, Any],
           scoring: dict[str, Any], evidence: list[Any] | None = None,
           requirements: list[Any] | None = None) -> RiskProfile:
    """Build the RiskProfile: a risk is triggered when any of its rule codes has a finding, severity comes from the matrix, and the profile level is the highest severity (Low if none).

    A failed Spectral run or an unevaluable mandatory trigger sets ``mandatory_trigger`` to UNEVALUABLE.
    """
    by_code: dict[str, list[Any]] = {}
    for r in run.results:
        by_code.setdefault(r.code, []).append(r)
    fact_status = {(f.element_id, f.attribute): f.mapping_status for f in facts.facts}
    triggered: list[RiskResult] = []
    unevaluable: list[str] = []
    for item in sorted(catalogs.approved(risks_catalog), key=lambda i: i["risk_id"]):
        codes = item.get("rule_codes") or []
        if item.get("mandatory_trigger"):
            for code in codes:
                rule = (item.get("spectral_rules") or {}).get(code) or {}
                fld = (rule.get("then") or {}).get("field")
                for _, node in catalogs.targeted_nodes(rule.get("given", ""), app_model):
                    if fact_status.get((node.get("unique-id"), fld), "UNKNOWN") != "MAPPED":
                        unevaluable.append(f"{item['risk_id']}: {node.get('unique-id')}.metadata.{fld} is "
                                           f"{fact_status.get((node.get('unique-id'), fld), 'UNKNOWN')}")
        hits = [r for c in codes for r in by_code.get(c, [])]
        if not hits:
            continue
        sev = matrix_lookup(scoring, item["likelihood"], item["impact"])
        triggered.append(RiskResult(
            risk_id=item["risk_id"], title=item.get("title"), likelihood=item["likelihood"], impact=item["impact"],
            severity=sev, inherent_severity=sev, residual_severity=residual_severity(item, sev, evidence, requirements),
            triggered_by=sorted({r.code for r in hits}), remediation=item.get("remediation"),
            findings=[{"rule_code": r.code, "path": _path(r.path), "message": r.message} for r in hits],
            source=item.get("source") or {}))
    level = max((r.severity for r in triggered), key=LEVELS.index) if triggered else "Low"
    tier = risk_tier.classify_risk(approval_tier_inputs(app_model, facts))
    mandatory = "UNEVALUABLE" if (run.status == "ERROR" or unevaluable) else None
    if run.status == "ERROR":
        unevaluable.append(f"spectral risks run failed: {run.error}")
    return RiskProfile(risks=triggered, profile_level=level, scoring_version=scoring.get("version"),
                       tier=tier.label, tier_detail=tier.to_dict() if hasattr(tier, "to_dict") else {"label": tier.label},
                       mandatory_trigger=mandatory, unevaluable=unevaluable, label=scoring.get("label", ""))
