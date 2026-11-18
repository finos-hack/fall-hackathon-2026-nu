# Rule Authoring walkthrough (independent of CALM Generation and Governance)

Git Bash, from `ai-governance-intelligence-platform/`. Checkouts `../ai-governance-framework` and `../common-cloud-controls`.
Executable proof: `python -m pytest rule-authoring-framework/tests/test_journey.py`.

```bash
cd rule-authoring-framework
export PYTHONPATH=src
R=fixtures/recordings/llm

# 1. Ingest and extract from recordings (replay needs no model; bedrock is not required)
python -m rule_authoring.ingest --source aigf --path ../../ai-governance-framework --extract --provider replay --recordings $R
python -m rule_authoring.ingest --source ccc  --path ../../common-cloud-controls  --extract --provider replay --recordings $R
#    Drafts land in catalogs/drafts/. Inexpressible items (e.g. CCC.Core.CN01) are stored and reported.
#    Live run (needs AWS and the Decider): --provider bedrock uses temperature 0.1 and Strands steering
#    (--temperature, --steering-retries N). AIGF risk likelihood/impact come from the Decider (--scores decider, the
#    default); use --scores llm to keep the model's scores. Rule_Codes of AIGF items are set by code.
#    In replay, Decider scores are read from <recordings dir>/../decider-scores; where none is recorded the model's
#    scores are kept and the reason is stored in the entry's `scoring` block.

# 2. Merge the reviewed drafts into the catalogs (hash rule). Prints ADDED, UNCHANGED, UPDATED or REVISED per item.
python -m rule_authoring.merge                      # all drafts; or --ids AIGF-RI-001 ...; --drafts DIR --catalogs DIR
#    New items are DRAFT. A changed APPROVED item becomes DRAFT at version + 1 and its approved version stays in force
#    (previous_approved) until the new one is approved. Edit fields in the catalog YAML if the draft needs changes.

# 3. Submit, confirm (risks only), approve
python -m rule_authoring.approval submit  CCC.Core.CN02 --by alice --role reviewer --rationale checked
python -m rule_authoring.approval confirm CCC.Core.TH01 --by bob --role approver --rationale "scores reviewed"
python -m rule_authoring.approval approve CCC.Core.CN02 --by bob --role approver --rationale ok

# 4. Compile (deterministic; run twice and diff). Unchanged rules leave the ruleset bytes alone; changed rules raise the
#    catalog's top-level `version:` and the ruleset's `# version:` header by one.
python -m rule_authoring.compile --strict

# 5. Run Spectral on an independent CALM fixture (needs the spectral CLI)
spectral lint -r rulesets/controls.spectral.yaml ../calm-app-generation-framework/fixtures/variants/invoice-lite-v1.json

# 6. Lineage and coverage: rule_code -> catalog item -> source id -> source path
python -m rule_authoring.coverage --format table
```

## Dashboard path (Generate Rules)

The same steps run from the dashboard, without the checkouts. From the repo root:

```bash
uv run python -m governance_execution.dashboard.app      # http://127.0.0.1:8001
```

1. Open **Generate Rules** (`/rules/new`). Upload `.md` / `.markdown` control documents (AIGF `ri-*`/`mi-*` files keep
   their AIGF IDs; any other Markdown becomes `UPL-<id>`) or `.yaml` / `.yml` CCC fragments. UTF-8, 1 MB per file,
   20 items per run; PDF and Word are rejected.
2. The page extracts each item like the CLI (Bedrock with temperature 0.1 and steering when `MODEL_PROVIDER=bedrock`,
   otherwise recordings only), scores risks with the Decider, and merges the drafts into the main catalogs as DRAFT
   (the same merge as step 2 above). It opens `/rules/runs/<run_id>`, kept in `<data>/rule-runs/<run_id>/`.
3. Items show PENDING HUMAN REVIEW. **Approve** is the MVP direct approval (recorded as `dashboard-reviewer`, role
   `governance_admin`, no role check); for a risk it also confirms the proposed likelihood and impact.
4. **Compile rulesets** runs the consistency check and the compile (step 4 above) and shows the new ruleset versions.

Details: `AUTHORING-GUIDE.md`, Part B.
