# CALM app generation walkthrough

Run from `calm-app-generation-framework` with `PYTHONPATH=src:../shared/src`. Lifecycle state is in
`registry/lifecycle.yaml`; pass `--registry <copy>` to try the steps without changing it. The command-line path below
involves no LLM. The dashboard path (second part) adds two optional agent drafts, "Draft spec with the agent" and
"Generate with the agent"; their output is checked by code and saved only as DRAFT.
`tests/test_journey.py` runs the command-line path end to end with a stub `calm` CLI.

## Command-line path

1. **Inspect and select.** `python -m calm_generation patterns` lists the 11 patterns (P02, P03, P07, P08, P11 to P17)
   with version and state. `python -m calm_generation versions` shows each pattern hash and the version history of each
   reference architecture (RA) template: RA03-LITE v1 is `SUPERSEDED`, v2 is `PUBLISHED`; RA05-CYBER-REMEDIATION is v1.
2. **Compose.** `python -m calm_generation compose` composes `templates/RA03-LITE.compose.yaml` (ra-version 2, composed
   from P02 v2 and P03, P07, P08, P11 to P14). Only APPROVED or PUBLISHED patterns that pass static validation are
   accepted. The output records source pattern versions and hashes. Pass another spec path to compose another RA, for
   example `templates/RA05-CYBER-REMEDIATION.compose.yaml`.
3. **Trigger a conflict.** Bind a property to a value a pattern forbids (see `tests/test_journey.py`). Compose exits 1,
   names both patterns and writes nothing.
4. **Review and publish.** Each step needs `--by`, `--role` and `--rationale`, and follows the shared lifecycle table:
   `submit` (IN_REVIEW), `approve` (APPROVED), `publish` (PUBLISHED); `reject` and `deprecate` also exist.
   Example: `python -m calm_generation approve RA03-LITE --by dana --role architect --rationale "controls mapped"`.
5. **Form.** `python -m calm_generation form RA03-LITE --out form.yaml`. An unpublished template is refused.
6. **Instantiate (V1).** Fill `form.yaml`, then `python -m calm_generation instantiate --form form.yaml --out app.json`.
   This needs the `calm` CLI (found on PATH or via `CALM_BIN`) and prints the output hash. Without it the command exits with a clear error.
   `calm generate` receives only the published template (as `p.json`) and the option choices (as `c.json`); the attribute
   values are filled into the generated model afterwards (see "What `calm generate` receives").
7. **Reject invalid attributes.** A bad value (for example `PAYMENT_AGENT_PRIVILEGE: root`) is refused before `calm` runs.
8. **V4 invalid.** If `calm validate` reports errors, the command prints each path and message and exits 1.
9. **Reproduce.** Running step 6 again with the same form gives the same sha256 and identical bytes.

`python -m calm_generation validate <file>` checks a pattern statically (CALM 1.2 shape, node references, catalog IDs,
technology neutrality) or validates an architecture through `calm`.

The command-line `instantiate` checks attributes only. The option-to-attribute consistency rules (below) are applied by
the dashboard path.

## Dashboard path

