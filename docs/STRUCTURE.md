# Repository structure

## Rationale
The draft "foundation" layout (`src/agip/{legacy,core,...}`, top-level `catalogs/`, `rulesets/`, `fixtures/`) mixed three concerns. Each framework now owns its code, tests, data and docs in one top-level folder. Dependency direction (enforced by `tests/test_framework_boundaries.py`):

```
shared  <-  rule_authoring
shared  <-  calm_generation
shared, rule_authoring, calm_generation  <-  governance_execution
```

`shared` holds only cross-framework contracts. A single root `pyproject.toml` lists every `src` path, so `uv sync && uv run pytest` runs all tests.

## Old path -> new path
| Old | New |
|---|---|
| `src/agip/legacy/rule.py` | `shared/src/agip_shared/contracts.py` |
| `src/agip/legacy/calm_finos.py` | `calm_generation/calm_finos.py`, then removed in task 16 |
| `src/agip/legacy/risk_tier.py` | `governance-execution-framework/src/governance_execution/risk_tier.py` |
| `src/agip/legacy/{applicability,scoring,findings,pipeline}.py` | `governance_execution/`, then removed in task 16 |
| `src/agip/{core,adapters,units,store,exec,obs,dashboard}` | `governance-execution-framework/src/governance_execution/<same>` |
| `src/agip/gateway` | `shared/src/agip_shared/gateway/` (the empty `governance_execution/gateway` package was removed in task 16) |
| `src/agip/contracts`, `src/agip/__init__.py`, `src/agip/legacy/__init__.py` | dropped (superseded by `agip_shared`) |
| `catalogs/seed/registry.yaml`, `catalogs/seed/*-00N.yaml` | `rule-authoring-framework/catalogs/seed/`, then removed in task 16 (merged into `controls.catalog.yaml` and `risks.catalog.yaml`) |
| `rule-authoring/AUTHORING-GUIDE.md` | `rule-authoring-framework/docs/AUTHORING-GUIDE.md` |
| `rule-authoring/mi-*.md` | `docs/examples/`, then removed in task 16 |
| `rule-authoring/rule.yaml.j2`, `rule-authoring/transform.py` | `templates/rule.yaml.j2` and `rule_authoring/transform.py`, then removed in task 16 |
| `scripts/ingest_finos_mitigations.py` | `rule_authoring/ingest_finos.py`, then removed in task 16 (replaced by `rule_authoring/sources_aigf.py` and `ingest.py`) |
| `scripts/validate_calm_v12.py` | `calm_generation/validate_v12.py`, then removed in task 16 |
| `docs/VOCABULARY.md` | `calm-app-generation-framework/docs/VOCABULARY.md` |
| `fixtures/variants/*.json` | `calm-app-generation-framework/fixtures/variants/` |
| `fixtures/recordings/llm` | `rule-authoring-framework/fixtures/recordings/llm` |
| `fixtures/recordings/decider` | `governance-execution-framework/fixtures/recordings/decider` |
| `patterns/`, `templates/` | `calm-app-generation-framework/patterns/`, `.../templates/` |
| `rulesets/` | `rule-authoring-framework/rulesets/` |
| `forms/`, `prompts/`, `config/` | `governance-execution-framework/{forms,prompts,config}/` |
| `tests/legacy/test_risk_tier.py` | `governance-execution-framework/tests/test_risk_tier.py` |
| `tests/legacy/test_rule_schema.py`, `test_task3_aigf_ccc_rules.py` | moved to `rule-authoring-framework/tests/`, then removed in task 16 with the seed catalog |
| `tests/unit/test_consistency_guards.py` | `tests/test_consistency_guards.py` (scans all frameworks) |
| `tests/unit/test_framework_boundaries.py` | `tests/test_framework_boundaries.py` |
| `tests/unit/test_smoke.py` | replaced by `tests/test_import_all_modules.py` |
| `tests/{golden,integration,property}` | `governance-execution-framework/tests/` |
| `docs/copy-manifest.txt` | merged into `docs/REUSE.md`, removed |

## Added after task 16 (no draft-repo origin)
| Path | Role |
|---|---|
| `shared/src/agip_shared/versioned_write.py` | Hash rule: `.versions` sidecar index per folder (`inputs_hash` skips regeneration, `content_hash` raises the version) |
| `rule-authoring-framework/src/rule_authoring/upload.py` | Uploaded `.md`/`.markdown`/`.yaml`/`.yml` to source items (Generate Rules) |
| `rule-authoring-framework/src/rule_authoring/merge.py`, `versioning.py` | Merge DRAFTs into the catalogs under the hash rule (`python -m rule_authoring.merge`); catalog writes keep the YAML comment header |
| `rule-authoring-framework/src/rule_authoring/scoring.py` | `DeciderScorer`: risk likelihood and impact from the Strands Decider; recordings in `fixtures/recordings/decider-scores` |
| `rule-authoring-framework/prompts/extraction.v1.md`, `extraction.v2.md` | Extraction prompts; the runtime appends the allowed Scoring_Profile dimensions and taxonomy fields |
| `calm-app-generation-framework/src/calm_generation/pattern_builder.py`, `ra_agent.py`, `ra_builder.py`, `questions.py` | Build Pattern, Build Reference Architecture and Generate CALM support |
| `calm-app-generation-framework/patterns/P15-*.json`, `P16-*.json`, `P17-new-pattern.json` | High-Impact Action Approval, Controlled Remediation, and a pattern created from the UI |
| `calm-app-generation-framework/templates/<RA>.{compose,questions,consistency}.yaml`, `RA05-CYBER-REMEDIATION.*` | Per-RA compose spec, requirement questions and implied attributes; the cyber remediation RA |
| `governance-execution-framework/src/governance_execution/dashboard/routers/{rules,architecture,mvp}.py` | Generate Rules; Build Pattern and Build Reference Architecture; overview, review, Generate CALM, approve endpoints |
| `scripts/build_cyber.py` | Idempotent build of P15, P16 and the cyber catalog rules and rulesets |
## Dropped
- `.fix3.sh` (one-off helper), empty `.gitkeep` placeholders in directories that now hold files.
- `src/agip` package namespace and `tests/legacy`, `tests/unit` directories (all contents moved or replaced above).
- `demo_2` validation in `validate_v12` (module not copied).
- Evaluator and calm-guard bridge references in `pipeline.py` (evaluator is injected).
- Task 16 removed `pipeline.py`, `applicability.py`, `findings.py`, `scoring.py`, `calm_finos.py`, `validate_v12.py`, `ingest_finos.py`, `transform.py`, `catalogs/seed/` and the empty `governance_execution/gateway/` package.
