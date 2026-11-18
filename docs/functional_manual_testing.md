# Functional manual testing

This guide tests the MVP by hand: each framework on its own, then the end-to-end flow, with the dashboard showing each run as it happens. Every command was run on Windows in Git Bash from the repo root (`ai-governance-intelligence-platform/`).

Fluxnova is not part of this MVP. The executor is `Direct_Adapter` (in-process). The dashboard has no login; its Approve buttons act as a fixed MVP reviewer (section 13).

## 0. One-time setup

### 0.1 Tools

| Tool | Check | Notes |
|---|---|---|
| Git Bash | `bash --version` | Run every command below in Git Bash, from the repo root |
| uv + Python 3.12 | `uv --version` | `uv sync` installs the Python dependencies |
| CALM CLI | `calm --version` | `npm i -g @finos/calm-cli` if missing |
| Spectral 6.17.1 | `.tools/node_modules/.bin/spectral --version` | Local install. If missing: `npm i --prefix .tools @stoplight/spectral-cli@6.17.1` |
| Source checkouts | `ls ../ai-governance-framework ../common-cloud-controls` | Needed only for ingestion (sections 2.2 and 6) |

```bash
uv sync
```

### 0.2 Configuration (`.env`)

All connection settings live in `.env` in the repo root (never committed). It is read from the current folder, so run every command from the repo root (see section 16 if you run from a framework folder). Start from the example and edit it:

```bash
cp .env.example .env      # only if you have no .env yet, or want to start again
```

Pick one of two profiles.

**Offline profile.** No Bedrock, no Decider. Use this for sections 1 to 8 and for the parts of sections 9 to 15 that do not call an agent.

```ini
MODEL_PROVIDER=replay        # recorded LLM outputs
DECIDER_PROVIDER=fixture     # recorded Decider answers
DATA_DIR=data
```

**Live profile.** Bedrock directly, plus your Strands Decider endpoint on EC2.

```ini
MODEL_PROVIDER=bedrock
AWS_REGION=<region>
AWS_PROFILE=<profile>        # or AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in the environment
BEDROCK_MODEL_ID=<model id enabled in that region>
DECIDER_PROVIDER=http
DECIDER_URL=http://<ec2-host>:8000
DECIDER_MODEL=<decider model name, if the endpoint needs one>
DECIDER_TIMEOUT_S=10
DATA_DIR=data
```

Before a live run, check both:

```bash
curl -s "$DECIDER_URL/health"          # export DECIDER_URL=... first, or paste the URL
aws sts get-caller-identity --profile <profile>
```

The agent steps in sections 9 to 12 (extraction, pattern draft, RA draft, Decider scores and mapping) need the live profile.

Other keys in `.env.example` (`EXECUTOR`, `FLUXNOVA_URL`, `PGLITE_*`, `CALM_BIN`, `SPECTRAL_BIN`, `AIGF_PATH`, `CCC_PATH`) can keep their defaults. Leave `EXECUTOR=direct`.

### 0.3 Configuration files you may change while testing

| File | What it controls | Change for |
|---|---|---|
| `governance-execution-framework/config/decider_policy.yaml` | Decider thresholds, `on_fail`, `block_on_pending_human` | Human-review flow (section 7) |
| `governance-execution-framework/config/roles.yaml` | Roles allowed to accept risk, with a severity limit per role | Risk acceptance |
| `governance-execution-framework/config/gates.yaml`, `decision_matrix.yaml`, `scoring_profile.yaml`, `gap_rule.yaml`, `taxonomy.yaml` | Decision logic | Leave as is. Changes alter the V1-V4 golden results |
| `rule-authoring-framework/catalogs/*.catalog.yaml` | Approved controls and risks | Change a copy only (section 2.4). The dashboard (section 9) edits the real files |
| `calm-app-generation-framework/registry/lifecycle.yaml`, `patterns/`, `templates/` | Pattern and RA lifecycle states and files | Change a copy only (`--registry`). The dashboard (sections 10 and 11) edits the real files |
| `calm-app-generation-framework/templates/<ra>.questions.yaml`, `<ra>.consistency.yaml` | Questions and option-consistency rules read by Generate CALM | Edit through Build Reference Architecture |

Human-task roles (who can act on which task type) default to the table in `shared/src/agip_shared/humantasks.py`:

| Task type | Roles |
|---|---|
| RULE_REVIEW | rule_reviewer, governance_admin |
| RISK_LI_CONFIRMATION | risk_analyst, governance_admin |
| PATTERN_APPROVAL, INVALID_CALM_CORRECTION | architect, governance_admin |
| RA_APPROVAL, RISK_ACCEPTANCE | risk_approver, governance_admin |
| DECIDER_CLASSIFICATION_REVIEW, REMEDIATION_REVIEW | risk_analyst, governance_admin |
| EVIDENCE_REVIEW | evidence_reviewer, governance_admin |

### 0.4 Scratch folder and reset

Use `_out/` for scratch copies; it is git-ignored. Every run stores its artifacts in `DATA_DIR` (default `data/`), and the dashboard reads the same folder. To start clean:

```bash
rm -rf data _out && mkdir -p _out
```

## 1. Automated checks first

```bash
uv run pytest -q shared/tests rule-authoring-framework/tests calm-app-generation-framework/tests governance-execution-framework/tests   # offline, about 4 min
uv run pytest -q -m acceptance        # the three framework acceptance journeys
```

