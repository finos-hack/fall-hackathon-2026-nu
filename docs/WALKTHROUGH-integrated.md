# Integrated walkthrough (13 steps, Git Bash, offline), then the dashboard path and the cyber example

The same journey that `tests/test_integrated_e2e.py` runs, as shell commands. Run everything from the platform root in Git Bash.
Scoring and severity labels are "illustrative, not approved policy"; Spectral passes are "design-level evidence only".
There is no Fluxnova or other workflow engine: human tasks live in the `HumanTaskStore` files under the data dir.
Steps 1-13 use the command line on a scratch copy. "Dashboard end-to-end path" below does the same journey through the web pages, which write straight into the repo files.

```bash
cd "/c/Users/User1/projects/personal/in progress/finos-hackathon-2026/ai-governance-intelligence-platform"
uv sync --quiet
export WS=/tmp/agip-ws                      # scratch workspace; repo catalogs, rulesets and registry stay untouched
mkdir -p $WS/catalogs $WS/data
cp rule-authoring-framework/catalogs/{controls,risks}.catalog.yaml $WS/catalogs/
cp calm-app-generation-framework/registry/lifecycle.yaml $WS/lifecycle.yaml
export DECIDER_PROVIDER=fixture MODEL_PROVIDER=replay   # recorded LLM and Decider outputs
```

Every command below was checked with `--help` (flags as listed). `python -m governance_execution.dashboard.app` has no argparse and
starts the server directly, so it was not run with `--help`.

## Rule Authoring (steps 1-4)

### 1. Ingest
Needs the `../ai-governance-framework` and `../common-cloud-controls` checkouts.
```bash
uv run python -m rule_authoring.ingest --source aigf --path ../ai-governance-framework --out $WS/catalogs/sources/aigf.json
uv run python -m rule_authoring.ingest --source ccc  --path ../common-cloud-controls   --out $WS/catalogs/sources/ccc.json
```

### 2. Extract (replay, no LLM call)
Adds `--extract` to write DRAFT rules from the recorded model output. Inexpressible items (for example `CCC.Core.CN01`) are kept with a reason.
```bash
for s in "aigf ../ai-governance-framework" "ccc ../common-cloud-controls"; do set -- $s
  uv run python -m rule_authoring.ingest --source $1 --path $2 --out $WS/catalogs/sources/$1.json \
    --extract --provider replay --recordings rule-authoring-framework/fixtures/recordings/llm --drafts $WS/catalogs/drafts
done
uv run python -m rule_authoring.coverage --format table
```
Live extraction (Bedrock, not needed offline): add `--provider bedrock`. It runs at temperature 0.1 with Strands steering (`--temperature`, `--steering-retries`, default 2). A candidate rule must test a taxonomy field, otherwise the item is kept as inexpressible with the reason. Risk likelihood and impact come from the Strands Decider (`--scores decider`, default; `--scores llm` uses the model scores). Documents that did not change (same input, prompt, model and parameters) are not sent to the model again.
Merge: `uv run python -m rule_authoring.merge --drafts $WS/catalogs/drafts --catalogs $WS/catalogs` adds each draft to the catalogs as DRAFT (new), leaves unchanged items alone, and makes a changed APPROVED item a DRAFT with version +1 while the approved version stays in force.
Review: copy a draft (for example `$WS/catalogs/drafts/CCC.Core.CN02.json`) into the matching `$WS/catalogs/*.catalog.yaml` as a DRAFT item.
The tests do this with `rule_authoring.extraction.to_catalog_entry`; the `merge` command above is the CLI route for the copy.

### 3. Approve (risks need an explicit confirm)
```bash
C=$WS/catalogs/controls.catalog.yaml; R=$WS/catalogs/risks.catalog.yaml
uv run python -m rule_authoring.approval submit  CCC.Core.CN02 --by alice --role reviewer --rationale checked --catalog $C
uv run python -m rule_authoring.approval approve CCC.Core.CN02 --by bob   --role approver --rationale ok      --catalog $C
uv run python -m rule_authoring.approval submit  CCC.Core.TH01 --by alice --role reviewer --rationale checked --catalog $R
uv run python -m rule_authoring.approval approve CCC.Core.TH01 --by bob --role approver --rationale ok --catalog $R   # refused: confirm first
uv run python -m rule_authoring.approval confirm  CCC.Core.TH01 --by bob --role approver --rationale "scores reviewed" --catalog $R
uv run python -m rule_authoring.approval approve CCC.Core.TH01 --by bob --role approver --rationale ok --catalog $R
```

