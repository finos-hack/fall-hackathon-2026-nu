"""Gap_Level from failed-control catalog severities using the versioned gap rule (Req 17.3, 17.4)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

CONFIG = Path(__file__).resolve().parents[3] / "config" / "gap_rule.yaml"
_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def load_gap_rule(path: Path = CONFIG) -> dict[str, Any]:
    """Load the versioned gap rule YAML (default ``config/gap_rule.yaml``)."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def gap_level(statuses: list[tuple[str, str | None]], rule: dict[str, Any]) -> str:
    """``statuses``: (status, catalog severity of the failed configuration). ERROR anywhere -> INDETERMINATE_INPUT."""
    if any(s == "ERROR" for s, _ in statuses):
        return rule["error_controls"]
    failed = [sev for s, sev in statuses if s == "FAIL" and sev]
    if not failed:
        return rule["gap_level"]["none"]
    return rule["gap_level"][max(failed, key=lambda s: _RANK[s])]