Expected: 558 passed, 1 skipped across the four suites (shared 112, rule authoring 112 + 1 skipped, CALM generation 51, governance execution 283). The skip is the real-Spectral step in the Rule Authoring journey, skipped when Spectral is not on PATH.

## 2. Rule Authoring framework (`rule-authoring-framework/`)

### 2.1 Tests on their own

```bash
uv run pytest -q rule-authoring-framework/tests
```

### 2.2 Ingest the sources

```bash
uv run python -m rule_authoring.ingest --source aigf --out _out/aigf.json
uv run python -m rule_authoring.ingest --source ccc  --out _out/ccc.json
```

Expected:
- AIGF: `49 items (mitigation=25, risk=24), 0 errors, commit <hash>`.
- CCC: 148 items (38 controls, 51 threats, 59 capabilities), 0 errors.

Native IDs are kept (`ri-24`, `CCC.Core.CN02`).

### 2.3 Extract from recordings (no Bedrock)

```bash
uv run python -m rule_authoring.ingest --source ccc --extract --provider replay --drafts _out/drafts --out _out/ccc.json
ls _out/drafts
```

Expected:
- Drafts `CCC.Core.CN01.json`, `CCC.Core.CN02.json` and `CCC.Core.TH01.json`.
- The summary reports `CCC.Core.CN01` as INEXPRESSIBLE (the CALM vocabulary has no transport-encryption attribute).
- Items with no recording are listed as MISSING-RECORDING. They are reported, not dropped.

With the live profile, `--provider bedrock` calls Bedrock and writes new DRAFTs. They are never approved automatically.

### 2.4 Review lifecycle (on a copy)

```bash
cp -r rule-authoring-framework/catalogs _out/cat
sed -i '0,/status: APPROVED/s//status: DRAFT/' _out/cat/controls.catalog.yaml     # AIGF-MI-024 becomes DRAFT
uv run python -m rule_authoring.compile --catalogs _out/cat --out _out/rs         # skipped_unapproved=1, fewer controls rules
A="uv run python -m rule_authoring.approval"
$A approve AIGF-MI-024 --by bob --role rule_reviewer --rationale "skip" --catalog _out/cat/controls.catalog.yaml   # refused: DRAFT -> APPROVED
$A submit  AIGF-MI-024 --by alice --role author --rationale "ready" --catalog _out/cat/controls.catalog.yaml
$A approve AIGF-MI-024 --by bob --role rule_reviewer --rationale "checked" --catalog _out/cat/controls.catalog.yaml
uv run python -m rule_authoring.compile --catalogs _out/cat --out _out/rs         # controls v2 rules=15 again
cmp _out/rs/controls.spectral.yaml rule-authoring-framework/rulesets/controls.spectral.yaml && echo identical
```

Expected:
- Only APPROVED items compile.
- Skipping IN_REVIEW is refused.
- After approval, the compiled ruleset is byte-identical to the committed one.
- Each approval records the catalog version. A changed APPROVED item that comes back as DRAFT v+1 keeps its `previous_approved` copy in force for compile until it is approved (section 9.1).
- The item's `history` in `_out/cat/controls.catalog.yaml` records every step: who, role, rationale and time.

Risks need a recorded human confirmation of likelihood and impact before approval (`$A confirm <risk-id> ...`). The seed risks already carry a `seed-import` confirmation. The refusal case is covered by `uv run pytest -q rule-authoring-framework/tests/test_lifecycle.py -k confirm`.

### 2.5 Consistency, compile and coverage

```bash
uv run python -m rule_authoring.consistency        # prints "consistent"
uv run python -m rule_authoring.compile            # writes rulesets/*.spectral.yaml and rulesets/MANIFEST.yaml
git diff --stat rule-authoring-framework/rulesets  # expect no change to the two ruleset files
uv run python -m rule_authoring.coverage           # one row per AIGF risk/mitigation and CCC control/threat
```

Expected coverage counts: `APPROVED rule: 18, missing extraction: 54, non-executable (stored): 66`. `MANIFEST.yaml` holds the version and SHA-256 of each ruleset.

Do not edit the committed rulesets. The offline Spectral recordings are keyed by their bytes.

### 2.6 Merge drafts into the catalogs

```bash
uv run python -m rule_authoring.merge --drafts _out/drafts --catalogs _out/cat      # ADDED x3 (CCC.Core.CN01, CN02, TH01), all DRAFT v1
uv run python -m rule_authoring.merge --drafts _out/drafts --catalogs _out/cat      # UNCHANGED x3
```

Use `--ids` to limit the items. Run it on the copy `_out/cat` from 2.4 (section 2.3 must have produced `_out/drafts`). `--catalogs` defaults to the real catalogs.

## 3. CALM App Generation framework (`calm-app-generation-framework/`)

### 3.1 Tests on their own

```bash
uv run pytest -q calm-app-generation-framework/tests
```

### 3.2 Patterns, versions and the attributes form

```bash
uv run python -m calm_generation patterns          # 11 patterns (P02, P03, P07, P08, P11-P17), all PUBLISHED; P02 is v2
uv run python -m calm_generation versions          # version, state and SHA-256 of each pattern and template: RA03-LITE v1 SUPERSEDED, v2 PUBLISHED; RA05-CYBER-REMEDIATION v1 PUBLISHED
uv run python -m calm_generation form RA03-LITE --out _out/form.yaml
```

### 3.3 Lifecycle (on a copy of the registry)

