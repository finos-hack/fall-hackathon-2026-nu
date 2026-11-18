"""Agent risk-tier classifier.

Implements the "Scoring rubric" from the design-time GRC session: the AI agent is
scored on FIVE risk dimensions (1 = lowest risk .. 4 = highest), the scores are
summed (range 5..20), and the sum maps to a risk TIER. Three override rules can
then escalate the tier ("the higher-risk result wins").

This classifier measures the agent's INHERENT risk (from its declared
`risk_profile`), independent of whether security controls are present. The
control-gap gate (scoring.py) is a separate computation; the tier only sets the
approval path / scrutiny level and (via scoring.py) tightens the gate.

Dimensions (1..4):
    autonomy, data_access, external_connectivity, action_capability, decision_impact

Tiers (by summed score 5..20):
    Critical 17-20 | High 13-16 | Moderate 9-12 | Low 5-8

Overrides (applied after the score; higher-risk result wins):
    1. action_capability == 4 and autonomy in (3, 4)                 -> Critical
    2. (data_access == 4 and external_connectivity in (3, 4))
       or decision_impact == 4                                       -> at least High
    3. any data source unmapped/unclassified                         -> data_access treated as 4
       (modeled via risk_profile.data_unclassified == true)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


DIMENSIONS = [
    "autonomy",
    "data_access",
    "external_connectivity",
    "action_capability",
    "decision_impact",
]

# Tier number -> (label, min_score, max_score, approval_path, reassessment)
TIER_TABLE = {
    1: ("Critical", 17, 20,
        "Block until all required controls are evidenced; senior human sign-off",
        "Quarterly and on any change"),
    2: ("High", 13, 16,
        "Human reviewer sign-off on the agent recommendation",
        "Every six months and on any change"),
    3: ("Moderate", 9, 12,
        "Automated approval with conditions; sampled human review",
        "Annually and on material change"),
    4: ("Low", 5, 8,
        "Automated approval",
        "Annual attestation"),
}

# Rank for "higher-risk wins" comparisons (lower tier number = higher risk).
_LABEL_TO_TIER = {label: num for num, (label, *_rest) in TIER_TABLE.items()}


@dataclass
class RiskTier:
    """Result of classifying an agent's inherent risk."""

    tier: int                     # 1 (Critical) .. 4 (Low)
    label: str                    # Critical | High | Moderate | Low
    score: int                    # summed 5..20
    base_tier: int                # tier from score alone, before overrides
    base_label: str
    dimensions: Dict[str, int] = field(default_factory=dict)
    overrides_applied: List[str] = field(default_factory=list)
    approval_path: str = ""
    reassessment: str = ""

    def to_dict(self) -> Dict:
        """Return the classification as a plain dict for JSON serialisation."""
        return {
            "tier": self.tier,
            "label": self.label,
            "score": self.score,
            "base_tier": self.base_tier,
            "base_label": self.base_label,
            "dimensions": self.dimensions,
            "overrides_applied": self.overrides_applied,
            "approval_path": self.approval_path,
            "reassessment": self.reassessment,
        }


def _tier_from_score(score: int) -> int:
    """Map a summed score to a tier number (1 Critical .. 4 Low) using TIER_TABLE ranges."""
    for num, (_label, lo, hi, *_rest) in TIER_TABLE.items():
        if lo <= score <= hi:
            return num
    # Scores below 5 are not expected (min 1 per dimension); clamp to Low.
    return 4 if score < 5 else 1


def _clamp(v) -> int:
    """Coerce a dimension score to int within 1..4; missing or non-numeric values count as the lowest risk (1)."""
    try:
        v = int(v)
    except (TypeError, ValueError):
        return 1
    return max(1, min(4, v))


def _escalate(current_tier: int, at_least_tier: int, label: str,
              applied: List[str]) -> int:
    """Higher-risk wins: move to the stricter (lower-number) tier."""
    if at_least_tier < current_tier:
        applied.append(label)
        return at_least_tier
    return current_tier


