# Design-Time GRC Vocabulary — Official FINOS CALM v1.2

This document maps design-time AI-agent governance concepts to the official FINOS CALM v1.2 schema.

## FINOS CALM v1.2 Architecture Structure

A CALM architecture is a top-level JSON object with:

```json
{
  "$schema": "https://calm.finos.org/release/1.2/meta/calm.json",
  "metadata": {
    "id": "unique-architecture-identifier",
    "name": "Architecture Name",
    "description": "Description of the architecture"
  },
  "nodes": [
    {
      "unique-id": "node-id",
      "node-type": "node-type",
      "name": "Friendly name",
      "description": "Required node description",
      "metadata": {
        "custom_key": "value"
      }
    }
  ],
  "relationships": [
    {
      "unique-id": "relationship-id",
      "description": "Human-readable description",
      "relationship-type": {
        "connects": {
          "source": {"node": "source-node-id"},
          "destination": {"node": "target-node-id"}
        }
      },
      "metadata": {
        "governance_type": "authorized-by",
        "controls": ["custom_key"]
      }
    }
  ]
}
```

> **Official CALM note:** nodes require `unique-id`, `node-type`, `name`, and
> `description`. Relationships require `unique-id` and a `relationship-type`
> whose key is one of the **five official verbs only**: `interacts`, `connects`,
> `deployed-in`, `composed-of`, `options`. This framework's governance
> semantics (authorized-by, audited-by, uses, can-access, invokes,
> communicates-through) are **not** CALM relationship verbs — they are recorded
> in relationship `metadata.governance_type` while the relationship itself uses
> the official `connects` verb (`{"source": {"node": ...}, "destination": {"node": ...}}`).
> Actor→agent uses `interacts` (`{"actor": "<id>", "nodes": ["<id>"]}`). This keeps
> every model valid against `calm validate` and renderable in CALM tooling.

## Governance Extensions (metadata.controls)

Governance properties are stored in node/relationship `metadata` under a `controls` list:

```json
"metadata": {
  "controls": [
    "encryption_at_rest",
    "multi_factor_auth",
    "audit_logging"
  ]
}
```

Or as structured objects for evidence:

```json
"metadata": {
  "controls": [
    {
      "key": "authorization_mechanism",
      "value": "policy_engine"
    }
  ]
}
```

## Node Types

### `ai-agent`

An autonomous decision-making system.

**Governance-relevant metadata keys**:
- `autonomy_level`: "autonomous" | "semi_autonomous" | "human_supervised"
- `has_external_action`: boolean
- `can_perform_high_impact_action`: boolean
- `accesses_sensitive_data`: boolean
- `has_external_connectivity`: boolean
- `capabilities`: list of capability strings

**Example**:
```json
{
  "unique-id": "support_agent",
  "node-type": "ai-agent",
  "name": "Customer Support Agent",
  "metadata": {
    "autonomy_level": "semi_autonomous",
    "has_external_action": true,
    "can_perform_high_impact_action": true,
    "accesses_sensitive_data": true,
    "has_external_connectivity": false,
    "capabilities": ["tool_invocation", "api_calling"],
    "controls": [
      "multi_factor_auth",
      "encryption_at_rest"
    ]
  }
}
```

### `datastore`

A persistent data repository.

**Governance-relevant metadata keys**:
- `data_classification`: "public" | "internal" | "confidential" | "restricted"
- `contains_pii`: boolean
- `contains_sensitive_data`: boolean
- `access_control_type`: "rbac" | "abac" | "fine_grained" | "none"

**Example**:
```json
{
  "unique-id": "customer_db",
  "node-type": "datastore",
  "name": "Customer Database",
  "metadata": {
    "data_classification": "confidential",
    "contains_pii": true,
    "access_control_type": "rbac",
    "controls": [
      "encryption_at_rest",
      "access_logging",
      "encryption_in_transit"
    ]
  }
}
```

### `external-system`

External services, APIs, or third-party systems.

**Governance-relevant metadata keys**:
- `trust_level`: "trusted" | "untrusted" | "conditional"
- `requires_authentication`: boolean
- `encryption_support`: boolean
- `high_impact_capability`: boolean

**Example**:
```json
{
  "unique-id": "payment_api",
  "node-type": "external-system",
  "name": "Payment Processing API",
  "metadata": {
    "trust_level": "trusted",
    "requires_authentication": true,
    "encryption_support": true,
    "high_impact_capability": true,
    "controls": [
      "rate_limiting",
      "api_key_rotation"
    ]
  }
}
```

### `authorization-service`

Handles access control and authorization decisions.

**Governance-relevant metadata keys**:
- `authorization_model`: "rbac" | "abac" | "policy_engine" | "attribute_based"