```bash
cp calm-app-generation-framework/registry/lifecycle.yaml _out/lifecycle.yaml
uv run python -m calm_generation --registry _out/lifecycle.yaml deprecate P13 --by ann --role architect --rationale "test"
uv run python -m calm_generation --registry _out/lifecycle.yaml compose      # refused: P13 is not APPROVED/PUBLISHED
```

`submit`, `approve`, `publish` and `reject` take the same `--by --role --rationale` options.

### 3.4 Instantiate and validate (real `calm` CLI)

```bash
uv run python -m calm_generation instantiate --form governance-execution-framework/forms/v1.attributes.yaml --out _out/v1.json
uv run python -m calm_generation validate _out/v1.json                 # VALID
uv run python -m calm_generation instantiate --form governance-execution-framework/forms/v4.attributes.yaml --out _out/v4.json
```

Expected:
- V1 prints `VALID app=invoice-lite-v1 sha256=2796d275...`. Running it again gives the same hash.
- V4 prints `INVALID` with `/nodes/payment-agent/metadata/payment_limit: must be <= 100000`.

Also build V2 and V3 from their forms, `governance-execution-framework/forms/v2.attributes.yaml` and `v3.attributes.yaml`. The same variants are committed under `calm-app-generation-framework/fixtures/variants/invoice-lite-v{1..4}.json`.

## 4. Governance Execution framework (`governance-execution-framework/`)

### 4.1 Tests on their own

```bash
uv run pytest -q governance-execution-framework/tests
```

### 4.2 Assess an external CALM file

```bash
G="uv run python -m governance_execution"
$G assess _out/v1.json --mode no-llm --cli real --decider fixture --template RA03-LITE
```

Expected JSON: `assessment_status: COMPLETED`, `validation_status: VALID`, `decision: APPROVED_WITH_CONDITIONS`, and a `trace_id`.

| Flag | Values | Meaning |
|---|---|---|
| `--mode` | `normal`, `no-llm`, `replay` | `normal` uses MODEL_PROVIDER for the remediation text. `no-llm` uses a deterministic remediation list. `replay` uses recorded LLM output and the Decider fixture |
| `--cli` | `real`, `replay` | Run `calm`/`spectral`, or use recorded tool outputs |
| `--decider` | `http`, `fixture` | Overrides DECIDER_PROVIDER |

### 4.3 The four variants

```bash
for v in 1 2 3 4; do
  $G assess calm-app-generation-framework/fixtures/variants/invoice-lite-v$v.json --mode replay --cli replay --template RA03-LITE \
    | grep -E '"(assessment_status|decision)"'
done
```

| Variant | Status | Decision | Why |
|---|---|---|---|
| V1 | COMPLETED | APPROVED_WITH_CONDITIONS | Clean design. Design-level evidence only, so the result is conditional |
| V2 | COMPLETED | REJECTED | Gate G2: Payment Agent writes to the Payment API directly, without the approval control |
| V3 | COMPLETED | RESTRICTED | High risk profile: no audit service, autonomous Payment Agent |
| V4 | BLOCKED | none | Invalid CALM (payment_limit above 100000). No decision is made |

### 4.4 Show and replay

```bash
$G show <trace_id>                    # stored record and artifact list
$G replay <trace_id> --cli real       # expect "identical": true, same decision
```

Replay uses the catalogs, rulesets and config frozen with the assessment (`config_snapshot`), so later catalog edits do not change it.

## 5. Dashboard

### 5.1 Start it

```bash
uv run python -m governance_execution.dashboard.app       # http://127.0.0.1:8001, reads DATA_DIR
```

Or run `bash scripts/demo.sh`. It compiles the rulesets, assesses V1-V4 on recordings, starts the dashboard and opens the browser.

Keep the dashboard running in one Git Bash window and run commands in another. Every page reads the stored artifacts on each request. A run made with the same `DATA_DIR` appears after a browser refresh, with no restart. To point the dashboard at another folder: `DATA_DIR=_out/data uv run python -m governance_execution.dashboard.app`.

### 5.2 Pages

| Page | What to check |
|---|---|
| `/` or `/overview` | Six metrics: Controls, Risks, Patterns, Reference Architectures (each links to its catalog), Control Gaps Assessment, Risk Assessment (both link to Assessments) |
| Sidebar | Overview; Catalog (Controls Catalog `/catalogs/controls`, Risk Profile Catalog `/catalogs/risks`, CALM Patterns Catalog `/catalogs/patterns`, also `/catalogs/templates`); Source Registry `/source-registry` (sections `sources`, `dimensions`, `scoring`, `adrs`); Generate Rules `/rules/new`; Architecture (Build Pattern `/patterns/new`, Build Reference Architecture `/architectures/new`, Generate CALM `/applications/new`); Assessments. Catalog and Architecture are collapsible |
| `/rules/new`, `/rules/runs/{run}` | Generate Rules: upload, run results, Approve, Compile (section 9) |
| `/patterns/new`, `/architectures/new`, `/applications/new` | Build Pattern, Build Reference Architecture, Generate CALM (sections 10 to 12) |
| `/assessments` | One row per run, newest included. A WAITING_FOR_HUMAN run shows PENDING HUMAN REVIEW |
| `/assessments/{trace}` | Report (with tabs Report, Flow, Architecture, Risk matrix, Decider, Traceability, Execution): decision, gates, risk matrix, control gaps, remediation, Decider panel, UNMAPPED and inferred facts. Links to trace explorer, flow, architecture, export, replay |
| `/assessments/{trace}/execution` | Timeline: steps, status, input/output refs, versions, CALM hash, Decider outcomes, human tasks |
| `/assessments/{trace}/trace` | Lineage from the decision back to the source IDs |
| `/lineage/source/{id}` | Lineage from a source forward (for example `/lineage/source/AIGF:mi-24`) |
| `/review`, `/review/{id}` | Review queue across frameworks, filters, act on a task, resume an assessment |
| `/registry/{kind}` | Kinds: `sources`, `risks`, `controls`, `assessment-requirements`, `patterns`, `ras`, `rulesets`, `governance-config`, `scoring-profiles`, `evaluators`, `models-prompts`. Detail pages list the assessments that used the item |
| `/workbench/rule-authoring`, `/workbench/calm-generation`, `/workbench/governance` | Commands and history per framework |
| `/variants`, `/versions`, `/catalogs/{kind}` | Variant summary, versions, catalogs |
| `/api/docs` | Swagger UI: `POST /api/upload` (CALM file, 1 MB max), `/api/assess`, `/api/instantiate`, `/api/replay/{trace}`, `/api/assessments/{trace}/approve`, `/api/review/{task}/act` |
| `/catalogs/{controls,risks,patterns,templates}` | Catalog pages with expandable rows and PENDING HUMAN REVIEW badges and Approve buttons for DRAFT and IN_REVIEW items |

