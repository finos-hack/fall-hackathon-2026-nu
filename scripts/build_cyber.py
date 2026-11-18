"""Cyber remediation building blocks (step C), reproducible and idempotent (hash rule: re-running changes nothing).

1. Generic patterns, saved through the Build Pattern path and published:
   P15 High-Impact Action Approval (agent action class + approval path, human approval service)
   P16 Controlled Remediation (remediation tool with an action allow-list, target host fleet)
2. Catalog rules for them (AIGF mitigations from the hackathon demo guide: MI-18 least privilege incl. approval,
   MI-24 human approval gate, MI-21 decision audit), compiled into the Spectral rulesets:
   * AIGF-MI-024 CFG-HITL-PRODUCTION (mandatory, critical): production-changing agents act only via human approval.
     Gate G2 rejects any application where AIGF-MI-024 fails.
   * AIGF-MI-018 CFG-REMEDIATION-SCOPE (high): remediation limited to allow-listed actions on tagged hosts.
   * AIGF-RI-024 rule risk-production-change-without-approval: triggers the risk when the approval path is direct.

Run from the repo root: ``uv run python scripts/build_cyber.py``.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CATALOGS = ROOT / "rule-authoring-framework" / "catalogs"
RULESETS = ROOT / "rule-authoring-framework" / "rulesets"
BY = "cyber-remediation-build"

ACTION = {"enum": ["read-only", "reversible-write", "business-write", "production-change"]}
PATTERNS = [
    {"pattern_id": "P15", "slug": "high-impact-action-approval", "title": "High-Impact Action Approval",
     "description": "An agent declares how far its actions reach; high-impact actions pass a human approval step.",
     "nodes": [
         {"id": "agent", "type": "ai:agent", "name": "Agent", "description": "AI agent whose high-impact actions need approval.",
          "metadata": {"action_capability": ACTION, "action_approval_path": {"enum": ["via-human-approval", "direct"]}}},
         {"id": "human-approval", "type": "service", "name": "Human Approval Service",
          "description": "Queues high-impact actions for a human decision.", "metadata": {"role": {"const": "human-approval"}}}],
     "relationships": [{"id": "agent-requests-approval", "description": "Agent submits high-impact actions for approval",
                        "from": "agent", "to": "human-approval"}],
     "related_controls": ["AIGF-MI-024", "AIGF-MI-018"], "related_risks": ["AIGF-RI-024"]},
    {"pattern_id": "P16", "slug": "controlled-remediation", "title": "Controlled Remediation",
     "description": "A remediation tool applies only allow-listed actions to a tagged host fleet.",
     "nodes": [
         {"id": "remediation-tool", "type": "ai:tool", "name": "Remediation Tool",
          "description": "Tool that applies remediation actions to hosts.",
          "metadata": {"remediation_scope": {"enum": ["allow-listed", "any"]}, "input_validation": {"enum": ["enforced", "none"]}}},
         {"id": "host-fleet", "type": "system", "name": "Host Fleet", "description": "Hosts that remediation actions are applied to.",
          "metadata": {"environment": {"enum": ["production", "non-production"]}, "host_tagging": {"enum": ["enforced", "none"]}}}],
     "relationships": [{"id": "tool-changes-hosts", "description": "Remediation tool applies actions to the hosts",
                        "from": "remediation-tool", "to": "host-fleet"}],
     "related_controls": ["AIGF-MI-018"], "related_risks": ["AIGF-RI-024"]},
]

PROD_AGENT = "$.nodes[?(@['node-type']=='ai:agent' && @.metadata.action_capability=='production-change')].metadata"
CONTROL_CONFIGS = {
    "AIGF-MI-024": ({"id": "CFG-HITL-PRODUCTION", "mandatory": True, "severity": "critical",
                     "rule_codes": ["ctl-production-change-requires-approval"],
                     "remediation": "Route every production-changing action of the agent through the Human Approval Service."},
                    {"ctl-production-change-requires-approval": {
                        "description": "Production-changing agents act only after human approval",
                        "message": "Agent at {{path}} changes production without the human approval path (AIGF mi-24)",
                        "severity": "error", "given": PROD_AGENT,
                        "then": {"field": "action_approval_path", "function": "pattern", "functionOptions": {"match": "^via-human-approval$"}}}}),
    "AIGF-MI-018": ({"id": "CFG-REMEDIATION-SCOPE", "mandatory": False, "severity": "high",
                     "rule_codes": ["ctl-remediation-allow-listed", "ctl-hosts-tagged"],
                     "remediation": "Limit the remediation tool to the allow-listed actions and apply them only to tagged hosts."},
                    {"ctl-remediation-allow-listed": {
                        "description": "Remediation tools run only allow-listed actions",
                        "message": "Remediation tool at {{path}} is not limited to allow-listed actions (AIGF mi-18)",
                        "severity": "error", "given": "$.nodes[?(@['node-type']=='ai:tool' && @.metadata.remediation_scope)].metadata",
                        "then": {"field": "remediation_scope", "function": "pattern", "functionOptions": {"match": "^allow-listed$"}}},
                     "ctl-hosts-tagged": {
                        "description": "Remediation targets only tagged hosts",
                        "message": "Host fleet at {{path}} does not enforce remediation tagging (AIGF mi-18)",
                        "severity": "error", "given": "$.nodes[?(@['node-type']=='system' && @.metadata.host_tagging)].metadata",
                        "then": {"field": "host_tagging", "function": "pattern", "functionOptions": {"match": "^enforced$"}}}}),
}
RISK_RULES = {
    "AIGF-RI-024": ("risk-production-change-without-approval", {
        "description": "A production-changing agent acts without human approval",
        "message": "Agent at {{path}} changes production directly (AIGF ri-24)",
        "severity": "error", "given": PROD_AGENT,
        "then": {"field": "action_approval_path", "function": "pattern", "functionOptions": {"notMatch": "^direct$"}}}),
}


def patterns() -> None:
    from calm_generation import lifecycle as lc, pattern_builder as pb
    for spec in PATTERNS:
        res = pb.save(spec, by=BY)
        print(f"pattern {spec['pattern_id']}: {res['action']}" + (f" {res['errors']}" if res["errors"] else f" v{res.get('version')}"))
        if res["errors"]:
            sys.exit(1)
        if lc.state_of(spec["pattern_id"]) in ("DRAFT", "IN_REVIEW"):
            for target in (["IN_REVIEW"] if lc.state_of(spec["pattern_id"]) == "DRAFT" else []) + ["APPROVED", "PUBLISHED"]:
                lc.transition(spec["pattern_id"], target, by="architecture-review", role="architect",
                              rationale="cyber remediation building block (step C)")
            print(f"  published {spec['pattern_id']}")
        pb.mark_approved(spec["pattern_id"], "architecture-review")


def _revise(entry: dict, change: str) -> None:
    at = datetime.now(timezone.utc).isoformat()
    entry["version"] = int(entry.get("version", 1)) + 1
    entry.setdefault("history", []).append({"from": "APPROVED", "to": "APPROVED", "by": BY, "role": "governance_admin",
                                            "rationale": change, "at": at, "version": entry["version"]})


def catalogs() -> bool:
    from rule_authoring.versioning import write_catalog
    changed = False
    p = CATALOGS / "controls.catalog.yaml"
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    for cid, (cfg, rules) in CONTROL_CONFIGS.items():
        e = next(i for i in doc["items"] if i["control_id"] == cid)
        if any(c["id"] == cfg["id"] for c in e.get("configurations") or []):
            continue
        e["configurations"].append(cfg)
        e["spectral_rules"].update(rules)
        _revise(e, f"added {cfg['id']} for production-changing agents (cyber remediation)")
        changed = True
        print(f"control {cid}: + {cfg['id']} -> v{e['version']}")
    if changed:
        doc["version"] = int(doc.get("version", 1)) + 1          # catalog version = ruleset header version
        write_catalog(p, doc)
    p = CATALOGS / "risks.catalog.yaml"
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    rchanged = False
    for rid, (code, rule) in RISK_RULES.items():
        e = next(i for i in doc["items"] if i["risk_id"] == rid)
        if code in (e.get("rule_codes") or []):
            continue
        e["rule_codes"].append(code)
        e["spectral_rules"][code] = rule
        _revise(e, f"added {code} (cyber remediation)")
        rchanged = True
        print(f"risk {rid}: + {code} -> v{e['version']}")
    if rchanged:
        doc["version"] = int(doc.get("version", 1)) + 1
        write_catalog(p, doc)
    return changed or rchanged


def main() -> None:
    patterns()
    catalogs()
    from rule_authoring import compile as comp
    for k, c in comp.compile_all(CATALOGS, RULESETS).items():
        print(f"ruleset {k}: v{c.version}, {len(c.rule_codes)} rules")


if __name__ == "__main__":
    main()