### 4. Compile (deterministic: same catalogs, same bytes)
```bash
uv run python -m rule_authoring.compile --catalogs $WS/catalogs --out $WS/rulesets --strict
cat $WS/rulesets/MANIFEST.yaml        # per-ruleset version, rule count and sha256
```
Unchanged rules leave the ruleset bytes alone. A change raises the `version:` at the top of the catalog, which is the ruleset header version (repo rulesets are at version 2: controls 15 rules, risks 7).
The extra rules from step 3 change the ruleset bytes. The recorded `calm`/`spectral` outputs used in steps 8-13 are keyed by ruleset
content, so assess with the repo's approved rulesets (`rule-authoring-framework/rulesets`, which an unmodified catalog compiles to byte for byte).
With real `calm` and `spectral` on PATH you can assess with `$WS/rulesets` and drop `--cli replay`.

## CALM Generation (steps 5-7)

### 5. Approve patterns (calm_generation lifecycle)
The patterns (P02, P03, P07, P08, P11 to P17; P02 is v2) are already PUBLISHED. The test resets them to DRAFT in the registry copy and walks each one through
`submit`, `approve`, `publish` (shown for P13; repeat per pattern id from `calm_generation patterns`). The CLI has no state reset, so on
a fresh copy a pattern in PUBLISHED can only go to `deprecate`.
```bash
uv run python -m calm_generation --registry $WS/lifecycle.yaml patterns
uv run python -m calm_generation --registry $WS/lifecycle.yaml submit  P13 --by dana --role architect --rationale reviewed
uv run python -m calm_generation --registry $WS/lifecycle.yaml approve P13 --by dana --role architect --rationale reviewed
uv run python -m calm_generation --registry $WS/lifecycle.yaml publish P13 --by dana --role architect --rationale reviewed
```
(These three are accepted only while P13 is DRAFT. Against the untouched PUBLISHED copy they are refused with a transition error.)

### 6. Publish RA03-LITE (ra-version 2)
```bash
uv run python -m calm_generation --registry $WS/lifecycle.yaml versions
uv run python -m calm_generation --registry $WS/lifecycle.yaml compose --out $WS/RA03-LITE.json   # recomposes the template from published patterns
uv run python -m calm_generation --registry $WS/lifecycle.yaml form RA03-LITE --out $WS/blank-form.yaml   # only for a PUBLISHED template
```
For a DRAFT template: `submit`, `approve`, `publish` with `RA03-LITE` as the id, as in step 5.

### 7. Instantiate V1
Copy `governance-execution-framework/forms/v1.attributes.yaml` values into the blank form (the `app`, `values` and `options` blocks), then:
```bash
uv run python -m calm_generation --registry $WS/lifecycle.yaml instantiate --form $WS/v1-form.yaml --out $WS/v1.json
# prints: VALID app=invoice-lite-v1 sha256=...   (needs the real `calm` CLI; the tests stub it)
```
Offline alternative: use the stored V1 model, `calm-app-generation-framework/fixtures/variants/invoice-lite-v1.json`
(identical to what the recorded `calm generate` produces; the e2e test asserts that).

## Governance Execution (steps 8-13)

### 8. Assess (V1 to V4)
```bash
V=calm-app-generation-framework/fixtures/variants
for n in 1 2 3 4; do
  uv run python -m governance_execution assess $V/invoice-lite-v$n.json --mode no-llm --cli replay --decider fixture \
    --catalogs rule-authoring-framework/catalogs --rulesets rule-authoring-framework/rulesets \
    --template RA03-LITE --data-dir $WS/data | tee $WS/assess-v$n.json
done
```
Exit codes: 0 COMPLETED, 3 BLOCKED, 4 WAITING_FOR_HUMAN, 2 FAILED. Expected (from `fixtures/variants/expected.yaml`):
V1 APPROVED_WITH_CONDITIONS, V2 REJECTED (gate G2-PAYMENT-AUTH), V3 RESTRICTED, V4 BLOCKED with no decision (invalid CALM at `/nodes/payment-agent/metadata/payment_limit`).
Use `--mode normal` to run the recorded remediation LLM output as well.