Start the dashboard from the repo root: `uv run python -m governance_execution.dashboard.app` (http://127.0.0.1:8001).
Menu: Architecture > Build Pattern, Build Reference Architecture, Generate CALM. This path has no login; the Approve
buttons are the MVP direct approval (recorded as `dashboard-reviewer`, role `governance_admin`, no role check; role
checks are in the backlog).

### Build Pattern (`/patterns/new`)

An architect writes a pattern as a YAML spec (`calm_generation/pattern_builder.py`), or starts from an existing pattern
(`?start=P12`):

```yaml
pattern_id: P20                 # P plus 2 or 3 digits
slug: remediation-tool          # lower-case kebab-case, used in the file name
title: Remediation Tool
description: Agent applies allow-listed fixes to tagged hosts.
nodes:
  - id: agent
    type: ai:agent              # actor, ecosystem, system, service, database, network, ldap, webclient, data-asset, ai:agent, ai:tool, ai:llm
    name: Agent
    description: AI agent that applies remediation.
    metadata:                   # lower_snake_case field -> {const: v} | {enum: [two or more values]} | {type: string|number|integer|boolean[, minimum, maximum]}
      remediation_scope: {enum: [allow-listed, any]}
  - {id: target-host, type: system, name: Target Host, port: true}   # a port is a connection point a component fills; no metadata
relationships:
  - {id: agent-remediates-host, description: Agent applies fixes, from: agent, to: target-host}
related_controls: [AIGF-MI-018]
related_risks: [AIGF-RI-024]
```

- **Field reuse rule.** A metadata field name already used by another library pattern must keep exactly the same
  schema (unless one side is a `const`), or use another name. The Composer merges patterns that share a component and
  reports a conflict when the same property is defined differently, so the builder rejects the clash at save time.
- **Save** validates the spec and the generated CALM 1.2 pattern and stores it as a **DRAFT** (hash rule). Identical
  content is reported as unchanged and nothing is written. Changed content is saved as version + 1 and returns to
  DRAFT (example: P02 is now v2, after a wording edit in the UI).
- **Draft spec with the agent.** Describe the pattern and a Strands agent (Bedrock, temperature 0.1, needs
  `MODEL_PROVIDER=bedrock` and `BEDROCK_MODEL_ID`) proposes a spec. Steering makes it retry (at most 2 times) until the
  spec passes `check_spec`, reuses library fields exactly and names only controls and risks that exist in the catalogs.
  The result opens in the editor; nothing is saved until the architect saves it.
- **Approve** (Catalog > CALM Patterns Catalog) takes the pattern to PUBLISHED; the pattern file then shows status
  `APPROVED` and the approver. Revising a published pattern lists the RAs composed from its older version, each with a
  **Recompose** link that opens the RA in the editor.

The library now has P15 High-Impact Action Approval and P16 Controlled Remediation (see `patterns/SPECS.md`), built
with `scripts/build_cyber.py` and published. P17 "New Pattern" was created from the UI and is kept.

### Build Reference Architecture (`/architectures/new`)

An RA template is composed from published patterns only. Three YAML texts define it, all stored under `templates/`:

| File | Content |
|---|---|
| `<ra>.compose.yaml` | Composer spec: patterns, components (`from: P12/agent`, several patterns can feed one component), `bind` (fixed fields), relationships, `options` (oneOf / anyOf design choices) |
| `<ra>.questions.yaml` | The business questions Generate CALM asks |
| `<ra>.consistency.yaml` | Optional: attributes that must follow a chosen option |

Two ways in:

- **Generate with the agent.** Enter an RA id (for example `RA05-CYBER`), the patterns to use and a description. A
  Strands agent (`calm_generation/ra_agent.py`, temperature 0.1) proposes a compose spec. Code drives at most 4
  rounds: each round runs the Composer, `calm validate -p` on the template and the question checks, and returns their
  errors to the agent. The agent cannot add nodes or metadata, because the Composer only merges what the patterns
  declare. The questions are then derived by rule, one per option and one per enum, number or boolean field (free-text
  string fields stay under Advanced in Generate CALM). Known weakness: balancing `oneOf` choices, which must list the
  same number of nodes and of relationships.
- **Edit by hand.** Pick an existing RA to edit (`?start=<RA id>`) or paste the three texts.

**Preview** composes and checks everything and writes nothing: YAML, composition conflicts, `calm validate -p`,
questions and consistency rules against the template's form, and a warning for fields no question covers.
**Save as DRAFT** writes `<ra>.json` and the three YAML files and records the composition in the lifecycle registry
(hash rule: an identical composition keeps its version; a changed one is the highest recorded version + 1).
**Approve and publish** makes it available to Generate CALM, which offers only PUBLISHED templates.

**Questions file.** Each question maps an answer onto the template. `set` gives attribute values, `options` gives an
option choice (a list for an `anyOf` option); a `number` question fills one attribute. Example from
`RA05-CYBER-REMEDIATION.questions.yaml`:

```yaml
questions:
  - id: remediation_approval
    label: How is a remediation action released to the production hosts?
    answers:
      human-approval: {label: "A security analyst approves every action ...", options: {opt-approval-path: actions-require-human-approval}}
      direct:         {label: "The agent applies actions directly ...",      options: {opt-approval-path: actions-are-applied-directly}}
  - id: agent_autonomy
    label: How independently may the remediation agent investigate and act?
    answers:
      supervised: {label: "Only under supervision ...", set: {REMEDIATION_AGENT_AUTONOMY: supervised}}
  - {id: payment_limit, label: "What is the largest single payment?", type: number, attribute: PAYMENT_AGENT_PAYMENT_LIMIT}   # RA03-LITE
```

**Consistency file.** An attribute that records the same design decision as an option must agree with it:

```yaml
rules:
  - {option: opt-approval-path, choice: actions-require-human-approval, requires: {REMEDIATION_AGENT_ACTION_APPROVAL_PATH: via-human-approval}}
  - {option: opt-approval-path, choice: actions-are-applied-directly,   requires: {REMEDIATION_AGENT_ACTION_APPROVAL_PATH: direct}}
```

When the attribute is empty, it is set from the chosen option. When it is set and disagrees, Generate CALM rejects the
form before `calm generate` runs. Both files are reused unchanged for every application.

### Generate CALM (`/applications/new`)

1. **Step 1.** App id and name, "What does the application do?", and the reference architecture (PUBLISHED only). If
   none is chosen, the only published template is used, or the Decider chooses one from the description (accepted only
   if it passes the Decider policy).
2. **Step 2: requirement questions** from `templates/<ra>.questions.yaml`. The user picks an answer, or "Not sure, I will
   describe it" and the Decider maps the text to an answer (policy-gated; otherwise the user is asked to choose).
   Template fields that no question covers are under Advanced. Without a questions file the raw attribute form is shown.
3. **Derive and check.** Attributes implied by the chosen options are set from `<ra>.consistency.yaml`. Anything still
   empty is inferred by the Decider from the description and the chosen design, again only when the policy accepts it.
   Contradictions are shown as errors and nothing is generated.
4. **Generate.** Attributes are validated, then `calm generate`, placeholder fill and `calm validate -p` run, and the
   governance assessment starts. The report has an "Inputs and requirements" section that shows who set each value:
   the user, a question, an option, or the Decider (with model and confidence).

### What `calm generate` receives

Only the published template (`p.json`, `RA….json`) and the option choices (`c.json`, option id to chosen description):
`calm generate -p p.json --option-choices c.json -o out.json`. The attribute values do not go into `calm generate`;
`placeholders.fill` writes them into the generated model afterwards. The generation manifest records the template hash,
the option choices, the attributes hash and the fill record, so the same template and inputs give the same model.

## Example: RA05-CYBER-REMEDIATION

A cyber remediation agent reads alerts from a data store, calls a language model, and applies remediation to production
hosts through a tool. It is composed from P08, P11, P12, P14, P15 and P16 (`templates/RA05-CYBER-REMEDIATION.*`). The RA
agent generated it; the approval option (`opt-approval-path`) was balanced by review, and the audit service is an
`anyOf` option (`opt-audit`). Generating CALM for it gives:

| Application | Answers | Result |
|---|---|---|
| cyber-fixed | analyst approval, audit trail | risk tier High (Tier 2), `APPROVED_WITH_CONDITIONS` |
| cyber-blocked | direct production changes, no audit | risk tier Critical (Tier 1, Override 1), `REJECTED` by gate G2; AIGF-MI-021 and AIGF-MI-024 fail; AIGF-RI-024 and AIGF-RI-022 triggered |

## RA03-LITE version 2

P02 became v2 (description wording edited in the UI), so RA03-LITE was recomposed as ra-version 2. The registry keeps
both versions (`versions` shows v1 as `SUPERSEDED`), the forms were regenerated with `scripts/build_forms.py`, and the
recorded CLI results were refreshed. The composition content is the same apart from the P02 text.
