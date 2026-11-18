"""Build the eight Pattern_Library JSON files from the specification table (see patterns/SPECS.md).

Run from the repo root: ``uv run python scripts/build_patterns.py``. Output is deterministic.
The files are then reviewed and published with ``calm_generation.pattern_library.publish``.
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "calm-app-generation-framework" / "patterns"
CORE = "https://calm.finos.org/release/1.2/meta/core.json#/defs/"
ENABLED = {"enum": ["enabled", "none"]}


def node(uid, ntype, name, desc, meta):
    """CALM pattern constraint for one node: fixed unique-id, node-type, name and description, with required metadata keys."""
    return {"$ref": CORE + "node", "type": "object",
            "properties": {"unique-id": {"const": uid}, "node-type": {"const": ntype}, "name": {"const": name},
                           "description": {"const": desc},
                           "metadata": {"type": "object", "properties": meta, "required": sorted(meta)}},
            "required": ["unique-id", "node-type", "name", "description", "metadata"]}


def port(uid, ntype, name):
    """Neighbour role a relationship needs. The Composer maps it to another component; it is never emitted itself."""
    return {"$ref": CORE + "node", "type": "object",
            "properties": {"unique-id": {"const": uid}, "node-type": {"const": ntype}, "name": {"const": name},
                           "description": {"const": f"{name} (connection point)"}},
            "required": ["unique-id", "node-type", "name", "description"]}


def connects(uid, desc, src, dst):
    """CALM pattern constraint for a 'connects' relationship between two node ids."""
    return {"$ref": CORE + "relationship", "type": "object",
            "properties": {"unique-id": {"const": uid}, "description": {"const": desc},
                           "relationship-type": {"const": {"connects": {"source": {"node": src},
                                                                         "destination": {"node": dst}}}}},
            "required": ["unique-id", "description", "relationship-type"]}


SPECS = [
    ("P02", "api-gateway", "API Gateway", "Single mediated entry point for external callers.",
     [node("api-gateway", "service", "API Gateway", "Mediates and authenticates external requests.",
           {"role": {"const": "api-gateway"}, "exposure": {"const": "external"}, "mediation": {"const": "gateway"}}),
      port("client", "actor", "Client")],
     [connects("client-calls-gateway", "Client calls the gateway", "client", "api-gateway")], ["CCC.VPC"], ["AIGF-RI-010"]),
    ("P03", "application-service", "Application Service", "Internal business application service.",
     [node("app-service", "service", "Application Service", "Runs business logic.",
           {"role": {"type": "string"}, "exposure": {"enum": ["internal", "external"]},
            "mediation": {"enum": ["gateway", "none"]}, "criticality": {"enum": ["low", "medium", "high", "critical"]}}),
      port("caller", "service", "Caller")],
     [connects("caller-calls-service", "Caller invokes the service", "caller", "app-service")], ["CCC.VPC"], []),
    ("P07", "external-system-integration", "External System Integration", "A system outside the trust boundary.",
     [node("external-system", "service", "External System", "System operated outside the application boundary.",
           {"role": {"type": "string"}, "exposure": {"const": "external"}, "mediation": {"enum": ["gateway", "none"]}}),
      port("caller", "service", "Caller")],
     [connects("caller-calls-external", "Caller invokes the external system", "caller", "external-system")], ["CCC.VPC", "AIGF-MI-017"], ["AIGF-RI-024"]),
    ("P08", "relational-data-store", "Relational Data Store", "Structured persistent data store.",
     [node("data-store", "database", "Data Store", "Stores structured records.",
           {"data_classification": {"type": "string"}, "access_control": {"enum": ["rbac", "none"]},
            "encryption_at_rest": ENABLED}),
      port("data-consumer", "service", "Data Consumer")],
     [connects("consumer-reads-store", "Consumer reads and writes records", "data-consumer", "data-store")], ["AIGF-MI-012", "CCC.KMS"], ["AIGF-RI-001"]),
    ("P11", "llm-inference", "LLM Inference", "Hosted foundation model used for inference.",
     [node("foundation-model", "ai:llm", "Foundation Model", "Large language model used for inference.",
           {"model_version": {"enum": ["pinned", "floating"]}, "guardrails": ENABLED,
            "sensitive_data_filtering": ENABLED}),
      port("model-consumer", "service", "Model Consumer")],
     [connects("consumer-calls-model", "Consumer sends prompts to the model", "model-consumer", "foundation-model")], ["AIGF-MI-017"], ["AIGF-RI-005", "AIGF-RI-001"]),
    ("P12", "tool-using-agent", "Tool-Using Agent", "Agent that acts through declared tools.",
     [node("agent", "ai:agent", "Agent", "AI agent that invokes tools.",
           {"privilege": {"enum": ["read-only", "restricted-write", "unrestricted-write"]},
            "permitted_tools": {"type": "string"}, "credential_storage": {"enum": ["vault", "inline"]},
            "observability": ENABLED, "acceptance_testing": {"enum": ["completed", "none"]}, "input_filtering": ENABLED}),
      node("tool", "ai:tool", "Tool", "Tool exposed to the agent.",
           {"input_validation": {"enum": ["enforced", "none"]}, "mcp_server": {"enum": ["governed", "ungoverned"]}})],
     [connects("agent-uses-tool", "Agent invokes the tool", "agent", "tool")],
     ["AIGF-MI-018", "AIGF-MI-019", "AIGF-MI-020", "AIGF-MI-023", "AIGF-MI-004", "AIGF-MI-005"], ["AIGF-RI-010"]),
    ("P13", "human-in-the-loop", "Human-in-the-Loop", "High-impact agent actions pass a human approval step.",
     [node("agent", "ai:agent", "Agent", "AI agent whose high-impact actions need approval.",
           {"can_execute_payment": {"type": "boolean"}, "payment_approval_path": {"enum": ["via-human-approval", "direct"]},
            "payment_limit": {"type": "number", "minimum": 1, "maximum": 100000}}),
      node("human-approval", "service", "Human Approval Service", "Queues high-impact actions for a human decision.",
           {"role": {"const": "human-approval"}})],
     [connects("agent-requests-approval", "Agent submits actions for approval", "agent", "human-approval")],
     ["AIGF-MI-024"], ["AIGF-RI-024"]),
    ("P14", "autonomous-agent-execution", "Autonomous Agent Execution", "Agent decisions executed with an audit trail.",
     [node("agent", "ai:agent", "Agent", "AI agent that executes decisions.",
           {"autonomy": {"enum": ["supervised", "semi-autonomous", "autonomous"]},
            "decision_impact": {"enum": ["low", "medium", "high", "financial"]}}),
      node("audit-service", "service", "Audit Service", "Records agent decisions for review.",
           {"role": {"const": "audit"}})],
     [connects("agent-is-audited", "Agent decisions are recorded", "agent", "audit-service")],
     ["AIGF-MI-021"], ["AIGF-RI-018", "AIGF-RI-022"]),
]


def build(pid, slug, title, desc, nodes, rels, controls, risks):
    """Assemble a pattern schema from node and relationship constraints; arrays are pinned to exactly those entries (min/max items) in order. Status is APPROVED."""
    return {
        "$schema": "https://calm.finos.org/release/1.2/meta/calm.json",
        "$id": f"https://agip.example/patterns/{pid}-{slug}.json",
        "title": f"{pid} {title}",
        "description": desc,
        "metadata": {"pattern-id": pid, "version": 1, "status": "APPROVED", "approved_by": "architecture-review",
                     "related_controls": controls, "related_risks": risks},
        "type": "object",
        "properties": {
            "nodes": {"type": "array", "minItems": len(nodes), "maxItems": len(nodes), "prefixItems": nodes},
            "relationships": {"type": "array", "minItems": len(rels), "maxItems": len(rels), "prefixItems": rels},
        },
        "required": ["nodes", "relationships"],
    }


def main() -> None:
    """Write one JSON pattern file per entry in SPECS (sorted keys, stable output)."""
    OUT.mkdir(parents=True, exist_ok=True)
    for spec in SPECS:
        p = build(*spec)
        (OUT / f"{spec[0]}-{spec[1]}.json").write_text(json.dumps(p, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(spec[0], "written")


if __name__ == "__main__":
    main()