The `/review` queue and `/workbench/*` pages still exist but are not in the sidebar.

Every page shows the labels "illustrative, not approved policy" and "design-level evidence only".

## 6. End-to-end flow with the dashboard

Use the offline profile. Keep the dashboard running (section 5.1) and refresh the browser after each step.

| # | Step | Command | Dashboard check |
|---|---|---|---|
| 0 | Reset | `rm -rf data _out && mkdir -p _out` | `/overview` shows 0 assessments |
| 1 | Ingest | Section 2.2 commands | `/registry/sources` lists AIGF and CCC items |
| 2 | Extract | Section 2.3 command | none (drafts stay in `_out/drafts`) |
| 3 | Approve | Section 2.4 on `_out/cat` | none (copy only) |
| 4 | Compile | `uv run python -m rule_authoring.compile` | `/registry/rulesets` shows version and SHA-256 |
| 5-6 | Patterns, RA03-LITE | `uv run python -m calm_generation versions` | `/registry/patterns`, `/registry/ras` show PUBLISHED |
| 7 | Instantiate | Section 3.4 (V1 and V4) | none yet |
| 8-11 | Assess, classify, evaluate, decide | `$G assess _out/v1.json --mode no-llm --cli real --decider fixture --template RA03-LITE` | New row in `/assessments`. The report shows APPROVED_WITH_CONDITIONS and `invoice-db.data_classification` under "Inferred facts" (accepted Decider classification, raw value kept) |
| 8b | Blocked case | `$G assess _out/v4.json --mode no-llm --cli real --template RA03-LITE` | Status BLOCKED, no decision. `/overview` counts it as blocked |
| 9-12 | Create content in the UI | Sections 9 to 12 (writes into the repo files) | Catalog pages and Overview counters change |
| 12 | Human task | Section 7 | `/review` lists the task; after resume, the report shows the decision |
| 13 | Execution, lineage, replay | Open `/assessments/{trace}/execution` and `/assessments/{trace}/trace`, then click **Replay** on the report (or `$G replay <trace> --cli real`) | Replay reports identical |

A shorter run is `bash scripts/demo.sh`. It covers steps 4 and 8-11 for V1-V4 and opens the dashboard. Each command in the table is also explained in `docs/WALKTHROUGH-integrated.md`.

## 7. Human-review flow (pause, review, resume)

A run pauses for a human only when the Decider can't classify a fact confidently and the policy says to wait.

### 7.1 Offline

Make the recorded Decider answer fall below the threshold, and turn on blocking:

```bash
P=governance-execution-framework/config/decider_policy.yaml
cp "$P" _out/decider_policy.yaml.bak
sed -i 's/min_confidence: 0.80/min_confidence: 0.99/; s/on_fail: ABSTAIN  .*/on_fail: HUMAN_REVIEW/' "$P"
printf '\nblock_on_pending_human: true\n' >> "$P"
```

Run the assessment:

```bash
$G assess calm-app-generation-framework/fixtures/variants/invoice-lite-v1.json --mode replay --cli replay --decider fixture --template RA03-LITE
```

Expected:
- `assessment_status: WAITING_FOR_HUMAN`.
- `decision: null`.
- `pending_human_tasks: ["decider-review-<trace8>-invoice-db-data_classification"]`.

In the dashboard:
1. Open `/review`, then the task. The context shows the raw value and `allowed_values`.
2. Act **CLAIM**: actor `bob`, role `risk_analyst`, any rationale.
3. Act **COMPLETE**: same actor and role, with value `confidential` (one of the allowed values).
4. Under **Resume the assessment**, pick mode `replay` and tools `replay`, then click **Resume**.
5. The report opens with status COMPLETED and decision APPROVED_WITH_CONDITIONS. "Inferred facts" lists the classification with the reviewer as its source.

Checks to try:
- **Wrong role:** role `architect` gets HTTP 403.
- **Rejected review:** choosing REJECT instead of COMPLETE leaves the fact UNMAPPED. It is never given a risk-reducing default.

The CLI does the same:

```bash
$G resume <trace_id> --mode replay --cli replay
```

The task and its outcomes are files under `data/human_tasks/`, so the flow survives a restart. Outcomes are append-only.

Restore the policy afterwards:

