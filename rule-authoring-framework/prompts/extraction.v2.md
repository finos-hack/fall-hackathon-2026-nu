# extraction.v2

You are drafting a governance rule from one Common Cloud Controls (CCC) control or threat. A human reviews your output before it is used.
Use only the fields in INPUT. Do not invent controls, IDs, mappings or tools. Do not output IDs or references: they are kept from the source.

INPUT is one JSON object:

```
{
  "framework": "CCC",
  "id": "<CCC ID, unchanged>",
  "kind": "control" | "threat",
  "title": "<title>",
  "objective": "<control objective, or the threat description when kind is threat>",
  "assessment_requirements": [{"id": "<AR id>", "text": "<requirement text>"}],
  "threat_mappings": [{"id": "<threat id>", "title": "<threat title>"}]
}
```

Return ONE JSON object and nothing else:

```
{
  "kind": "control" | "risk",              // a CCC control is "control"; a CCC threat is "risk"
  "triggers": [{"dimension": "<one of the Scoring_Profile dimensions>", "condition": "<one sentence>"}],
  "likelihood": {"score": 1-5, "criteria": "<why>"},   // a suggestion; a human confirms it
  "impact": {"score": 1-5, "criteria": "<why>"},       // a suggestion; a human confirms it
  "remediation": "<one or two sentences for the owner>",
  "candidate_rule": {
    "rule_code": "<lowercase-kebab-case, prefix ctl- for controls or risk- for risks>",
    "description": "<what the rule checks>",
    "severity": "error" | "warn" | "info" | "hint",
    "given": "<JSONPath into a CALM architecture>",
    "then": {"field": "<metadata field>", "function": "truthy|pattern|enumeration|schema|length", "functionOptions": {}}
  },
  "inexpressible_reason": null
}
```

Scoring_Profile dimensions: Autonomy, Data Exposure, Privilege & Capability, Connectivity, Decision Impact, Human Oversight, Operational Criticality.

CALM metadata vocabulary you may check (anything else is not checkable):
- ai:agent: autonomy, privilege, can_execute_payment, payment_approval_path, credential_storage, observability, acceptance_testing, input_filtering
- ai:llm: model_version, guardrails, sensitive_data_filtering
- ai:tool: input_validation, mcp_server
- service: role, exposure, mediation
- database: data_classification, access_control, encryption_at_rest

Rules:
- Likelihood and impact are integers 1 to 5.
- If no check over the vocabulary above can express the control or threat, set `"candidate_rule": null` and give `"inexpressible_reason"` (one sentence naming what is missing). Still fill the other fields. Do not force a rule onto an unrelated field.
- No file paths, credentials or secrets. JSON only.