**Example**:
```json
{
  "unique-id": "authz_service",
  "node-type": "authorization-service",
  "name": "Authorization Service",
  "metadata": {
    "authorization_model": "policy_engine",
    "controls": [
      "policy_versioning",
      "audit_logging",
      "decision_caching"
    ]
  }
}
```

### `audit-service`

Logs and tracks system actions and decisions.

**Governance-relevant metadata keys**:
- `retention_period`: duration or "indefinite"
- `immutable`: boolean

**Example**:
```json
{
  "unique-id": "audit_service",
  "node-type": "audit-service",
  "name": "Audit Service",
  "metadata": {
    "retention_period": "7_years",
    "immutable": true,
    "controls": [
      "encryption_at_rest",
      "tamper_detection",
      "audit_of_audits"
    ]
  }
}
```

### `credential-store`

Secure storage for secrets, API keys, credentials.

**Governance-relevant metadata keys**:
- `encryption`: "enabled" | "disabled"
- `rotation_enabled`: boolean
- `access_control`: "rbac" | "fine_grained"

**Example**:
```json
{
  "unique-id": "secret_manager",
  "node-type": "credential-store",
  "name": "Secrets Manager",
  "metadata": {
    "encryption": "enabled",
    "rotation_enabled": true,
    "access_control": "fine_grained",
    "controls": [
      "mfa_for_access",
      "access_logging",
      "key_rotation"
    ]
  }
}
```

### `api-gateway`

Mediates and controls API access.

**Governance-relevant metadata keys**:
- `filtering_enabled`: boolean
- `rate_limiting_enabled`: boolean
- `authentication_enforcement`: boolean

**Example**:
```json
{
  "unique-id": "api_gateway",
  "node-type": "api-gateway",
  "name": "API Gateway",
  "metadata": {
    "filtering_enabled": true,
    "rate_limiting_enabled": true,
    "authentication_enforcement": true,
    "controls": [
      "waf_enabled",
      "ddos_protection",
      "request_logging"
    ]
  }
}
```

### `actor`

A human user or process initiating actions.

**Example**:
```json
{
  "unique-id": "user",
  "node-type": "actor",
  "name": "End User"
}
```

## Cyber Remediation Metadata (patterns P15 and P16)

Patterns P15 High-Impact Action Approval and P16 Controlled Remediation (`patterns/SPECS.md`) add five metadata fields.
The pattern library names node types with a colon (`ai:agent`, `ai:tool`, `ai:llm`) plus `service`, `database` and
`system`; the sections above use the older design-time names. Each field is also a taxonomy attribute
(`governance-execution-framework/config/taxonomy.yaml`): the raw value is mapped to a normalized value under a scoring
Dimension, and a value that matches no entry stays UNMAPPED.

### `ai:agent` (P15)

**Governance-relevant metadata keys**:
- `action_capability`: "read-only" | "reversible-write" | "business-write" | "production-change"
- `action_approval_path`: "via-human-approval" | "direct"

**Example**:
```json
{
  "unique-id": "agent",
  "node-type": "ai:agent",
  "name": "Remediation Agent",
  "metadata": {
    "action_capability": "production-change",
    "action_approval_path": "via-human-approval"
  }
}
```

### `ai:tool` (P16)

**Governance-relevant metadata keys**:
- `remediation_scope`: "allow-listed" | "any"
- `input_validation`: "enforced" | "none" (existing field, also declared by P16)

### `system` (P16)

**Governance-relevant metadata keys**:
- `host_tagging`: "enforced" | "none"
- `environment`: "production" | "non-production"

**Example**:
```json
{
  "unique-id": "host-fleet",
  "node-type": "system",
  "name": "Host Fleet",
  "metadata": {
    "environment": "production",
    "host_tagging": "enforced"
  }
}
```

### Taxonomy mapping and use

| Field | Node type | Normalized value | Dimension | Pattern | Used by |
|---|---|---|---|---|---|
| `action_capability` | `ai:agent` | unchanged (4 values) | Privilege & Capability | P15 | Approval-tier score: read-only 1, reversible-write 2, business-write 3, production-change 4 (the higher of this and `privilege`). `production-change` makes `agent_can_perform_high_impact_action` apply. Rules `ctl-production-change-requires-approval` (AIGF-MI-024) and `risk-production-change-without-approval` (AIGF-RI-024) test agents with this value |
| `action_approval_path` | `ai:agent` | `via-human-approval` is `human-approved`, `direct` is `unapproved` | Human Oversight | P15 | Both rules above. Approval-tier autonomy: `via-human-approval` caps it at 2, `direct` raises it to at least 3 |
| `remediation_scope` | `ai:tool` | `allow-listed`, `any` | Privilege & Capability | P16 | Rule `ctl-remediation-allow-listed` (AIGF-MI-018) |
| `host_tagging` | `system` | `enforced`, `none` | Privilege & Capability | P16 | Rule `ctl-hosts-tagged` (AIGF-MI-018) |
| `environment` | `system` | `production`, `non-production` | Operational Criticality | P16 | Recorded as a fact; no rule tests it yet |