def classify_risk(risk_profile: Dict) -> RiskTier:
    """Classify an agent's inherent risk tier from its risk_profile.

    Args:
        risk_profile: dict with 1..4 scores for the five dimensions. May also
            carry `data_unclassified: true` (Override 3).

    Returns:
        RiskTier with tier, label, score, applied overrides, and approval path.
    """
    rp = risk_profile or {}
    dims = {d: _clamp(rp.get(d, 1)) for d in DIMENSIONS}

    # Override 3 first: an unmapped/unclassified data source forces data_access = 4.
    overrides: List[str] = []
    if rp.get("data_unclassified") is True and dims["data_access"] != 4:
        dims["data_access"] = 4
        overrides.append("Override 3: unmapped/unclassified data source -> data_access = 4")

    score = sum(dims.values())
    base_tier = _tier_from_score(score)
    tier = base_tier

    # Override 1: action_capability == 4 and autonomy in (3, 4) -> Critical (Tier 1).
    if dims["action_capability"] == 4 and dims["autonomy"] in (3, 4):
        tier = _escalate(tier, 1,
                         "Override 1: action_capability=4 and autonomy>=3 -> Critical",
                         overrides)

    # Override 2: (data_access == 4 and external_connectivity in (3, 4))
    #             or decision_impact == 4 -> at least High (Tier 2).
    if (dims["data_access"] == 4 and dims["external_connectivity"] in (3, 4)) \
            or dims["decision_impact"] == 4:
        tier = _escalate(tier, 2,
                         "Override 2: (data_access=4 and external_connectivity>=3) "
                         "or decision_impact=4 -> at least High",
                         overrides)

    label, _lo, _hi, approval_path, reassessment = TIER_TABLE[tier]
    base_label = TIER_TABLE[base_tier][0]

    return RiskTier(
        tier=tier,
        label=label,
        score=score,
        base_tier=base_tier,
        base_label=base_label,
        dimensions=dims,
        overrides_applied=overrides,
        approval_path=approval_path,
        reassessment=reassessment,
    )


def derive_capability_flags(risk_profile: Dict) -> Dict[str, object]:
    """Option B: derive the control-applicability booleans from risk_profile levels.

    One source of truth (risk_profile 1..4) drives BOTH the tier and the control
    applicability. Thresholds:
      - accesses_sensitive_data       : data_access >= 3 (confidential+) or unclassified
      - has_external_connectivity     : external_connectivity >= 2
      - has_external_action           : action_capability >= 2 (any write/execute) or ext_conn >= 3
      - can_perform_high_impact_action: action_capability == 4 or decision_impact == 4
      - has_tool_access               : action_capability >= 2 or external_connectivity >= 3
      - uses_credentials              : external_connectivity >= 2 (reaches external systems)
    autonomy_level and capabilities are passed through / defaulted.
    """
    rp = risk_profile or {}
    dims = {d: _clamp(rp.get(d, 1)) for d in DIMENSIONS}
    if rp.get("data_unclassified") is True:
        dims["data_access"] = 4

    autonomy_label = {1: "supervised", 2: "human_in_the_loop",
                      3: "human_on_the_loop", 4: "autonomous"}[dims["autonomy"]]

    flags: Dict[str, object] = {
        "accesses_sensitive_data": dims["data_access"] >= 3,
        "has_external_connectivity": dims["external_connectivity"] >= 2,
        "has_external_action": dims["action_capability"] >= 2
                               or dims["external_connectivity"] >= 3,
        "can_perform_high_impact_action": dims["action_capability"] == 4
                                          or dims["decision_impact"] == 4,
        "has_tool_access": dims["action_capability"] >= 2
                           or dims["external_connectivity"] >= 3,
        "uses_credentials": dims["external_connectivity"] >= 2,
        "autonomy_level": autonomy_label,
    }
    return flags
