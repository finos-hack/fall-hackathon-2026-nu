# Rule-Authoring Showcase: FINOS-Style Deterministic Control Authoring

This folder demonstrates a repeatable, deterministic, **LLM-free** workflow for authoring new governance rules from FINOS AIGF/CCC sources.

## Why Deterministic?

New governance rules require accuracy, traceability, and audit ability. This workflow eliminates LLM-based inconsistency by using:
- **Markdown templates** (human-readable governance source)
- **Jinja2 templating** (rule derivation)
- **Python transforms** (deterministic logic)
- **YAML output** (canonical rule format)

The result: new rules that are reproducible, versionable, and auditable.

This guide has two parts. Part A (the markdown template example below) shows the rule logic written by hand; the
`transform` module and `rule.yaml.j2` template it names were removed in task 16, so treat Part A as a description of
the logic, not as commands to run. Part B, **Extracting rules from AIGF, CCC and uploaded documents** (after the FAQ),
is the current path: a model drafts the rule, code fixes everything it must not decide, and a human approves.

## The Workflow

```
FINOS Control Definition (CCC / AIGF mitigations)
                │
                ▼
FINOS-Style Control Markdown (template)
                │
                ▼
applicability_facts (what architectures does this rule apply to?)
evidence_keys (what evidence proves this control?)
                │
                ▼
templates/rule.yaml.j2 (Jinja2 template)
                │
                ▼
rule_authoring.transform (Python module)
                │
                ▼
catalogs/seed/rules/[new-rule].yaml (canonical YAML)
                │
                ▼
Validate + Deploy
```

## Example: MI-18 (Agent Authorization for High-Impact Actions)

### 1. Source — FINOS AIGF Mitigation