`action_approval_path` has the same values and mapping as `payment_approval_path` (P13), so the approval path is one
vocabulary for payments and for production changes.

## Relationship Types (FINOS CALM v1.2)

Official CALM permits exactly **five** `relationship-type` verbs:
`interacts`, `connects`, `deployed-in`, `composed-of`, `options`. This framework
expresses AI-agent governance edges with the `connects` verb and records the
governance intent in `metadata.governance_type`. Actor→agent uses `interacts`.

### Official relationship verbs used here

- **`interacts`**: Actor interacts with one or more nodes
  ```json
  {"unique-id": "r1", "relationship-type": {"interacts": {"actor": "user", "nodes": ["agent"]}}}
  ```

- **`connects`**: A directed edge between two nodes (every governance edge)
  ```json
  {"unique-id": "r2",
   "relationship-type": {"connects": {"source": {"node": "agent"}, "destination": {"node": "authz-service"}}},
   "metadata": {"governance_type": "authorized-by", "controls": ["rbac_enforcement"]}}
  ```

### Governance verb → encoding

Each governance verb is a `connects` relationship with `metadata.governance_type`
set accordingly (the deterministic validator matches on `governance_type`):

| governance_type | Meaning | CALM verb |
|---|---|---|
| `can-access` | Agent can access data/system | `connects` |
| `invokes` | Agent/gateway invokes a service | `connects` |
| `authorized-by` | Access/action gated by authorization service | `connects` |
| `audited-by` | Action/decision logged by audit service | `connects` |
| `uses` | Agent/service uses a component (e.g. credentials) | `connects` |
| `communicates-through` | Communication mediated by a gateway | `connects` |

## Governance Applicability Conditions

The validator derives these facts from CALM architecture:

| Applicability Condition | Detection |
|---|---|
| `agent_has_external_action` | Node with node-type `ai-agent` has metadata `has_external_action: true`, OR has `invokes` relationship to `external-system` |
| `agent_accesses_sensitive_data` | Node with node-type `ai-agent` has metadata `accesses_sensitive_data: true`, OR has `can-access` relationship to `datastore` with metadata `contains_pii: true` or `data_classification` in ["confidential", "restricted"] |
| `agent_has_external_connectivity` | Node with node-type `ai-agent` has metadata `has_external_connectivity: true`, OR has relationship to `external-system` |
| `agent_uses_credentials` | Node with node-type `ai-agent` has `uses` relationship to `credential-store` |
| `agent_can_perform_high_impact_action` | Node with node-type `ai-agent` has metadata `can_perform_high_impact_action: true`, OR has `invokes` relationship to `external-system` with metadata `high_impact_capability: true` |
| `authorization_in_place` | Agent has `authorized-by` relationship to `authorization-service` |
| `audit_in_place` | Agent has `audited-by` relationship to `audit-service` |

In the current rules (`governance_execution/core/catalogs.applicability`), `agent_can_perform_high_impact_action` also
applies when an agent has `action_capability: production-change`, or `can_execute_payment: true`.

## Complete Example: Customer Support Agent

A full, schema-valid example (validated with `calm validate`, 0 errors) lives at:

- `architecture/examples/customer-support-compliant.json` - all controls present (10 COVERED / 0 GAP)
- `architecture/examples/customer-support-gap.json` - missing controls (2 COVERED / 7 GAP)

Both use the official `interacts` / `connects` verbs with governance intent in
`metadata.governance_type`, so they render in CALM tooling and pass `calm validate`.

## calm-cli Integration

To validate an architecture against official FINOS CALM v1.2:

```bash
# Install calm-cli (if not already present)
pip install calm-cli

# Validate an architecture file
calm validate path/to/architecture.json

# Output: "✓ Architecture is valid CALM v1.2" or detailed errors
```

The `calm-cli` tool checks:
- Structural conformance to CALM v1.2 schema
- Required metadata fields
- Valid relationship types
- Node references in relationships

## Notes

- All node `unique-id` and relationship `unique-id` values must be unique within the architecture
- The `from` and `to` endpoints (inside `relationship-type`) must reference existing node `unique-id` values; the `interacts` verb references nodes via `actor` and `nodes`
- Metadata fields are flexible and can include custom governance properties
- The `controls` list in metadata is the primary carrier of governance information
- When calm-cli is not installed, a lightweight Python parse guard ensures basic structural validity
