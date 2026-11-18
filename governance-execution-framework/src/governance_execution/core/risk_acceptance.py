"""Risk acceptance: an immutable, role-checked, expiring human record with an append-only audit history.

An acceptance never changes severity, gates or the decision. It cannot override a mandatory gate (G1/G2/G3 in
config/gates.yaml): accepting a risk that fired one raises. Roles and severity ceilings come from config/roles.yaml.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field

from . import gates as gates_mod

ROLES = Path(__file__).resolve().parents[3] / "config" / "roles.yaml"
LEVELS = ["Low", "Medium", "High", "Critical"]


class RiskAcceptanceError(ValueError):
    """Refused: unauthorized role, bad input, expired, or a mandatory gate fired."""


class RiskAcceptanceRecord(BaseModel):
    """Immutable record of one accepted risk: who, in which role, why, for what scope and until when."""
    model_config = ConfigDict(frozen=True)

    acceptance_id: str
    risk_ref: str
    app_ref: str
    assessment_ref: str
    severity: str
    actor: str
    role: str
    rationale: str = Field(min_length=1)
    scope: str
    created: datetime
    expiry: datetime


class RiskAcceptanceRegister:
    """Append-only history: accepted records and refusals."""

    def __init__(self) -> None:
        """Start with an empty history and no records."""
        self._history: list[dict[str, Any]] = []
        self.records: list[RiskAcceptanceRecord] = []

    @property
    def history(self) -> tuple[dict[str, Any], ...]:
        """Copy of the audit log; entries are appended by ``_log`` and never removed."""
        return tuple(dict(h) for h in self._history)

    def _log(self, event: str, **kw: Any) -> None:
        """Append a timestamped (UTC) event to the audit history."""
        self._history.append({"event": event, "at": datetime.now(timezone.utc).isoformat(), **kw})


def load_roles(path: Path = ROLES) -> dict[str, Any]:
    """Load the roles YAML (default ``config/roles.yaml``) that defines who may accept risk and up to which severity."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


ALWAYS_MANDATORY = {"G1-CALM-INVALID"}  # invalid CALM blocks the assessment (task 23.7); never acceptable


def mandatory_gate_ids(gates: Optional[dict[str, Any]] = None) -> set[str]:
    """IDs of all gates in ``gates`` (loaded from config if None) plus ALWAYS_MANDATORY."""
    return ALWAYS_MANDATORY | {g["id"] for g in (gates or gates_mod.load_gates())["order"]}


def fired_gate_ids(gates_evaluated: Iterable[dict[str, Any]]) -> list[str]:
    """IDs of gates marked ``fired`` in an evaluated-gates record."""
    return [g["id"] for g in gates_evaluated if g.get("fired")]


def is_valid(rec: RiskAcceptanceRecord, now: Optional[datetime] = None) -> bool:
    """True while ``now`` (default: current UTC time) is before the record's expiry."""
    return (now or datetime.now(timezone.utc)) < rec.expiry


def record(risk_ref: str, app_ref: str, assessment_ref: str, actor: str, role: str, rationale: str, scope: str,
           expiry: datetime, *, severity: str, fired_gates: Iterable[str] = (),
           register: Optional[RiskAcceptanceRegister] = None, roles: Optional[dict[str, Any]] = None,
           gates: Optional[dict[str, Any]] = None, now: Optional[datetime] = None) -> RiskAcceptanceRecord:
    """Validate and store a risk acceptance. Raises RiskAcceptanceError (and logs REFUSED) for unauthorized role, unknown or too-high severity, a fired mandatory gate, blank rationale, or a non-aware or past expiry."""
    reg = register if register is not None else RiskAcceptanceRegister()
    now = now or datetime.now(timezone.utc)
    ctx = {"risk_ref": risk_ref, "app_ref": app_ref, "assessment_ref": assessment_ref, "actor": actor, "role": role}

    def refuse(reason: str) -> RiskAcceptanceError:
        """Log a REFUSED event in the register and return the error for the caller to raise."""
        reg._log("REFUSED", reason=reason, **ctx)
        return RiskAcceptanceError(reason)

    cfg = ((roles or load_roles()).get("risk_acceptance") or {}).get(role)
    if cfg is None:
        raise refuse(f"role {role!r} is not authorized to accept risk")
    if severity not in LEVELS:
        raise refuse(f"unknown severity {severity!r}")
    if LEVELS.index(severity) > LEVELS.index(cfg["max_severity"]):
        raise refuse(f"role {role!r} may accept up to {cfg['max_severity']}, not {severity}")
    hit = sorted(set(fired_gates) & mandatory_gate_ids(gates))
    if hit:
        raise refuse(f"mandatory gate(s) {hit} fired; an acceptance cannot override them")
    if not rationale or not rationale.strip():
        raise refuse("rationale is required")
    if expiry.tzinfo is None or expiry <= now:
        raise refuse("expiry must be a timezone-aware future time")
    rec = RiskAcceptanceRecord(acceptance_id=f"RA-{len(reg.records) + 1:04d}", risk_ref=risk_ref, app_ref=app_ref,
                               assessment_ref=assessment_ref, severity=severity, actor=actor, role=role,
                               rationale=rationale, scope=scope, created=now, expiry=expiry)
    reg.records.append(rec)
    reg._log("ACCEPTED", acceptance_id=rec.acceptance_id, severity=severity, expiry=expiry.isoformat(), **ctx)
    return rec


# ---- shared HumanTask integration (task 24.4): a RISK_ACCEPTANCE outcome feeds record() -----------------------
def request_acceptance(store: Any, risk_ref: str, app_ref: str, assessment_ref: str, requested_by: str, severity: str,
                       fired_gates: Iterable[str] = ()) -> Any:
    """Create a RISK_ACCEPTANCE HumanTask for the risk in ``store``, assigned to the store's first acceptance role."""
    from agip_shared.contracts import HumanTask
    return store.create(HumanTask(
        task_id=f"risk-acceptance-{assessment_ref}-{risk_ref}", framework="governance_execution", task_type="RISK_ACCEPTANCE",
        subject_refs=[f"risk:{risk_ref}", f"assessment:{assessment_ref}"], role=store.roles["RISK_ACCEPTANCE"][0],
        context={"risk_ref": risk_ref, "app_ref": app_ref, "assessment_ref": assessment_ref, "severity": severity,
                 "fired_gates": list(fired_gates), "created_by": requested_by}))


def record_from_task(store: Any, task_id: str, scope: str, expiry: datetime, **kw: Any) -> RiskAcceptanceRecord:
    """COMPLETED task -> record() with the reviewer's actor, role and rationale. Other states refuse."""
    task = store.get(task_id)
    done = [o for o in store.outcomes(task_id) if o.resulting_state == "COMPLETED"]
    if task.status != "COMPLETED" or not done:
        raise RiskAcceptanceError(f"task {task_id} is {task.status}; only a COMPLETED task can record an acceptance")
    o, c = done[-1], task.context
    return record(c["risk_ref"], c["app_ref"], c["assessment_ref"], o.actor, o.role, o.rationale, scope, expiry,
                  severity=c["severity"], fired_gates=c.get("fired_gates") or (), **kw)