### 9. Accept a classification
The Decider (fixture) classifies `invoice-db.data_classification`; policy accepts it, so the fact is INFERRED and carries a `classification_ref`.
```bash
T=$(python -c "import json;print(json.load(open('$WS/assess-v1.json'))['trace_id'])")
uv run python -m governance_execution show $T --data-dir $WS/data     # steps, artifact kinds, versions
ls $WS/data/artifacts/$T/                                              # facts, decider_calls, ...
```

### 10-11. Evaluate controls and risks, decide
`show` lists `control_gap`, `risk_profile`, `decision` among the artifacts; each is a JSON file under `$WS/data/artifacts/<trace>/`.
```bash
T2=$(python -c "import json;print(json.load(open('$WS/assess-v2.json'))['trace_id'])")
uv run python -m governance_execution show $T2 --data-dir $WS/data    # gates_fired: G2-PAYMENT-AUTH; decision REJECTED
```

### 12. Complete a human task (`block_on_pending_human`)
Set `block_on_pending_human: true` and `tasks.classify_attribute.on_fail: HUMAN_REVIEW` in `governance-execution-framework/config/decider_policy.yaml`
(a working-copy edit; revert afterwards) and use a Decider that answers with low confidence (`DECIDER_PROVIDER=http` against your Decider endpoint).
The assessment then stops after facts.
```bash
uv run python -m governance_execution assess $V/invoice-lite-v1.json --mode no-llm --cli replay --data-dir $WS/data
# exit 4, assessment_status WAITING_FOR_HUMAN, pending_human_tasks: [<task id>]
```
Start the dashboard (step 13), open `http://127.0.0.1:8001/review`, claim and complete the task as role `risk_analyst`, or call the same API:
```bash
curl -s -X POST http://127.0.0.1:8001/api/review/<task id>/act -H 'content-type: application/json' \
  -d '{"actor":"alice","role":"risk_analyst","action":"CLAIM","rationale":"taking it"}'
curl -s -X POST http://127.0.0.1:8001/api/review/<task id>/act -H 'content-type: application/json' \
  -d '{"actor":"alice","role":"risk_analyst","action":"COMPLETE","rationale":"classified by hand","outcome_artifact_id":"<allowed value>"}'
uv run python -m governance_execution resume <trace id> --mode no-llm --cli replay --data-dir $WS/data   # COMPLETED with a decision
```
(`<allowed value>` is in the task's `context.allowed_values`, shown on the review page. Choose REJECT instead of COMPLETE to leave the fact UNMAPPED; the assessment still decides.)

### 13. Inspect execution and lineage, then replay
```bash
DATA_DIR=$WS/data uv run python -m governance_execution.dashboard.app      # http://127.0.0.1:8001 (Ctrl+C stops)
#   /assessments/<trace>/execution     step timeline, Decider outcomes, human tasks
#   /assessments/<trace>/trace         decision -> gate -> control/risk -> Rule_Code -> CALM element -> pattern -> source
#   /lineage/source/AIGF:mi-24         source -> catalog item -> assessments (and back)
uv run python -m governance_execution replay $T --cli replay --data-dir $WS/data    # identical: true, exit 0
```
The shortcut `bash scripts/demo.sh` compiles the rulesets, assesses V1-V4 and starts the same dashboard
(`uv run python -m governance_execution.dashboard.app`, port 8001) against the default data dir.

## Dashboard end-to-end path

The same journey through the web pages. Start the dashboard from the repo root with the live profile for the agent steps (`MODEL_PROVIDER=bedrock`, `BEDROCK_MODEL_ID`, `DECIDER_PROVIDER=http`, `DECIDER_URL`; see `functional_manual_testing.md` section 0.2). Without a model you can still do every step except the agent drafts.
These pages write into `rule-authoring-framework/catalogs` and `rulesets`, and into `calm-app-generation-framework/patterns`, `templates` and `registry`. Back them up first (functional_manual_testing.md, section 9.0).

```bash
DATA_DIR=_out/data uv run python -m governance_execution.dashboard.app      # http://127.0.0.1:8001
```

| # | Page (sidebar) | What you do | What you see |
|---|---|---|---|
| 1 | Generate Rules `/rules/new` | Upload a Markdown control or an AIGF `ri-`/`mi-` file (UTF-8, 1 MB, 20 items per run) | A run page `/rules/runs/<run>`: each item is a DRAFT with a candidate Spectral rule, likelihood/impact (risks, with Decider confidence) and the badge PENDING HUMAN REVIEW |
| 2 | Run page | **Approve** each item (a risk click also confirms likelihood and impact), then **Compile rulesets** | Items APPROVED. Ruleset table with version, rule count and SHA-256 (the version rises only when rules changed). Uploading the same file again changes nothing |
| 3 | Build Pattern `/patterns/new` | Describe a pattern and **Draft spec with the agent** (or edit YAML), **Validate and save as DRAFT**, **Approve and publish** | Pattern file and registry entry, state PUBLISHED. Saving an unchanged spec writes nothing. Revising a published pattern lists the RAs built from the old version with a Recompose button |
| 4 | Build Reference Architecture `/architectures/new` | RA id and description, **Generate with the agent** (published patterns only; up to 4 compose-and-validate rounds), **Preview**, **Save as DRAFT**, **Approve and publish** | Template, compose, questions and consistency files. Preview writes nothing |
| 5 | Generate CALM `/applications/new` | App id and name, pick the RA (or let the Decider choose from the description), answer the requirement questions ("Not sure, I will describe it" lets the Decider map a sentence) | A contradiction between an attribute and an option is rejected before `calm generate`. Otherwise CALM is generated from the shared template, validated and assessed |
| 6 | Assessment report `/assessments/<trace>` | Read the decision, gates, controls, risks and the "Inputs and requirements" section (who set each value) | V1-like answers give APPROVED_WITH_CONDITIONS, a direct payment gives REJECTED (G2), an invalid value gives BLOCKED |
| 7 | Report, if status is WAITING_FOR_HUMAN | Choose a value for each open Decider task and click **Approve and resume assessment** | Tasks are claimed and completed as the MVP reviewer, the assessment resumes and COMPLETES with a decision |

There is no login yet: every Approve acts as `dashboard-reviewer` / `governance_admin`. Role checks are in the backlog. Detailed test steps with expected results are in `functional_manual_testing.md`, sections 9 to 15.

## Cyber remediation example (RA05-CYBER-REMEDIATION)

A second reference architecture for an AI agent that remediates security alerts on production hosts. It composes P08, P11, P12, P14 and the two new patterns P15 High-Impact Action Approval and P16 Controlled Remediation. It adds catalog rules AIGF-MI-024 (human approval for production changes, mandatory, gate G2 rejects when it fails), AIGF-MI-018 (remediation scope) and AIGF-RI-024 (production change without approval). `uv run python scripts/build_cyber.py` rebuilds all of it and is idempotent.

In Generate CALM (step 5 above) choose `RA05-CYBER-REMEDIATION` and answer the six questions. The risk tier follows the hackathon scoring rubric (thresholds 17/13/9/5 and three overrides):

| App | Key answers | Result |
|---|---|---|
| cyber-fixed | Analyst approves every action; supervised; confidential data; pinned model; governed tool server; audit trail | COMPLETED, APPROVED_WITH_CONDITIONS. Risk profile Low. Approval tier High (Tier 2) |
| cyber-blocked | Agent applies actions directly; autonomous; restricted data; floating model; ungoverned tool server; no audit | REJECTED through gate G2 (AIGF-MI-024 fails). AIGF-RI-024 and AIGF-RI-022 triggered, risk profile High. Approval tier Critical (Tier 1, Override 1: action capability 4 with autonomy 3 or higher) |

Known: the gate id is still `G2-PAYMENT-AUTH` and the AIGF-RI-024 remediation text still mentions payments.

## Automated equivalents
`uv run pytest -q tests/test_integrated_e2e.py tests/test_cross_framework_contracts.py`
