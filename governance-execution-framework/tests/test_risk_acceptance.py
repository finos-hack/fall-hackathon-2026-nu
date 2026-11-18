"""Task 23.8: risk acceptance is role-checked, immutable, expiring and cannot override mandatory gates."""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from governance_execution.core import risk_acceptance as ra

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)
FUT = NOW + timedelta(days=30)


def _rec(reg=None, role="risk_owner", severity="High", fired=(), expiry=FUT, rationale="reviewed"):
    return ra.record("AIGF-RI-018", "app1", "trace1", "alice", role, rationale, "app1 prod", expiry,
                     severity=severity, fired_gates=fired, register=reg, now=NOW)


def test_accept_records_immutable_with_history():
    reg = ra.RiskAcceptanceRegister()
    rec = _rec(reg)
    assert rec.role == "risk_owner" and reg.records == [rec] and reg.history[-1]["event"] == "ACCEPTED"
    with pytest.raises(ValidationError):
        rec.severity = "Low"
    assert ra.is_valid(rec, NOW) and not ra.is_valid(rec, FUT + timedelta(seconds=1))


def test_role_ceilings_and_unknown_role_refused_and_logged():
    reg = ra.RiskAcceptanceRegister()
    with pytest.raises(ra.RiskAcceptanceError):
        _rec(reg, severity="Critical")
    with pytest.raises(ra.RiskAcceptanceError):
        _rec(reg, role="intern")
    assert _rec(reg, role="ciso", severity="Critical").severity == "Critical"
    assert [h["event"] for h in reg.history] == ["REFUSED", "REFUSED", "ACCEPTED"] and len(reg.records) == 1


def test_mandatory_gates_cannot_be_overridden():
    for gid in ("G1-CALM-INVALID", "G2-PAYMENT-AUTH", "G3-UNEVALUABLE"):
        with pytest.raises(ra.RiskAcceptanceError, match="mandatory gate"):
            _rec(role="ciso", fired=[gid])


def test_past_or_naive_expiry_and_empty_rationale_refused():
    with pytest.raises(ra.RiskAcceptanceError):
        _rec(expiry=NOW - timedelta(days=1))
    with pytest.raises(ra.RiskAcceptanceError):
        _rec(expiry=datetime(2030, 1, 1))
    with pytest.raises(ra.RiskAcceptanceError):
        _rec(rationale="  ")