From [FINOS AI Governance Framework](https://github.com/finos/ai-governance-framework):

> **MI-18: Authorization Service for High-Impact Agent Actions**
>
> **Category:** AI Agent Governance
> **Applies to:** AI agents that can perform high-impact actions (financial decisions, data deletion, user-facing actions)
> **Mitigation:** Require an authorization service (policy engine, human approval flow, or role-based gating) that intercepts and approves all high-impact agent actions before execution.
> **Rationale:** Prevents autonomous agents from causing irrevocable harm to users or financial systems without human oversight.
> **References:** NIST SP 800-53 AC-6 (Least Privilege), AU-2 (Audit Events)

### 2. Control Markdown

Create a file `mi-18-agent-authorization.md` in this folder:

```markdown
---
source: "FINOS AIGF: mi-18"
reference: "Agent Authorization for High-Impact Actions"
category: "Agent Governance"
---

# Agent Authorization for High-Impact Actions

**FINOS Source:** Mitigation MI-18 (AI Governance Framework)  
**NIST Control:** AC-6 (Least Privilege), AU-2 (Audit Events)

## Applicability

This control applies when:
- The agent has `can_perform_high_impact_action = true`  
  (e.g., can issue refunds, delete data, transfer funds, modify accounts)

## Evidence Keys

The architecture provides evidence of this control if it contains:
- An `authorization-service` node connected to the agent via an `authorized_by` relationship
- A `policy-engine` or `role-based-access` mechanism in the authorization service metadata
- All high-impact actions routed through the authorization service (not directly to external systems)

## Required Properties

- Authorization mechanism present
- Policy enforcement enabled
- Audit logging of authorization decisions

## Covered When

Any of these conditions are true:
- Agent has `authorized_by` relationship to `authorization-service` node
- Authorization service metadata contains `authorization_model: policy_engine`
- Agent is behind an API gateway that enforces authorization

## Gap When

- Agent has `can_perform_high_impact_action = true` AND
- No `authorized_by` relationship to any authorization service

## Unknown When

- Insufficient detail in the architecture to determine if authorization is present
- No explicit evidence about authorization flow for high-impact actions
```

### 3. Run the Transform

```bash
mkdir -p _out
uv run python -m rule_authoring.transform \
    --input rule-authoring-framework/docs/examples/mi-18-agent-authorization.md \
    --output rule-authoring-framework/_out/agent-authorization-mi18.yaml \
    --registry "" \
    --rule-id AGENT-AUTHORIZATION-MI18 \
    --title "Agent Authorization for High-Impact Actions"
```

The script:
1. Parses the markdown frontmatter (source, reference, category)
2. Extracts applicability conditions, evidence keys, covered/gap/unknown logic
3. Renders `rule.yaml.j2` with the extracted data
4. Writes the canonical YAML rule (schema-valid: `category`, enum `framework`)

### 4. Validate the Result

```bash
# from the repo root: parse the generated rule with the shared contract
uv run python -c "import yaml; from agip_shared.contracts import CanonicalRule as R; print(R(**yaml.safe_load(open('rule-authoring-framework/_out/agent-authorization-mi18.yaml'))).id)"
```

Expected output:
```
AGENT-AUTHORIZATION-MI18
```

### 5. Deploy

The example is generated into `_out/` (scratch, gitignored) so it does not alter
the demo scores. To ship it for real, reconcile its applicability with the
existing `agent-authorization-001.yaml` (they overlap), then copy it in:

```bash
cp rule-authoring-framework/_out/agent-authorization-mi18.yaml rule-authoring-framework/catalogs/seed/rules/
```

## Files in This Folder

| File | Purpose |
|------|---------|
| `AUTHORING-GUIDE.md` | Step-by-step guide (this file) |
| `src/rule_authoring/transform.py` | Python script that converts markdown → YAML |
| `rule.yaml.j2` | Jinja2 template for the canonical YAML output |
| `mi-18-agent-authorization.md` | Example control markdown (sample) |
| `_out/` | Scratch output dir for generated rules (gitignored) |

## Writing Your Own Rule

1. Pick a FINOS source: AIGF mitigation or CCC control
2. Create a markdown file: `[source-id]-[short-name].md`
3. Fill in the sections (Applicability, Evidence Keys, Covered When, Gap When, Unknown When)
4. Run `src/rule_authoring/transform.py` to generate the YAML
5. Validate with the CLI
6. Add to the test suite

## FAQ

### Can I use this without Python?

The transform script is Python, but the inputs (markdown) and output (YAML) are human-readable. You can manually write YAML if needed, but running `src/rule_authoring/transform.py` ensures consistency.

### What if I don't know all the evidence keys?

Start with what you know:
- What node type or relationship type proves the control is present?
- What property or metadata key would you check?

Ask the security architect for feedback; iterate. The deterministic part is the logic, not the initial discovery.

### Can I generate rules from an LLM?

Yes, in Part B. Part A deliberately avoids it. Part B uses a model to draft rules, but keeps the result auditable: the Rule_Code and the checked fields are fixed by code, invalid rules are dropped, every answer is recorded and replayable, and nothing is compiled until a human approves the item.

### How do I test my new rule?

1. Write a test CALM architecture that should COVER the rule
2. Write a test CALM architecture that should GAP the rule
3. Run the validator on both
4. Check that the findings are correct

See `tests/test_validator.py` for examples.

## Next Steps

- Write a markdown control definition for a new FINOS source
- Run the transform
- Add test cases in the test suite
- Submit as part of the TechX conference update




---

## Part B: Extracting rules from AIGF, CCC and uploaded documents

```
source (AIGF / CCC checkout, or uploaded .md / .yaml)
   -> ingest            catalogs/sources/<source>.json
   -> extract           model drafts one item; code fixes Rule_Code and checks the rule  -> catalogs/drafts/<id>.json
   -> merge             rule_authoring.merge: drafts -> catalog entries, always DRAFT
   -> review            submit / confirm (risks) / approve, by a human
   -> compile           APPROVED entries -> rulesets/*.spectral.yaml
```

CLI: `python -m rule_authoring.ingest --source aigf|ccc --extract --provider replay|bedrock` (see `WALKTHROUGH.md`).
Dashboard: **Generate Rules** (below). Both use the same extraction code.

### Rule_Code assignment

For AIGF items and uploaded items (`UPL`), the model does not choose the Rule_Code. `extraction.rule_code_for` sets it
and overwrites whatever the model wrote:

| Case | Rule_Code |
|---|---|
| The catalog already has a code for this item | That code is kept, because patterns, rulesets and other items refer to it |
| New AIGF risk or mitigation | `risk-aigf-ri-001` (risk) or `ctl-aigf-mi-006` (control): prefix, then the lower-case item ID |
| New uploaded document | `risk-upl-<slug>` or `ctl-upl-<slug>`, from the document's `id:` (or title) |

For CCC the CCC ID is kept and the model proposes the Rule_Code (lower-case kebab-case is required).
A Rule_Code mismatch never causes a retry for AIGF or uploads, since the code replaces it.

### Rule checks against the taxonomy

For AIGF and uploaded **risks**, the extraction prompt is extended at run time with:

- the allowed Scoring_Profile dimensions. Each `triggers[].dimension` must be exactly one of them, otherwise the
  whole extraction is rejected and reported as an error;
- the checkable fields, read from `governance-execution-framework/config/taxonomy.yaml` as data (a new taxonomy
  attribute becomes available without a code change): field name, dimension, node types and raw values.

A candidate rule is accepted only if it can match App_Model metadata (`extraction._rule_problem`):

- `then.field` is a taxonomy attribute;
- `then.function` is `pattern` (with `match` or `notMatch`) or `enumeration` (with a non-empty `values` list);
- `given` is `$.nodes[?(@['node-type']=='<type>')].metadata` (an `&& ...` filter inside the brackets is allowed),
  and `<type>` is a node type listed for that field in the taxonomy.

Spectral reports a finding when the value violates the rule, so a finding must mean the risk is present: use
`enumeration` with the safe values, or `pattern` with `notMatch` set to the risky value.

**Inexpressible items.** If no taxonomy field can express the check, the model must set `candidate_rule: null` and
give `inexpressible_reason` (prompt `extraction.v1.md`; "truthy on the closest field" is no longer allowed). A stub
rule that has a reason but no `then` is also treated as no rule. If the model proposes a rule that fails the checks,
the rule is dropped and the draft is kept with the reason `model-proposed rule rejected: <problem>; rule needs human
authoring`. The risk (dimension, likelihood, impact, remediation) stays for review. An inexpressible draft is listed
in the run summary, carries no Spectral rule, and is therefore not compiled. Controls and CCC items are not field-checked.

### Temperature and steering

`ingest --provider bedrock` samples at temperature 0.1 (`--temperature`) and enables Strands steering by default.
Steering (`steering_check`, a Strands `SteeringHandler`) applies the same schema, dimension and field checks while the
model is answering. A failing answer is rejected with the problem as guidance and the model tries again, at most
`--steering-retries` times (default 2; 0 turns retries off). The checks run again when the answer is stored, so a
recorded answer is held to the same rules. `--provider replay` needs no model.

A recorded model answer is reused when the input, the full prompt text (`prompt_sha256` in the Extraction_Record),
the model and the runtime parameters all match. The CLI prints how many answers were reused.

### Risk likelihood and impact from the Decider

Risk likelihood and impact come from the Strands Decider, not from the model (`rule_authoring/scoring.py`):

- two `score` questions over the risk text, with the rubrics from the Scoring_Profile (`likelihood_scale`, `impact_scale`);
- the score is the most probable level (1 to 5); the confidence is kept, and a confidence below 0.5 is flagged
  `low_confidence`; the model's criteria text stays as the explanation;
- each answer is recorded by input hash (CLI: `fixtures/recordings/decider-scores/`, created on the first live call;
  dashboard: `<data>/llm-records/decider-scores/`) and replayed when the input is the same;
- if the Decider cannot be reached or has no recording, the model's scores are kept and the reason is stored in
  the entry's `scoring` block (`source: llm`, `decider_error`).

`ingest --scores decider|llm` chooses the source (default `decider`; it applies to AIGF risks only in the CLI).
The Risk catalog row shows it as "Scored by". In the live runs so far (Nova 2 Lite) the Decider confidence was about
0.45, so every score was flagged low-confidence: a human must still confirm likelihood and impact before a risk can be
approved (`approval confirm`).

### Dashboard: Generate Rules

`http://127.0.0.1:8001/rules/new` (menu: Generate Rules). It runs the same path as the CLI, with Bedrock through
Strands at temperature 0.1 with steering when `MODEL_PROVIDER=bedrock` and `BEDROCK_MODEL_ID` are set, otherwise
from recordings only. The page states which one is in use.

Accepted uploads (UTF-8, at most 1 MB per file, at most 20 items per run; PDF and Word are rejected):

| Upload | Becomes |
|---|---|
| `.md` / `.markdown` named like an AIGF file (`ri-<n>.md`, `ri-<n>_<name>.md`, same for `mi-`) with front matter | AIGF item with its AIGF ID, for example `AIGF-RI-001` |
| Any other `.md` / `.markdown` | Uploaded item `UPL-<id>`. Optional front matter: `title`, `type` (risk, mitigation or control; shown in the run summary, while the model's output decides control or risk), `id`, `<framework>_references: [...]`. Without front matter the first `# heading` is the title and the whole text is the prose |
| `.yaml` / `.yml` CCC catalog fragment with `controls:` and/or `threats:` | CCC items, IDs kept |

The `<id>` is the slug of `id:` (else the title): lower-case letters, digits and dashes, at most 48 characters, and
always at least one dash (`-doc` is added if there is none), because Rule_Codes need one.
Every item records the file name and its SHA-256, so an unchanged document is not extracted again.

Flow: extract, then merge into the main catalogs as DRAFT, then the run page `/rules/runs/<run_id>` (files, drafts,
rejected items, inexpressible items, merge result per item). Each run is kept in `<data>/rule-runs/<run_id>/`
(`uploads/`, `drafts/`, `summary.json`). Items show PENDING HUMAN REVIEW with an **Approve** button, then
**Compile rulesets** runs the consistency check and the compile.

The Approve button is the MVP direct approval: it records `dashboard-reviewer` with role `governance_admin`, with no role
check (role checks are in the backlog). For a risk it also records the confirmation of the proposed likelihood and
impact. The CLI keeps the full steps (`approval submit`, `confirm`, `approve`, each with `--by --role --rationale`).

### Merge and versioning (hash rule)

`python -m rule_authoring.merge [--drafts DIR] [--catalogs DIR] [--ids ID ...]` merges drafts into the catalogs:

| Draft compared with the catalog entry | Result |
|---|---|
| Item is not in the catalog | Added as DRAFT (`ADDED`) |
| Same content | Nothing written (`UNCHANGED`) |
| Changed content, entry not approved | Content replaced, version + 1, history kept (`UPDATED`) |
| Changed content, entry APPROVED | New DRAFT at version + 1. The approved entry is kept as `previous_approved` and **stays in force**: compile uses it until the new version is approved (`REVISED`) |

`mandatory_trigger`, `type` and `history` are human-curated and are kept from the existing entry. Status, version,
history, approval and confirmation fields, `scoring` and `extraction` are not content, so approving or re-scoring
alone never raises the version; changing the title, references, scores, rules or remediation does. Approving the new
version removes `previous_approved`. The history records of a revision carry its version, and review tasks are
created per version (`request_review(..., version=)`).

Drafts follow the same rule: unchanged input gives the same draft; a changed draft is version + 1; a draft equal to
the catalog entry is not written; a new draft for an item already in the catalog starts at the catalog version + 1.

### Compile version

`python -m rule_authoring.compile` leaves the ruleset bytes alone when the rules did not change. When they changed,
it raises the catalog's top-level `version:` by one (edited in place in `controls.catalog.yaml` or
`risks.catalog.yaml`), and that number is the ruleset header's `# version:`. Only APPROVED entries are compiled, or
the `previous_approved` entry of a revision under review.

### Catalog header

Catalog writes (merge and approval) keep the leading `#` comment block of the YAML file (the CALM metadata
vocabulary and the merge notes), through `versioning.write_catalog`. A plain `yaml.safe_dump` would drop it.

---

## Assigning a control severity (scoring rubric for new rules)

Every rule carries a `severity` (`critical | high | medium | low`) that drives the
**Go/No-Go gate** (a Critical/High control GAP forces No-Go). Assign it
deterministically so new rules are consistent with existing ones.

Score the control's **blast radius** on three axes, 0–2 each (max 6):

| Axis | 0 | 1 | 2 |
|------|---|---|---|
| **Reversibility of harm** if the control is missing | Reversible | Hard to reverse | Irreversible (financial, data loss, regulatory) |
| **Data / regulatory exposure** it protects | None / public | Internal-confidential | PII, regulated, market-sensitive |
| **Autonomy & reach** it governs | Human-approved, internal | Semi-autonomous or external | Fully autonomous, external/MCP, multi-agent |

Sum the three axes and map to severity:

| Axis sum | `severity` |
|----------|-----------|
| 5–6 | `critical` |
| 3–4 | `high` |
| 1–2 | `medium` |
| 0   | `low` |

These axes intentionally mirror the agent **risk dimensions** (reversibility ≈
action capability / decision impact; exposure ≈ data access; autonomy & reach ≈
autonomy + external connectivity), so a rule author reasons the same way the
assessment scores risk.

**Worked example (MI-18 Agent Authorization):** Reversibility = 2 (irreversible
high-impact actions), Exposure = 1 (business systems), Autonomy & reach = 2
(autonomous external actions) → sum 5 → **critical**.

## How the 6 current risk rules were made

The six entries in `catalogs/risks.catalog.yaml` were not extracted by the pipeline. They were seed-imported from the
draft repo: each has `approved_by: seed-import`, a two-step history (`DRAFT -> IN_REVIEW -> APPROVED`, `by: seed-import`,
`role: seed`, rationale "seed import") and a `confirmation` block whose `by` is `seed-import` with the note "seed value
accepted at import; not an approved policy judgement". Their likelihood and impact are therefore seed values, not human
policy decisions. New risks go through `ingest --extract`, review, `confirm` and `approve` (see `WALKTHROUGH.md`).