```bash
cp _out/decider_policy.yaml.bak governance-execution-framework/config/decider_policy.yaml
git diff --stat governance-execution-framework/config/decider_policy.yaml    # expect no change
```

### 7.2 Live Decider

With the live profile:
1. Set only `on_fail: HUMAN_REVIEW` (and `block_on_pending_human: true` if the run should wait).
2. Run `$G assess <calm.json> --mode no-llm --cli real --decider http --template RA03-LITE`. An answer below the thresholds (choice: confidence < 0.80 or top-2 margin < 0.20) creates the review task.
3. Continue as in 7.1. Resume with `--mode no-llm --cli real`.

## 8. Live endpoints (Bedrock and Decider)

| Check | Command | Expected |
|---|---|---|
| Decider reachable | `curl -s http://<ec2-host>:8000/health` | HTTP 200 |
| Decider used | `$G assess _out/v1.json --mode no-llm --cli real --decider http --template RA03-LITE`, then open the report's **Decider** panel | Calls listed with model, confidence and outcome (ACCEPTED, HUMAN_REVIEW, ABSTAIN or ERROR) |
| Decider down | Same command with a wrong DECIDER_URL | Run completes. The fact stays UNMAPPED and the panel lists the call as ERROR. The decision never improves because of a Decider failure |
| Bedrock remediation | `$G assess _out/v3.json --mode normal --cli real --decider http --template RA03-LITE` | Report shows a Fix Prompt. The decision equals the `no-llm` run of the same file. LLM records are written to `data/llm-records/` |
| Bedrock down | Same with wrong credentials | Remediation falls back to the deterministic list; the decision is unchanged |
| Bedrock extraction | `uv run python -m rule_authoring.ingest --source aigf --ids ri-24 --extract --provider bedrock --drafts _out/drafts` | New DRAFT with an Extraction_Record (prompt version, model, input hash) |

The Decider never sets severity, control status, gates or the decision. `governance-execution-framework/tests/test_no_decider_in_decision.py` checks this.

## 9. Dashboard workflows: Generate Rules

Sections 9 to 15 test the dashboard pages that create and approve content. Read 9.0 first.

### 9.0 Before you start

- These pages write directly into the repo files: `rule-authoring-framework/catalogs/*.catalog.yaml`, `rule-authoring-framework/rulesets/`, `calm-app-generation-framework/patterns/`, `templates/` and `registry/lifecycle.yaml`. There is no scratch copy.
- Save a copy first and restore it when you finish (a `git checkout` would also discard uncommitted work):

```bash
mkdir -p _out/backup && cp -r rule-authoring-framework/catalogs rule-authoring-framework/rulesets _out/backup/
cp -r calm-app-generation-framework/patterns calm-app-generation-framework/templates calm-app-generation-framework/registry _out/backup/
git status --short > _out/status-before.txt
```

- Use a clean data folder for the assessments: `DATA_DIR=_out/data uv run python -m governance_execution.dashboard.app`.
- Agent steps need the live profile (section 0.2: `MODEL_PROVIDER=bedrock` and `BEDROCK_MODEL_ID`, plus the Decider for risk scores). The pages show the model in use, or "recordings only" / "No model configured". Offline, a new document has no recording, so Generate Rules lists it as "No model available and no recording", and the agent buttons in Build Pattern and Build Reference Architecture are disabled. Everything else (YAML editing, preview, save, approve, Generate CALM with questions) works offline.
- The sidebar is Overview; Catalog (Controls Catalog, Risk Profile Catalog, CALM Patterns Catalog); Source Registry; Generate Rules; Architecture (Build Pattern, Build Reference Architecture, Generate CALM); Assessments.

### 9.1 Upload, review, approve, compile

Create `_out/upl/supplier-access.md`:

```markdown
---
title: Supplier record access review
type: control
id: supplier-access-review
---
# Supplier record access review
An AI agent that reads supplier records must run with read-only privilege and its database must classify the data as confidential or restricted.
```

| Step | Action | Expected |
|---|---|---|
| 1 | Open `/rules/new` | Model label (Bedrock id or "recordings only"), supported formats (`.md`, `.markdown`, `.yaml`, `.yml`), limits 1000 KB per file and 20 items per run |
| 2 | Upload `supplier-access.md`, click **Generate rules** | Redirect to `/rules/runs/<run>`. One row `UPL-supplier-access-review`, status PENDING HUMAN REVIEW, merge action ADDED, version 1. Live: a candidate rule `ctl-upl-supplier-access-review` with its `given`/`then` check (under "check"), or "No rule: <reason>" if no taxonomy field fits. The `given` path is `$.nodes[?(@['node-type']=='<type>')].metadata` |
| 3 | Open `/catalogs/controls` | The new item shows with a PENDING HUMAN REVIEW badge and an Approve button |
| 4 | Upload an AIGF risk file (for example a copy of `../ai-governance-framework/docs/_risks/ri-24*.md`) | Row `AIGF-RI-024`. Likelihood/impact are shown as `L<n> / I<n>` with "Decider: <label> (<confidence>)". A confidence below 0.5 is marked low confidence. Nova-2-lite scores came out around 0.45, so expect that flag; a human must confirm |
| 5 | Click **Approve** on the control row | Status APPROVED, page returns to the run. History in the catalog YAML shows `dashboard-reviewer` / `governance_admin` |
| 6 | Click **Approve** on the risk row | Note under the button: "confirms L<n> / I<n>". Status APPROVED, and the risk records the confirmation |
| 7 | Click **Compile rulesets** | Table with `controls.spectral.yaml` and `risks.spectral.yaml`: version, rule count, SHA-256. The version goes up by 1 only for the ruleset whose rules changed. `MANIFEST.yaml` updated |
| 8 | Run `uv run python -m rule_authoring.consistency` | `consistent` |

