"""Mandatory_Gates, evaluated in documented order; the first that fires wins (Req 19.1, 19.4)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

CONFIG = Path(__file__).resolve().parents[3] / "config" / "gates.yaml"


def load_gates(path: Path = CONFIG) -> dict[str, Any]:
    """Load the ordered Mandatory_Gates YAML (default ``config/gates.yaml``)."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _fires(when: dict[str, Any], inputs: dict[str, Any]) -> bool:
    """True when every condition in ``when`` (calm status, control statuses, mandatory trigger) holds for ``inputs``."""
    if "calm_status" in when and inputs.get("calm_status") not in when["calm_status"]:
        return False
    for cid, status in (when.get("control_status") or {}).items():
        if (inputs.get("control_status") or {}).get(cid) != status:
            return False
    if "mandatory_trigger" in when and inputs.get("mandatory_trigger") != when["mandatory_trigger"]:
        return False
    return True


def evaluate(gates: dict[str, Any], inputs: dict[str, Any]) -> tuple[Optional[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (winning gate or None, record of every gate evaluated)."""
    record, winner = [], None
    for g in gates["order"]:
        fired = _fires(g["when"], inputs)
        record.append({"id": g["id"], "fired": fired, "outcome": g["outcome"] if fired else None,
                       "overridden": bool(fired and winner is not None)})
        if fired and winner is None:
            winner = g
    return winner, record
