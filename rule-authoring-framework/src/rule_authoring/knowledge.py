"""Typed knowledge (Req 21.3). Only executable types compile to Spectral; the rest are stored and reported in coverage."""
from __future__ import annotations

from enum import Enum
from typing import Any, Iterable


class KnowledgeType(str, Enum):
    """Kinds of knowledge item the framework stores; only the executable ones compile to rules."""
    PRINCIPLE = "principle"
    GUIDELINE = "guideline"
    RISK = "risk"
    RISK_SCENARIO = "risk_scenario"
    MITIGATION = "mitigation"
    CONTROL = "control"
    POLICY = "policy"
    REQUIREMENT = "requirement"
    ASSESSMENT_REQUIREMENT = "assessment_requirement"
    EVIDENCE_CRITERION = "evidence_criterion"
    EVALUATION_PROCEDURE = "evaluation_procedure"
    RECOMMENDATION = "recommendation"
    INFORMATIONAL_STATEMENT = "informational_statement"


EXECUTABLE_TYPES = frozenset({KnowledgeType.CONTROL, KnowledgeType.RISK})
NON_EXECUTABLE_TYPES = frozenset(set(KnowledgeType) - EXECUTABLE_TYPES)


def item_type(item: dict[str, Any]) -> KnowledgeType:
    """Explicit ``type`` field; legacy catalog entries are inferred from control_id / risk_id."""
    t = item.get("type")
    if t is not None:
        try:
            return KnowledgeType(str(t).lower())
        except ValueError:
            raise ValueError(f"unknown knowledge type {t!r}") from None
    if "control_id" in item:
        return KnowledgeType.CONTROL
    if "risk_id" in item:
        return KnowledgeType.RISK
    raise ValueError("item has no type and no control_id/risk_id")


def is_executable(item: dict[str, Any]) -> bool:
    """True if the item's type compiles to Spectral rules."""
    return item_type(item) in EXECUTABLE_TYPES


def executable(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Items whose type compiles to Spectral rules."""
    return [i for i in items if is_executable(i)]


def non_executable(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Items that are stored and counted in coverage but never compiled."""
    return [i for i in items if not is_executable(i)]