Checks:
- **Unsupported file:** upload a `.pdf`. The run page lists "unsupported file type" under Input problems.
- **Size and count:** a file over 1000 KB, or more than 20 items, is reported and not extracted.
- **Re-upload unchanged:** upload the same `supplier-access.md` again. The row shows "unchanged", the version stays 1, no new model call is made (the run header may show "model answer(s) reused"), and compile leaves the ruleset bytes and versions as they were (`git diff --stat rule-authoring-framework/rulesets` shows no new change).
- **Re-upload changed:** edit one sentence and upload again. The item becomes DRAFT with version 2. If the previous version was APPROVED, the old version stays in force for compile until you approve the new one (`previous_approved` in the catalog entry).
- **CLI equivalent:** `uv run python -m rule_authoring.merge --drafts <drafts dir> --catalogs <catalog dir>` prints `ADDED`, `UNCHANGED`, `UPDATED` or `REVISED` per item. Try it on a copy (`_out/cat`) with the drafts from section 2.3: first run `ADDED` three times, second run `UNCHANGED` three times.

## 10. Dashboard workflows: Build Pattern

| Step | Action | Expected |
|---|---|---|
| 1 | Open `/patterns/new` | Description box, YAML spec box, list "Existing patterns" (P02, P03, P07, P08, P11 to P17) with state, and a "Spec format" help |
| 2 | Live only: describe "A remediation tool limited to an allow-list of actions on tagged hosts" and click **Draft spec with the agent** | A spec appears in the YAML box with the note "The agent drafted the spec below"; nothing is saved. Field names already in the library keep their exact schema, and `related_controls`/`related_risks` use catalog IDs only. Without a model the button is disabled |
| 3 | Offline: click **edit / copy** on an existing pattern, change the title and `pattern_id` to the suggested next free id (for example P18) and a new `slug` | Spec loaded in the box |
| 4 | Click **Validate and save as DRAFT** | Green box: `P18 created, v1`, badge PENDING HUMAN REVIEW, **Approve and publish** and "open in catalog". File `patterns/P18-<slug>.json` exists |
| 5 | Click **Validate and save as DRAFT** again with no change | Action is "unchanged"; version stays v1; the file is not rewritten |
| 6 | Click **Approve and publish** | State PUBLISHED, file status APPROVED. `/catalogs/patterns` shows P18 PUBLISHED. Overview Patterns counter went up by 1 |
| 7 | Open P02 with **edit / copy**, change the description, save | Action "revised", v2, state DRAFT again. A box "Composed from the previous version, so out of date until recomposed" lists the RAs composed from the old P02 (for example `RA03-LITE`) with a **Recompose RA03-LITE** button |
| 8 | Click **Recompose RA03-LITE** | Opens Build Reference Architecture with that RA loaded (section 11). Do not save it unless you want a new RA version |

Checks:
- **Bad spec:** an unknown node type, a `const` with no value, or a related control that is not in the catalog gives a red "Problems" list and nothing is written.
- **Field conflict:** reuse a library field name (for example `autonomy`) with a different enum. The save is rejected and names the existing definition.
- **Invalid YAML:** the page reports "invalid YAML" and keeps your text.
- Restore the files from `_out/backup` when you are done (9.0).

## 11. Dashboard workflows: Build Reference Architecture

| Step | Action | Expected |
|---|---|---|
| 1 | Open `/architectures/new` | RA id and description fields, "Limit to selected patterns" (only APPROVED/PUBLISHED patterns can be ticked), "Edit existing" buttons for each RA |
| 2 | Live only: RA id `RA06-CLAIMS`, description "An AI agent investigates security alerts and applies remediation to production hosts; each remediation can require analyst approval and every decision can be audited". Click **Generate with the agent** | About 20 seconds. The editor opens with an "Agent" box: "N round(s), composes and validates" (at most 4 rounds). Compose spec, questions and consistency rules are filled in. Known weakness: it may not balance `oneOf` choices well; edit the spec and repeat the preview |
| 3 | Offline: open an existing RA with **RA05-CYBER-REMEDIATION** under "Edit existing", change `ra_id` to `RA06-TEST` | Spec loaded |
| 4 | Click **Preview** | Green box: `RA06-TEST v1 composes from P08, P11, ...: N nodes, N relationships, N options, N questions; calm validate passed`. Nothing is written (check `templates/`). "What Generate CALM will ask for" lists the attributes and options |
| 5 | Break the spec (reference a pattern that is not published, or a field a pattern does not have) and Preview | Red "Not composable" list naming the problem. Nothing written |
| 6 | Click **Save as DRAFT** | "Saved (created)" with badge PENDING HUMAN REVIEW. Files `templates/RA06-TEST.json`, `.compose.yaml`, `.questions.yaml`, `.consistency.yaml` exist |
| 7 | Save again with no change | "unchanged"; no ra-version change |
| 8 | Change a description and save | ra-version 2 |
| 9 | Click **Approve and publish** | State PUBLISHED. `/catalogs/templates` lists it; Overview Reference Architectures counter is +1. Generate CALM (section 12) now offers `RA06-TEST` |

Questions are derived by rule: one per option, enum, number and boolean field. Edit them in the "Requirement questions" box if the wording is poor. Restore from `_out/backup` afterwards.

## 12. Dashboard workflows: Generate CALM

