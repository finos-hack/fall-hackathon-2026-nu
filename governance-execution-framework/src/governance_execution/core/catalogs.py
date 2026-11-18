"""Read-only access to the compiled catalogs and the CALM selectors used by their rules."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

CATALOG_DIR = Path(__file__).resolve().parents[4] / "rule-authoring-framework" / "catalogs"
_NODE_TYPE = re.compile(r"@\['node-type'\]==\s*'([^']+)'")
_META_EQ = re.compile(r"@\.metadata\.(\w+)\s*==\s*(true|false|'[^']*')")


def load(kind: str, directory: Path = CATALOG_DIR) -> dict[str, Any]:
    """Read ``<kind>.catalog.yaml`` from ``directory`` and return the parsed catalog."""
    return yaml.safe_load((directory / f"{kind}.catalog.yaml").read_text(encoding="utf-8"))


def approved(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """Catalog items whose status is APPROVED; other statuses are ignored."""
    return [i for i in catalog.get("items") or [] if i.get("status") == "APPROVED"]


def checked_fields(*catalogs: dict[str, Any]) -> set[str]:
    """Metadata fields read by any deterministic (Spectral) rule."""
    out: set[str] = set()
    for cat in catalogs:
        for item in approved(cat):
            for rule in (item.get("spectral_rules") or {}).values():
                then = rule.get("then")
                for t in then if isinstance(then, list) else [then]:
                    if isinstance(t, dict) and t.get("field"):
                        out.add(t["field"])
    return out


def targeted_nodes(given: str, app_model: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    """Nodes selected by a rule's ``given`` of the form ``$.nodes[?(@['node-type']=='X' && @.metadata.f==v)]``."""
    nt = _NODE_TYPE.search(given or "")
    conds = [(k, True if v == "true" else False if v == "false" else v.strip("'")) for k, v in _META_EQ.findall(given or "")]
    out = []
    for i, n in enumerate(app_model.get("nodes") or []):
        if nt and n.get("node-type") != nt.group(1):
            continue
        meta = n.get("metadata") or {}
        if all(meta.get(k) == v for k, v in conds):
            out.append((i, n))
    return out if nt else []


def applicability(app_model: dict[str, Any]) -> set[str]:
    """Applicability facts used to decide NOT_APPLICABLE controls."""
    nodes = app_model.get("nodes") or []
    types = {n.get("node-type") for n in nodes}
    agents = [n.get("metadata") or {} for n in nodes if n.get("node-type") == "ai:agent"]
    facts = set()
    if agents:
        facts.add("agent_present")
    if any(a.get("can_execute_payment") is True or a.get("action_capability") == "production-change" for a in agents):
        facts.add("agent_can_perform_high_impact_action")
    if any("credential_storage" in a for a in agents):
        facts.add("agent_uses_credentials")
    if "ai:tool" in types:
        facts |= {"agent_has_tool_access", "agent_has_external_action"}
    if "database" in types and agents:
        facts.add("agent_accesses_sensitive_data")
    if any((n.get("metadata") or {}).get("exposure") == "external" for n in nodes):
        facts.add("agent_has_external_connectivity")
    return facts
