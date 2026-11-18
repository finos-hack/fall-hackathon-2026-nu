# extraction.v1

You are drafting a governance rule from the prose of one framework item (an AIGF risk or mitigation, or a CCC control, threat or capability).
A human reviews your output before it is used. Use only the prose in INPUT. Do not invent controls, IDs or tools.

Return ONE JSON object and nothing else, with exactly these fields:

```
{
  "kind": "control" | "risk",
  "triggers": [{"dimension": "<risk dimension name>", "condition": "<when this dimension is triggered, one sentence>"}],
  "likelihood": {"score": 1-5, "criteria": "<why this likelihood>"},
  "impact": {"score": 1-5, "criteria": "<why this impact>"},
  "remediation": "<one or two sentences telling the owner how to fix a failing design>",
  "candidate_rule": {
    "rule_code": "<lowercase-kebab-case, prefix ctl- for controls or risk- for risks>",
    "description": "<what the rule checks>",
    "severity": "error" | "warn" | "info" | "hint",
    "given": "<JSONPath into a CALM architecture, for example $.nodes[?(@['node-type']=='ai:agent')].metadata>",
    "then": {"field": "<optional field>", "function": "truthy|pattern|enumeration|schema|length", "functionOptions": {}}
  }
}
```

Rules:
- Likelihood and impact are integers 1 to 5 (1 lowest).
- The candidate rule must be expressible with a core Spectral function on a named metadata field. If it cannot be, set `"candidate_rule": null` and add `"inexpressible_reason": "<why>"`.
- Do not include file paths, URLs with credentials, or secrets.
- Output JSON only. No commentary.