Uses the published RA03-LITE and RA05-CYBER-REMEDIATION. Steps that only use the questions work offline. Steps 3 and 6 call the Decider: use `DECIDER_PROVIDER=http` (live profile); with the fixture Decider they only work if a matching answer was recorded.

| Step | Action | Expected |
|---|---|---|
| 1 | Open `/applications/new` | Step 1 of 3. Application id, name, reference architecture drop-down (only PUBLISHED, with version and title), "What does the application do?" |
| 2 | Id `supplier-payments`, name `Supplier payments`, choose `RA03-LITE`, click **Continue to requirements** | Step 2. Header says the template was chosen by "you". One question per decision with radio buttons, plus "Not sure, I will describe it" |
| 3 | Go back, leave the template on "Choose for me from the description", write "Agents extract supplier invoices, match them to purchase orders and pay approved invoices" | Step 2 header says the template was chosen by the Decider with a confidence. A Decider answer below the policy threshold is refused with a message and you pick the template yourself |
| 4 | Answer: payment authorisation = a person approves every payment; payment agent autonomy = supervised; access = restricted-write; limit = 5000 (a number field); invoice agent autonomy = supervised; invoice data = confidential; model version = pinned; audit = yes. Click **Generate CALM and assess** | Redirect to the assessment report. Status COMPLETED, decision APPROVED_WITH_CONDITIONS (checked) |
| 5 | Scroll to "Inputs and requirements" | Every value and option with who set it: your answer, the Decider, or derived from an option |
| 6 | Describe it (live Decider): start again, leave "payment authorisation" on "Not sure, I will describe it" and write "payments go out straight away and we only get a report later" | The Decider maps the text to "The payment agent pays directly". The report's inputs section marks that value as set by the Decider. The expected decision is REJECTED (gate G2), as for V2. If the Decider is unsure the answer goes to human review instead |
| 7 | Contradiction: open "Advanced: template fields not covered by the questions", set `PAYMENT_AGENT_PAYMENT_APPROVAL_PATH` to `direct`, and answer "a person approves every payment" | Page stays on step 2 with HTTP 422 and "Not generated yet": `'direct' contradicts option opt-approval-path = payment-via-human-approval-service (requires 'via-human-approval')`. `calm generate` is not run and no assessment is created |
| 8 | Payment limit 200000 (everything else as in step 4) | Generation completes but CALM validation fails: assessment status BLOCKED, no decision, guidance points at `/nodes/payment-agent/metadata/payment_limit` (the V4 case) |

Checks:
- Leave an attribute empty that an option implies; it is derived from the option and shown as such in the report.
- Generate the same answers twice: both runs use the same template files (`templates/RA03-LITE.json` bytes and hash do not change).
- Open the generated model under `DATA_DIR/artifacts/<trace>/app_model/` and the `generation_manifest`: it records the template hash, option choices and attributes hash.

## 13. PENDING HUMAN REVIEW and Approve

The MVP has no login or role check. Every Approve button acts as `dashboard-reviewer` with role `governance_admin`, and the rationale is "approved in dashboard (MVP, no role check)". Role checks are in the backlog; the `/review` queue still enforces roles (section 7).

### 13.1 Catalog items

| Step | Action | Expected |
|---|---|---|
| 1 | Make a DRAFT: upload a document (section 9), or save a pattern or RA (sections 10, 11) | Item shows the badge PENDING HUMAN REVIEW in its catalog |
| 2 | Open `/catalogs/controls`, `/catalogs/risks`, `/catalogs/patterns` or `/catalogs/templates` and click **Approve** on the item | Controls and risks: APPROVED in the YAML catalog. Risks: the same click confirms the shown likelihood and impact. Patterns and RAs: APPROVED, then PUBLISHED in the lifecycle registry (history lists each transition) |
| 3 | Click Approve again (or POST the same URL) | HTTP 409 "<id> is <state>; nothing to approve", no change |
| 4 | Unknown id: `curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8001/catalogs/controls/NOPE/approve` | 404 |

### 13.2 A WAITING_FOR_HUMAN assessment

1. Set up the waiting run as in section 7.1 (offline policy edit) or 7.2 (live). The assessment status is WAITING_FOR_HUMAN.
2. Open `/assessments/<trace>`. The top of the report has a PENDING HUMAN REVIEW section with, for each open Decider task, a drop-down of the allowed values.
3. Choose `confidential` and click **Approve and resume assessment**.
4. Expected: the tasks are claimed and completed as `dashboard-reviewer`, the assessment resumes and the report shows COMPLETED with the decision (V1: APPROVED_WITH_CONDITIONS). "Inferred facts" lists the classification with the reviewer as the source.
5. Check: submit a value that is not in the allowed list (API: `curl -s -X POST http://127.0.0.1:8001/api/assessments/<trace>/approve -H 'content-type: application/json' -d '{"value__<task id>":"bogus"}'`). Expect HTTP 422 naming the allowed values and no change.
6. Restore `decider_policy.yaml` as in section 7.1.

## 14. Cyber remediation example (RA05-CYBER-REMEDIATION)

RA05 composes P08, P11, P12, P14, P15 and P16. It is built by `uv run python scripts/build_cyber.py` (idempotent: running it again changes nothing) and published. Use Generate CALM (section 12) with the template `RA05-CYBER-REMEDIATION`.

Answers for both variants (the questions are, in order: remediation release, agent autonomy, alert data sensitivity, model version, tool server, audit trail):

