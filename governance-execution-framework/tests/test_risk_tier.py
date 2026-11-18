"""Tests for the agent risk-tier classifier and tier-tightened Go/No-Go gate."""

import pytest

from governance_execution.risk_tier import classify_risk, derive_capability_flags


# --------------------------------------------------------------------------- #
# Risk-tier classifier — matches the "Demo scenarios" rubric
# --------------------------------------------------------------------------- #
class TestRiskTierClassifier:
    def test_hr_faq_low(self):
        r = classify_risk({"autonomy": 1, "data_access": 2, "external_connectivity": 1,
                           "action_capability": 1, "decision_impact": 1})
        assert r.score == 6
        assert r.label == "Low"
        assert r.overrides_applied == []

    def test_ticket_triage_high(self):
        r = classify_risk({"autonomy": 3, "data_access": 3, "external_connectivity": 2,
                           "action_capability": 3, "decision_impact": 3})
        assert r.score == 14
        assert r.label == "High"

    def test_trade_recon_critical(self):
        r = classify_risk({"autonomy": 4, "data_access": 4, "external_connectivity": 4,
                           "action_capability": 4, "decision_impact": 3})
        assert r.score == 19
        assert r.label == "Critical"

    def test_tier_thresholds(self):
        assert classify_risk(dict.fromkeys(
            ["autonomy", "data_access", "external_connectivity", "action_capability", "decision_impact"], 1)).label == "Low"      # 5
        assert classify_risk({"autonomy": 2, "data_access": 2, "external_connectivity": 2,
                              "action_capability": 2, "decision_impact": 1}).label == "Moderate"  # 9
        assert classify_risk({"autonomy": 3, "data_access": 3, "external_connectivity": 3,
                              "action_capability": 2, "decision_impact": 2}).label == "High"      # 13
        assert classify_risk({"autonomy": 4, "data_access": 4, "external_connectivity": 3,
                              "action_capability": 3, "decision_impact": 3}).label == "Critical"  # 17


class TestOverrides:
    def test_override1_action4_autonomy3_forces_critical(self):
        # Base score would be Moderate (11) but Override 1 forces Critical.
        r = classify_risk({"autonomy": 3, "data_access": 1, "external_connectivity": 1,
                           "action_capability": 4, "decision_impact": 2})
        assert r.base_label in ("Moderate", "High", "Low")
        assert r.label == "Critical"
        assert any("Override 1" in o for o in r.overrides_applied)

    def test_override2_decision_impact4_forces_at_least_high(self):
        r = classify_risk({"autonomy": 1, "data_access": 1, "external_connectivity": 1,
                           "action_capability": 1, "decision_impact": 4})  # score 8 -> Low base
        assert r.base_label == "Low"
        assert r.tier <= 2  # at least High
        assert any("Override 2" in o for o in r.overrides_applied)

    def test_override2_data4_extconn3(self):
        r = classify_risk({"autonomy": 1, "data_access": 4, "external_connectivity": 3,
                           "action_capability": 1, "decision_impact": 1})  # score 10 Moderate
        assert r.tier <= 2
        assert any("Override 2" in o for o in r.overrides_applied)

    def test_override3_unclassified_data_forces_data4(self):
        r = classify_risk({"autonomy": 1, "data_access": 1, "external_connectivity": 1,
                           "action_capability": 1, "decision_impact": 1,
                           "data_unclassified": True})
        assert r.dimensions["data_access"] == 4
        assert any("Override 3" in o for o in r.overrides_applied)


# --------------------------------------------------------------------------- #
# Option B — derive capability booleans from risk_profile
# --------------------------------------------------------------------------- #
class TestDerivation:
    def test_low_profile_all_false(self):
        flags = derive_capability_flags({"autonomy": 1, "data_access": 2,
                                         "external_connectivity": 1, "action_capability": 1,
                                         "decision_impact": 1})
        assert flags["accesses_sensitive_data"] is False
        assert flags["has_external_connectivity"] is False
        assert flags["has_external_action"] is False
        assert flags["can_perform_high_impact_action"] is False

    def test_high_profile_flags(self):
        flags = derive_capability_flags({"autonomy": 4, "data_access": 4,
                                         "external_connectivity": 4, "action_capability": 4,
                                         "decision_impact": 3})
        assert flags["accesses_sensitive_data"] is True
        assert flags["has_external_connectivity"] is True
        assert flags["can_perform_high_impact_action"] is True
        assert flags["uses_credentials"] is True


# --------------------------------------------------------------------------- #
# Tier-tightened decision
# --------------------------------------------------------------------------- #