| Question | cyber-fixed | cyber-blocked |
|---|---|---|
| How is a remediation released to the production hosts? | A security analyst approves every action | The agent applies actions directly |
| Agent autonomy | Supervised | Autonomous |
| Alert data sensitivity | Confidential | Restricted |
| Model version | Pinned | Floating |
| Remediation tool server | Governed | Ungoverned |
| Audit trail | Yes | No |

| Variant | Expected assessment |
|---|---|
| cyber-fixed | COMPLETED, **APPROVED_WITH_CONDITIONS** (design-level evidence only). Risk profile Low, no risks triggered. Approval tier **High (Tier 2)**: action capability 4 (production change) with autonomy capped at 2 by the analyst approval path |
| cyber-blocked | COMPLETED, **REJECTED** through gate G2: control AIGF-MI-024 (human-in-the-loop for production changes) fails, and AIGF-RI-024 (production change without approval) and AIGF-RI-022 trigger (RI-005 and RI-018 also appear with these answers), so the risk profile is High. Approval tier **Critical (Tier 1)** from "Override 1: action_capability=4 and autonomy>=3". The report lists AIGF-MI-024 as failed (the reference run also lists AIGF-MI-021) |

With only the first and last answers changed (direct approval and no audit, the other four as in cyber-fixed) the decision is also REJECTED, with risk High (RI-022 and RI-024 triggered).

Checks:
- Contradiction: in Advanced set `REMEDIATION_AGENT_ACTION_APPROVAL_PATH` to `direct` and answer "A security analyst approves every action". The form is rejected as in section 12 step 7.
- Known gaps: the gate id is still `G2-PAYMENT-AUTH`, and the AIGF-RI-024 remediation text still mentions payments.
- This matches the scoring rubric in the hackathon demo guide (thresholds 17/13/9/5 and three overrides; `risk_tier.py`).

## 15. Responsive layout

Open the dashboard in a browser and use the developer tools to set the window width. Check `/overview`, `/rules/new`, `/applications/new`, an assessment report and a catalog page at each width.

| Width | Expected |
|---|---|
| Above 1100 px | Fixed left sidebar with Catalog and Architecture as collapsible groups; Overview shows the six metric cards in a grid; two-column forms |
| 1100 px and below | Narrower page padding; Overview cards in two columns; two-column areas become one column |
| 860 px and below | Sidebar moves to the top as a horizontal wrapping menu (brand hidden); groups open as drop-downs; content uses the full width |
| 600 px and below | Tighter padding; Overview in one column; search boxes and toolbar buttons fill the width; the question tables in Generate CALM stack (label above the answers); wide tables scroll sideways inside their card |

At every width: no horizontal scroll of the whole page, all menu items reachable, buttons usable, and the two labels "illustrative, not approved policy" and "design-level evidence only" still visible.

## 16. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `assessment_status: COMPLETED` but `decision: INDETERMINATE` | A Spectral lane failed (G3). Check `.tools/node_modules/.bin/spectral --version`. Use `--cli replay` to rule out the tool |
| Recorded runs fail after editing a ruleset or catalog | Offline Spectral recordings match the committed ruleset bytes. Restore the files, or use `--cli real` |
| `calm validate` errors | Validate against the template: `uv run python -m calm_generation validate <file> --template RA03-LITE` |
| Dashboard empty | The dashboard and CLI must use the same `DATA_DIR`. Run both from the repo root |
| `resume` says no waiting assessment | The run did not stop: `block_on_pending_human` was off, or no task was created |
| 403 on a review action | Role not allowed for that task type (section 0.3), or the actor created the subject (no self-approval) |
| Connection or model settings ignored (Bedrock, Decider) when you run from a framework folder (for example `governance-execution-framework/`) | `.env` is read from the current folder only. Run from the repo root, or set the values in the shell: `export AWS_PROFILE=<profile> BEDROCK_MODEL_ID=<model id> DECIDER_URL=http://<ec2-host>:8000 MODEL_PROVIDER=bedrock DECIDER_PROVIDER=http` |
| Recorded runs (`--cli replay`) fail after approving a catalog change in the dashboard, or after a ruleset recompile | The CLI recordings are keyed by ruleset bytes. Refresh them: `uv run python scripts/seed_recordings.py --record-cli` (needs real `calm` and `spectral`), then rerun the tests |
| The repo shows modified catalogs, rulesets, patterns, templates or `lifecycle.yaml` after using the dashboard | The UI writes directly into the repo files (sections 9 to 12). Restore from the backup made in 9.0, or review with `git diff` |
| Generate Rules shows "No model available and no recording" | `MODEL_PROVIDER` is not `bedrock` or `BEDROCK_MODEL_ID` is empty, and no recording exists for that document. Use the live profile |
| "Draft spec with the agent" or "Generate with the agent" is disabled | No model configured (same settings as above) |
| Risk likelihood/impact all marked low confidence | Expected with Nova-2-lite (about 0.45). Confirm by hand when approving, or use a stronger `BEDROCK_MODEL_ID`/Decider model |
| Decider call rejected by the server (schema error) | The platform request is translated to the Strands Decider format (`questions` as a name-keyed map with `type`, `instructions`, `criteria`) in `adapters/decider.py`. Check `DECIDER_URL` points at the Strands Decider and the server version matches |
| Generate CALM page lists no template | No PUBLISHED RA. Approve one in the CALM Patterns Catalog or build one (section 11) |
| A revised pattern leaves an RA out of date | Use the Recompose button on the Build Pattern result (section 10 step 7) and approve the new RA version |
