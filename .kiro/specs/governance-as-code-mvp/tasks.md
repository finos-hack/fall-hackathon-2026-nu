# Implementation Plan: Governance-as-Code MVP

## Overview

Python 3.12 (pytest + hypothesis) in the NEW repo `c:\Users\User1\projects\personal\in progress\finos-hackathon-2026\ai-governance-intelligence-platform`. Numbering follows the design Build Order for tasks 0 to 3 (task N = step N). Design step 3 (Rule authoring) is split into tasks 3, 4 and 5 by dependency, so from task 6 onward task N = design step N-2. Mapping: design step 3 = tasks 3-5; step 4 = task 6; step 5 = task 7; step 6 = task 8; step 7 = task 9; step 8 = task 10; step 9 = task 11; step 10 = task 12; step 11 = task 13; step 12 = task 14; step 13 = task 15. Design checkpoints (after steps 0, 3, 6, 9, 10) map to CP0, CP5, CP8, CP11, CP12 (CP4 is an extra checkpoint after the gateway and approval work). All commands run in Git Bash on Windows (`uv sync && uv run pytest`). Never modify the draft repo `cyber-grc-finos-framework/design-time-agent-security`. CLI flags, output shapes and REST paths come from `docs/spike-notes.md` (task 1), not from the Proposal. Property tests: `max_examples=100`, tag `# Feature: governance-as-code-mvp, Property N: <title>`. Golden/replay/no-LLM/favourable-Decider tests run on recorded LLM and Decider outputs with no Bedrock, Decider or Fluxnova.

## Tasks

- [x] 0. [P0 -> 20.2] Scaffold repo and copy draft modules
  - [x] 0.1 Scaffold `ai-governance-intelligence-platform` (existing `.git` only): `pyproject.toml` (uv, pytest, hypothesis, fastapi, jinja2, pyyaml, pydantic, opentelemetry), directory layout from the design, empty `config/`, `catalogs/`, `rulesets/`, `fixtures/`, and a documented Git Bash install-and-test command
    - _Requirements: 1.1, 1.6_
  - [x] 0.2 [P0 -> 20.2] Copied the listed draft modules, rule files, VOCABULARY, examples, scripts, `rule-authoring/` and dependent tests from the draft repo (draft repo never modified) into the new repo, then moved them within the new repo into `shared/`, `rule-authoring-framework/`, `calm-app-generation-framework/` and `governance-execution-framework/` per the reuse map and `docs/STRUCTURE.md`; fixed imports only; do not copy `src/agent`, `demo*.py`, `agent_runtime.py`, AgentCore files, `uv.lock`, `evaluator.py`
    - _Requirements: 1.1, 1.2_
  - [x] 0.3 [P1 -> 28.2] Write `docs/REUSE.md` (file, source path, draft commit hash, new role); run copied tests and list failures with reasons as a deliberate-change list (kept for `spike-notes.md`)
    - _Requirements: 1.3, 1.4_
  - [x] 0.4 [P0 -> 20.2] Add consistency test that fails if any code path uses `risk_tier.py` output or summed Dimension values to set a severity, and that no `calm-guard`/draft-repo dependency exists
    - _Requirements: 1.2, 1.5_

- [x] CP0. [P0 -> 20.2] Checkpoint after step 0 - Ensure all tests pass, ask the user if questions arise.

- [ ] 1. [P1 -> 27.1, 28.2] Tooling spike (each task writes its own fragment under `docs/spike/`)
  - [x] 1.1 CALM spike script + notes: CLI version; `calm validate -a` / `-p ... -f json` shapes for valid, warning-only, invalid (VALID = `hasErrors` false); `calm generate` twice byte-identity and placeholder forms; validate draft examples for `ai:*` node types and custom verbs; record the metadata/`connects` fallback if rejected
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.10_
  - [x] 1.2 [P1 -> 28.2] Spectral spike: version and `spectral lint <file> -r <ruleset> -f json` output on a CALM JSON file (exit-code behaviour, result fields)
    - _Requirements: 2.5, 2.10_
  - [x] 1.3 Decider spike: one `POST /v1/systemone` and `GET /health` at `localhost:8000`; record request, response, client latency; record fallback if down
    - _Requirements: 2.6, 2.10_
  - [x] 1.4 py-pglite spike: TCP mode on Windows port 5433, persistence across restart; record YAML-seed/SQLite contingency
    - _Requirements: 2.7, 2.10_
  - [ ] 1.5 [P2 -> 21.2] Bedrock spike: model access from configured region via Strands; record contingency (`provider: none/replay`)
    - _Requirements: 2.9, 2.10_
  - [ ] 1.6 [P1 -> 27.1] Fluxnova spike (hard 30-minute limit): Docker `finos/fluxnova-bpm-platform:latest` on 8080; confirm `/engine-rest` paths for deployment, external-task fetch-and-lock, complete, failure, user tasks; record pass/fail
    - _Requirements: 2.8, 2.10, 22.3_
  - [x] 1.7 [P1 -> 28.2] Assemble `docs/spike-notes.md` from fragments plus the deliberate-change list from 0.3; state chosen contingencies and the Executor decision (Fluxnova vs Direct_Adapter)
    - _Requirements: 1.4, 2.10, 2.11, 22.4_

- [~] 2. [P0 -> 20.2] Contracts, store, adapters, observability
  - [x] 2.1 `shared/src/agip_shared/contracts.py`: AgentTask, AgentResult, Artifact, Fact, FactSet, SpectralRun, ControlGapAssessment, RiskProfile, Decision, DeciderResult, Extraction_Record (Pydantic; artifact IDs only)
    - _Requirements: 21.1, 21.3_
  - [x] 2.2 `shared/src/agip_shared/hashing.py` (canonical JSON, SHA-256, Input_Hash) and `shared/src/agip_shared/paths.py` (`resolve_within(data_dir, p)`; reject `..`, absolute, symlink escapes)
    - _Requirements: 9.5, 12.3, 15.2, 23.3_
  - [x] 2.3 [P0 -> 20.2] Property test for path containment
    - **Property 22: Path containment**
    - **Validates: Requirements 12.3**
  - [x] 2.4 `governance-execution-framework/src/governance_execution/store/` (py-pglite TCP 5433, `schema.sql`, immutable artifact files at `data/artifacts/<trace>/<kind>/<id>.json` with SHA-256, YAML seed + file export fallback, SQLite last resort per spike)
    - _Requirements: 23.1, 23.2, 23.3, 23.5_
  - [x] 2.5 `governance-execution-framework/src/governance_execution/adapters/calm.py` CALM_Adapter: `generate`, `validate(pattern?, arch)` returning VALID/INVALID/ERROR with errors (`code,severity,message,path`) and warnings; list args, temp dir, timeout, records version/exit code/duration; flags from spike notes
    - _Requirements: 10.1, 11.1, 11.2, 11.3, 11.4, 11.5_
  - [x] 2.6 `governance-execution-framework/src/governance_execution/adapters/spectral.py` Spectral_Adapter: `lint(app, ruleset) -> SpectralRun(OK|ERROR, results, version)`; parses JSON per spike (not exit code); list args, temp dir, timeout; keeps raw + parsed
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5_
  - [x] 2.7 `governance-execution-framework/src/governance_execution/obs/otel.py`: one trace per assessment (console/file), span per stage, Trace_ID on artifacts, secret scrubbing; `versions` recorder for all versioned inputs
    - _Requirements: 23.4, 24.1, 24.5, 12.5_
  - [x] 2.8 [P0 -> 20.2] Unit tests for both adapters with stubbed CLIs (missing tool, timeout, unparsable output -> ERROR, never VALID; warnings-only -> VALID; list args)
    - _Requirements: 11.1-11.5, 16.2-16.4_
  - [ ]* 2.9 [P1 -> 20.3] Integration smoke tests (skip when tool absent): `calm` valid/warning/invalid and generate twice byte-identical; `spectral lint` on a CALM file; py-pglite persistence
    - _Requirements: 2.1, 2.2, 2.5, 2.7_

- [~] 3. [P0 -> 21.1] Rule authoring: source adapters
  - [x] 3.1 `rule-authoring-framework/src/rule_authoring/sources_aigf.py`: read `ri-*.md`/`mi-*.md` frontmatter -> native ID, title, references; report path+field and skip malformed files; deterministic
    - _Requirements: 3.1, 3.4, 3.5, 3.3_
  - [x] 3.2 [P0 -> 21.1, 21.5] `rule-authoring-framework/src/rule_authoring/sources_ccc.py`: read controls/threats/capabilities YAML for `core/core` and `ai-ml/multi-agent-refarch` (use only 1-2 CCC controls in the MVP); same error handling
    - _Requirements: 3.2, 3.3, 3.4, 3.5_
  - [x] 3.3 [P0 -> 20.2] Unit tests for both adapters (malformed frontmatter/YAML skipped with path+field, identical output on repeat)
    - _Requirements: 3.4, 3.5_

- [x] 4. Model gateway and rule extraction/approval
  - [x] 4.1 `shared/src/agip_shared/gateway/model_gateway.py` + `recorder.py` + `runtime_strands.py`: providers `bedrock|none|replay`; configurable provider/model/region; strips secrets and file paths; persists Extraction_Record (prompt version, model, input hash, output); Strands types only in the runtime adapter
    - _Requirements: 4.1, 4.5, 4.7, 12.5, 21.2_
  - [x] 4.2 `governance-execution-framework/src/governance_execution/units/rule_authoring.py` extract (wrapping `rule-authoring-framework/src/rule_authoring/extraction.py`): `rule-authoring-framework/prompts/extraction.v1.md`, schema-validate (triggers, likelihood, impact, remediation, candidate Spectral rule), store as DRAFT, reject invalid with reason; use recorded outputs by default
    - _Requirements: 4.1, 4.2, 4.5, 4.6_
  - [ ]* 4.3 [P2 -> 21.2] Stretch: live re-extraction via Bedrock stored as a new DRAFT (never auto-approved)
    - _Requirements: 4.6_
  - [x] 4.4 Approval function (`rule-authoring-framework/src/rule_authoring/approval.py`) + CLI (`approve <id> --by`): DRAFT -> APPROVED with approver and timestamp; compile accepts APPROVED only
    - _Requirements: 4.3, 4.4_

- [x] CP4. [P0 -> 20.2] Checkpoint after gateway and approval - Ensure all tests pass, ask the user if questions arise.

- [x] 5. [P0 -> 20.2, 21.5] Catalogs, consistency and compile
  - [x] 5.1 [P0 -> 20.2] Merge draft `rule-authoring-framework/catalogs/seed/registry.yaml` + `rule-authoring-framework/catalogs/seed/rules/*.yaml` into `rule-authoring-framework/catalogs/controls.catalog.yaml` and `rule-authoring-framework/catalogs/risks.catalog.yaml` (one definition each, non-empty remediation, source refs, likelihood/impact 1-5, mandatory flags); write `governance-execution-framework/config/scoring_profile.yaml`, `gap_rule.yaml`, `gates.yaml` (G1 CALM invalid, G2 payment authorization, G3 unevaluable), `decision_matrix.yaml`, `taxonomy.yaml` from the design
    - _Requirements: 5.1, 5.2, 5.3, 5.5, 18.2, 19.1, 19.2_
  - [x] 5.2 `rule-authoring-framework/src/rule_authoring/consistency.py`: fail on duplicate or undefined Rule_Code and on conflicting definitions across sources, reporting both locations
    - _Requirements: 5.6, 5.7_
  - [x] 5.3 [P0 -> 21.5] `rule-authoring-framework/src/rule_authoring/compile.py`: catalogs -> `rule-authoring-framework/rulesets/controls.spectral.yaml`/`risks.spectral.yaml` (seed APPROVED recorded extractions via the approval function first; APPROVED only, sorted keys, version, SHA-256, core functions first, Custom_Function list with reasons under `rule-authoring-framework/rulesets/functions/`, inexpressible rules reported by Rule_Code); CLI `compile`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_
  - [x] 5.4 [P0 -> 20.2] Property test: only APPROVED items compiled
    - **Property 11: Only APPROVED items are compiled**
    - **Validates: Requirements 4.4, 6.1**
  - [x] 5.5 [P0 -> 20.2] Property test: ruleset compile determinism and inexpressible reporting
    - **Property 12: Ruleset compile determinism**
    - **Validates: Requirements 6.4, 6.5**
  - [x] 5.6 [P0 -> 20.2] Property test: Rule_Code join back to catalog and source
    - **Property 13: Rule_Code join back to catalog and source**
    - **Validates: Requirements 5.3, 5.4, 5.7**
  - [x]* 5.7 [P1 -> 21.7] Integration smoke (skip if absent): compiled rulesets run under `spectral lint` on a variant fixture
    - _Requirements: 6.1, 16.1_

- [x] CP5. [P0 -> 20.2] Checkpoint after step 3 (tasks 3-5) - Ensure all tests pass, ask the user if questions arise.

- [x] 6. [P0 -> 22.1, 22.2] Pattern library
  - [x] 6.1 `calm-app-generation-framework/prompts/pattern-draft.v1.md` and pattern specs for P02, P03, P07, P08, P11, P12, P13, P14 (technology-neutral; reference CALM_AI_Assets as concepts only)
    - _Requirements: 7.1, 7.2, 7.5_
  - [x] 6.2 [P0 -> 22.1] Author the eight CALM 1.2 pattern JSONs in `calm-app-generation-framework/patterns/` (recorded, human-approved), each with metadata listing related control rule IDs and risk rule IDs from the catalogs; each passes `calm validate`
    - _Requirements: 7.1, 7.3, 7.5, 7.6_
  - [x] 6.3 [P0 -> 22.2] Pattern_Library store: file + catalog DB record with version/status; publish only after validation passes and approval; reject invalid with each error
    - _Requirements: 7.2, 7.4, 7.7_
  - [ ] 6.4 [P0] CALM Pattern RA Generator, pattern step: calm-app-generation-framework/src/calm_generation/pattern_ra_generator.py drafts CALM 1.2 Pattern candidates from the pattern specs (6.1) via ModelGateway (Strands runs only behind untime_strands.py); technology-neutral; metadata lists related control and risk rule IDs; every call recorded as an Extraction_Record; provider 
one/replay returns the recorded candidate; output is an unapproved candidate until calm validate passes and a reviewer approves it as a HumanTask (24.4 pattern approval)
    - Done when: a replay-mode test generates a candidate Pattern that validates, is stored as unapproved, and cannot be published (6.3) without approval
    - _Requirements: 7.2, 7.6_
  - [x] 6.5 [P0 -> 20.2] Unit tests: no technology names in patterns, related IDs exist in catalogs, invalid pattern rejected
    - _Requirements: 7.3, 7.5, 7.7_

- [x] 7. [P0 -> 22.4] Composer and RA03-LITE
  - [x] 7.1 `calm-app-generation-framework/src/calm_generation/composer.py`: merge selected Patterns into ONE CALM 1.2 pattern (`const`, `options` relationships, placeholders); record RA ID/version/source pattern versions; pure; sorted, normalized output; no risk calculation or added controls
    - _Requirements: 8.1, 8.2, 8.7, 8.8_
  - [x] 7.2 [P0 -> 20.2] Property test: Composer determinism
    - **Property 1: Composer determinism**
    - **Validates: Requirements 8.7**
  - [x] 7.3 [P0 -> 20.2] Property test: Composer conflict rejection
    - **Property 2: Composer conflict rejection**
    - **Validates: Requirements 8.6**
  - [x] 7.4 [P0 -> 22.4] Compose `calm-app-generation-framework/templates/RA03-LITE.json` (API Gateway, Invoice Processing Service, Invoice Intelligence Agent and Payment Agent as `ai:agent` with tools/autonomy/privilege metadata, Foundation Model `ai:llm`, Payment Tool `ai:tool`, Payment API, Human Approval Service, Audit Service, Invoice DB); validate; publish to CALM_Catalog; report conflicts naming both Patterns
    - _Requirements: 8.3, 8.4, 8.5, 8.6_
  - [x] 7.5 [P0 -> 20.2] Unit tests: RA03-LITE contents, per-agent nodes, no controls added beyond Patterns
    - _Requirements: 8.3, 8.4, 8.8_
  - [ ] 7.6 [P0] CALM Pattern RA Generator, reference architecture step: the same generator proposes the Pattern selection and placeholder values for a reference architecture template from a short brief (via ModelGateway; replay/none supported), then hands the selection to the deterministic Composer (7.1) to build the template. The LLM never writes the final template JSON, adds controls or calculates risk. Result is an unapproved candidate until validated and approved as a HumanTask (24.4 RA approval); then published to CALM_Catalog
    - Done when: a replay-mode test produces an RA template candidate through Composer from a generated selection, it validates, and it stays unpublished until approved
    - _Requirements: 8.1, 8.2, 8.7, 8.8_

- [x] 8. Attributes, generate, fill, validate
  - [x] 8.1 `calm-app-generation-framework/src/calm_generation/attributes.py`: `form_for(template)` YAML (fields, options), `validate(form, template)` (required, allowed, type, placeholder coverage; no Decider); refuse DRAFT templates
    - _Requirements: 9.1, 9.2, 9.3, 9.4_
  - [x] 8.2 [P0 -> 20.2] Property test: invalid attributes block instantiation
    - **Property 5: Invalid attributes block instantiation**
    - **Validates: Requirements 9.2, 9.3, 9.4**
  - [x] 8.3 `calm-app-generation-framework/src/calm_generation/placeholders.py`: fill `[[ NAME ]]`, `[[ BOOLEAN_X ]]`, `[[ REF_X ]]`, `-1` numbers from attributes; fill record; leftovers reported with JSON path and no App_Model
    - _Requirements: 10.2, 10.3_
  - [x] 8.4 [P0 -> 20.2] Property test: generate and fill leaves no placeholder
    - **Property 3: Generate and fill leaves no placeholder**
    - **Validates: Requirements 10.2, 10.3, 26.7**
  - [x] 8.5 `governance-execution-framework/src/governance_execution/units/calm_builder.py` instantiate flow: option-choices file (unique-id -> description), `calm generate` via CALM_Adapter, fill, set `$schema` to CALM 1.2, `calm validate -p`, Generation_Manifest, store App_Model; INVALID returns errors + correction guidance (V4)
    - _Requirements: 10.1, 10.4, 10.5, 10.6, 11.1, 11.3, 11.6_
  - [x] 8.6 [P0 -> 20.2] Property test: manifest and output hash round trip
    - **Property 4: Manifest and output hash round trip**
    - **Validates: Requirements 10.4, 10.5, 26.6**
  - [x] 8.7 Write `governance-execution-framework/forms/ra03-lite.attributes.yaml` and filled `v1`-`v4` forms (V2 direct-to-Payment-API unrestricted write, V3 no audit service + autonomous Payment Agent, V4 invalid instance)
    - _Requirements: 9.5, 26.1_
  - [x]* 8.8 [P1 -> 22.5] Integration smoke (skip if absent): V1 instantiates VALID, V4 reports INVALID, double generate identical SHA-256
    - _Requirements: 10.5, 11.3_

- [x] CP8. [P0 -> 20.2] Checkpoint after step 6 (task 8) - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Facts, taxonomy, Decider
  - [x] 9.1 `governance-execution-framework/src/governance_execution/core/facts.py`: extract Facts for the seven Dimensions and per-agent Facts from App_Model metadata with provenance; deterministic Taxonomy mapping first; keep `UNMAPPED`; persist FactSet + taxonomy version + App_Model hash as an Artifact
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_
  - [x] 9.2 [P0 -> 20.2] Property test: UNMAPPED retention
    - **Property 6: UNMAPPED retention**
    - **Validates: Requirements 13.4, 13.7**
  - [x] 9.3 `governance-execution-framework/src/governance_execution/core/acceptance.py` + `governance-execution-framework/config/decider_policy.yaml`: choice/score by confidence and top-2 margin, noul by 0.9/0.1 without confidence, ABSTAIN->UNKNOWN or HUMAN_REVIEW, missing/invalid -> not accepted
    - _Requirements: 14.4, 14.5, 14.6, 14.7, 14.8_
  - [x] 9.4 [P0 -> 20.2] Property test: acceptance policy correctness
    - **Property 8: Acceptance policy correctness**
    - **Validates: Requirements 14.4, 14.5, 14.6, 14.7**
  - [x] 9.5 `governance-execution-framework/src/governance_execution/adapters/decider.py`: `POST /v1/systemone` (`noul|choice|score`), config for URL/model/timeout, client-side latency, state builder (fixed fields, 4000 chars, truncation order, no CALM/secrets/paths), Input_Hash cache, audit record, providers `http|fixture` (`fixture_missing`), never raises; call only for UNMAPPED with no deterministic check; labels may feed triggers only
    - _Requirements: 14.1, 14.2, 14.3, 14.9, 15.1, 15.2, 15.3, 15.4, 15.6, 12.5_
  - [x] 9.6 [P0 -> 20.2] Property test: Input_Hash stability and cache
    - **Property 9: Input_Hash stability**
    - **Validates: Requirements 15.2**
  - [x] 9.7 [P0 -> 20.2] Property test: provider failures never escape (Decider, CALM, Spectral)
    - **Property 10: Provider failures never escape**
    - **Validates: Requirements 11.4, 15.4, 16.4, 17.4**
  - [x]* 9.8 [P1 -> 20.3] Unit tests: Decider unavailable, HTTP error, timeout, low confidence, `fixture_missing`, state truncation
    - _Requirements: 15.4, 15.6, 15.7, 26.5_

- [x] 10. [P0 -> 20.2] Spectral run, assessment, decision
  - [x] 10.1 `governance-execution-framework/src/governance_execution/core/spectral_runs.py`: run controls and risks rulesets in parallel via Spectral_Adapter; persist raw and parsed Artifacts
    - _Requirements: 16.1, 16.5_
  - [x] 10.2 `governance-execution-framework/src/governance_execution/units/control_assessment.py`: Rule_Code join -> PASS/FAIL/ERROR/NOT_APPLICABLE (PASS labelled DESIGN evidence), `governance-execution-framework/src/governance_execution/core/gap.py` Gap_Level from `governance-execution-framework/config/gap_rule.yaml`, attach catalog remediation to FAIL
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5_
  - [x] 10.3 [P0 -> 20.2] Property test: Spectral pass is design-level only
    - **Property 14: Spectral pass is design-level only**
    - **Validates: Requirements 17.2, 17.4, 25.6**
  - [x] 10.4 [P0 -> 20.2] `governance-execution-framework/src/governance_execution/scoring.py` + `governance-execution-framework/src/governance_execution/units/risk_assessment.py`: triggered risks, severity = `severity_matrix[L][I]` per risk, profile level = worst, tier from `governance-execution-framework/src/governance_execution/risk_tier.py` kept separate, `INDETERMINATE` on unevaluable mandatory trigger
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6_
  - [x] 10.5 [P0 -> 20.2] Property test: severity is a matrix lookup
    - **Property 15: Severity is a matrix lookup**
    - **Validates: Requirements 1.5, 18.1, 18.2, 18.3, 18.6**
  - [x] 10.6 `governance-execution-framework/src/governance_execution/core/gates.py` + `governance-execution-framework/src/governance_execution/core/decision.py`: ordered gates then Decision_Matrix, design-only cap to APPROVED_WITH_CONDITIONS with the required condition, record every gate/cell evaluated; no LLM/Decider input
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6_
  - [x] 10.7 [P0 -> 20.2] Property test: gate precedence and decision determinism
    - **Property 16: Gate precedence and decision determinism**
    - **Validates: Requirements 19.1, 19.2, 19.4, 19.6, 26.6**
  - [x] 10.8 [P0 -> 20.2] Property test: clean design result is conditional
    - **Property 17: Clean design result is conditional**
    - **Validates: Requirements 19.3**
  - [x] 10.9 [P0 -> 20.2] Property test: INDETERMINATE on unevaluable mandatory trigger
    - **Property 18: INDETERMINATE on unevaluable mandatory trigger**
    - **Validates: Requirements 18.5, 19.1, 26.8**

- [x] 11. [P0 -> 23.7] Remediation, units, coordinator
  - [x] 11.1 `governance-execution-framework/src/governance_execution/units/decision_remediation.py` Remediation_Agent: collect remediation of failed controls and triggered risks, Fix Prompt/Summary via ModelGateway (`governance-execution-framework/prompts/remediation.v1.md`), deterministic list when no-LLM or LLM unavailable; never edits CALM or the decision
    - _Requirements: 20.2, 20.3, 20.5_
  - [x] 11.2 [P0 -> 20.2] Property test: remediation agent cannot change outcome
    - **Property 19: Remediation agent cannot change outcome**
    - **Validates: Requirements 20.5**
  - [x] 11.3 Wrap the five Units (in `governance-execution-framework/src/governance_execution/units/`: Rule Authoring, CALM Builder, Control Assessment, Risk Assessment, Decision & Remediation) behind AgentTask/AgentResult with artifact IDs only; no Strands types in domain code
    - _Requirements: 21.1, 21.2, 21.3_
  - [x] 11.4 [P0 -> 20.3, 23.7] `governance-execution-framework/src/governance_execution/exec/coordinator.py`: `run(trace_id, app_artifact, mode normal|no-llm|replay)` invoking Units only via AgentTask; blocks on invalid CALM; Unit error recorded and no decision derived from missing results; writes versions artifact; new Trace_ID per re-run
    - _Requirements: 20.4, 21.3, 21.4, 21.5, 23.4, 11.3_
  - [x] 11.5 [P0 -> 20.2] Unit tests: Unit error yields no decision; static check that Strands is imported only in `shared/src/agip_shared/gateway/runtime_strands.py`
    - _Requirements: 21.2, 21.5_

- [x] CP11. [P0 -> 20.2] Checkpoint after step 9 (task 11) - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Executors
  - [x] 12.1 `governance-execution-framework/src/governance_execution/exec/direct_adapter.py`: run Coordinator steps with `threading` for the two Spectral lanes; Executor label (development-only when it is the fallback) stored on the assessment
    - _Requirements: 22.4, 22.5_
  - Note: 12.2-12.10 are superseded by task 27 (Fluxnova, required, after Gate F). Do not execute them separately.
  - [ ] 12.2 [P1 -> 27] Re-run Fluxnova spike 1.6 (Docker must be running): start `finos/fluxnova-bpm-platform:latest` on 8080 and probe the six calls (deployment/create, process-definition start, external-task fetchAndLock, complete, failure, task list). Update `docs/spike/fluxnova.md` with pass/fail per call and the confirmed paths. Gate: if any call fails, stop here, keep Direct_Adapter, and record why
    - _Requirements: 2.8, 2.10, 22.3_
  - [ ] 12.3 [P1 -> 27] Add `docker-compose.fluxnova.yml` (or a script in `scripts/`) to start and stop the engine, plus `.env.example` keys `EXECUTOR=direct|fluxnova`, `FLUXNOVA_URL=http://localhost:8080/engine-rest`, and matching fields in `shared` Settings
    - _Requirements: 22.1, 22.3_
  - [ ] 12.4 [P1 -> 27] Author `governance-execution-framework/src/governance_execution/exec/bpmn/assessment.bpmn`: external task per Coordinator step (topics match `GOVERNANCE_STEPS` names), parallel gateway around `spectral_controls` and `spectral_risks`, user task for invalid-CALM correction (V4 path), user task for remediation review, optional user task for rule approval. Process variables hold artifact IDs and trace ID only
    - _Requirements: 22.1, 22.2_
  - [ ] 12.5 [P1 -> 27] Add a REST client `exec/fluxnova_client.py` (deploy, start, fetchAndLock, complete, failure, list and complete user tasks) using only confirmed paths, with timeouts and error mapping. Unit-test it against a stubbed HTTP server (no Docker)
    - _Requirements: 22.2, 22.3_
  - [ ] 12.6 [P1 -> 27] Implement `exec/fluxnova_worker.py`: poll topics, call `coordinator.run_step` once per task, pass artifact IDs only via variables, report `failure` on a non-OK step so no decision is derived from missing results, propagate Trace_ID and OTel context
    - _Requirements: 22.2, 21.5_
  - [ ] 12.7 [P1 -> 27] Implement `FluxnovaExecutor` with the same `execute(coordinator, steps, trace_id, refs, log)` interface as `DirectAdapter`: deploy BPMN if missing, start an instance, run the worker until the instance ends or waits on a user task, fill `log` and `refs`. Set `label = "Fluxnova"`. Update `factory.build` to choose the executor from `EXECUTOR`, falling back to Direct_Adapter (labelled development-only) when the engine is unreachable
    - _Requirements: 22.1, 22.4, 22.5_
  - [ ] 12.8 [P1 -> 27] Human tasks: add dashboard actions (or API endpoints) to list and complete the invalid-CALM correction and remediation review user tasks, and show the process instance and current task on the assessment report and Flow page
    - _Requirements: 22.1, 22.5_
  - [ ] 12.9 [P1 -> 27] Tests: (a) unit tests for client, worker and executor with a stub engine; (b) parity test that V1-V4 give the same decisions and artifact hashes under Direct_Adapter and Fluxnova; (c) round-trip smoke test marked `@pytest.mark.fluxnova`, skipped when `FLUXNOVA_URL` is unreachable
    - _Requirements: 22.1, 22.2, 26.9_
  - [ ] 12.10 [P1 -> 27] Docs: add a Fluxnova section to `docs/functional_manual_testing.md` (start engine, run V1-V4 with `EXECUTOR=fluxnova`, check the process in the engine cockpit, complete a user task), update `docs/TESTING.md` and the Executor note in `docs/spike/fluxnova.md`
    - _Requirements: 22.4, 22.5_

- [x] CP12. [P0 -> 20.2] Checkpoint after step 10 (task 12) - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Dashboard
  - [x] 13.1 `governance-execution-framework/src/governance_execution/dashboard/app.py` (FastAPI + Jinja2 + vanilla JS, port 8001, Mermaid vendored in `governance-execution-framework/src/governance_execution/dashboard/static/`, reads persisted Artifacts only): base layout with labels "illustrative, not approved policy" / "design-level evidence only"; routes `/`, report, `/versions`, `/catalogs/{kind}`, `/variants`; show Executor; mount routers from `governance-execution-framework/src/governance_execution/dashboard/routers/pages.py` and `.../routers/api.py`
    - _Requirements: 22.5, 25.1, 25.4, 25.6_
  - [x] 13.2 `governance-execution-framework/src/governance_execution/dashboard/routers/pages.py`: flow (parallel lanes), architecture diagram coloured by worst finding, 5x5 risk matrix, control gap table, remediation/Fix Prompt, Decider panel (unavailable questions listed), UNMAPPED facts
    - _Requirements: 13.7, 15.5, 25.2, 25.4_
  - [x] 13.3 `governance-execution-framework/src/governance_execution/core/trace.py` + explorer route: graph decision -> gate/matrix cell -> control/risk -> Rule_Code + JSON path -> CALM element -> pattern/template version -> AIGF/CCC source ID, both directions
    - _Requirements: 25.3_
  - [x] 13.4 [P0 -> 20.2] Property test: trace graph completeness
    - **Property 23: Trace graph completeness**
    - **Validates: Requirements 25.3**
  - [x] 13.5 `governance-execution-framework/src/governance_execution/dashboard/routers/api.py`: `POST /api/upload` (<=1 MB, JSON/YAML, data only, immutable Artifact, same path as generated), `/api/assess`, `/api/rules/{id}/approve`, `GET /api/attributes-form/{template}`, `/api/instantiate`, `/api/replay/{trace}`; paths via `resolve_within`
    - _Requirements: 4.3, 9.1, 12.1, 12.2, 12.3, 12.4, 20.4, 24.2_
  - [x] 13.6 JSON Artifact downloads and Static_Export (self-contained HTML report)
    - _Requirements: 20.1, 25.5_
  - [x] 13.7 [P0 -> 20.2] FastAPI `TestClient` smoke tests: all routes, no `http(s)://` CDN refs, both labels present, UNMAPPED fact shown, upload rejects >1 MB and non-JSON/YAML
    - _Requirements: 12.1, 13.7, 25.1, 25.6_

- [x] 14. Variants, golden E2E, replay
  - [x] 14.1 Recorded LLM and Decider outputs and recordings (`rule-authoring-framework/fixtures/recordings/llm/`, `governance-execution-framework/fixtures/recordings/decider/`) for V1-V4 (variant inputs in `calm-app-generation-framework/fixtures/variants/`); expected results file (V1 APPROVED_WITH_CONDITIONS, V2 REJECTED by G2, V3 high profile + minor gaps + RESTRICTED, V4 blocked); tune catalog rules so these hold
    - _Requirements: 26.1_
  - [x] 14.2 `governance-execution-framework/src/governance_execution/obs/replay.py`: replay from recordings with zero model calls, identical artifacts and decision, fail naming the missing record
    - _Requirements: 24.2, 24.3, 24.4_
  - [x] 14.3 Golden E2E tests V1-V4 (instantiate -> assess via Direct_Adapter; CALM/Spectral stubbed on recorded outputs, real tools when present)
    - _Requirements: 26.1, 26.9_
  - [x] 14.4 Golden no-LLM (V1-V3 complete with deterministic remediation list), replay-identical (V1-V4), and most-favourable-Decider invariant tests
    - _Requirements: 26.2, 26.3, 26.4, 26.9_
  - [x]* 14.5 [P0 -> 23.3] Property test: Decider advisory and bounded
    - **Property 7: Decider is advisory and bounded**
    - **Validates: Requirements 14.1, 14.9, 26.4**
  - [x] 14.6 [P0 -> 20.2] Property test: no-LLM mode completes
    - **Property 20: No-LLM mode completes**
    - **Validates: Requirements 20.3, 21.4, 26.2**
  - [x] 14.7 [P0 -> 20.2] Property test: replay is identical
    - **Property 21: Replay is identical**
    - **Validates: Requirements 24.2, 24.3, 24.4, 26.3**

- [x] 15. README and demo
  - [x] 15.1 `README.md`: purpose, architecture summary, Git Bash install/test command, tool prerequisites (calm, spectral, Docker optional), modes, ports, labels, link to `docs/REUSE.md` and `docs/spike-notes.md`
    - _Requirements: 1.6, 23.5_
  - [x] 15.2 `scripts/demo.sh` (repo root) (Git Bash): compile rulesets, instantiate and assess V1-V4 on recorded outputs, print decisions, start the dashboard on 8001 and open it in the browser
    - _Requirements: 20.1, 26.1, 26.9_

- [x] 16. [P1 -> 28.1] (Superseded: run as 28.1 after functional acceptance) Remove unused code (paths relative to `ai-governance-intelligence-platform/`; before each deletion grep for importers, after each task run `uv run pytest` and the golden tests)
  - [x] 16.1 [P1 -> 28.1] Remove the old rule-registry pipeline in `governance-execution-framework/src/governance_execution/`: `pipeline.py`, `applicability.py`, `findings.py`, `scoring.py`, and `tests/test_pipeline.py`. Trim `tests/test_risk_tier.py` to the `classify_risk` and `derive_capability_flags` tests (it imports `GovernanceScorer`). Keep `risk_tier.py` (used by `units/risk_assessment.py`). Update `tests/test_consistency_guards.py` (`RISK_TIER_MODULES` and its negative examples reference `scoring`)
    - _Requirements: 18, 26.9_
  - [x] 16.2 [P1 -> 28.1] Remove the old seed path in `rule-authoring-framework/`: `src/rule_authoring/ingest_finos.py`, `transform.py`, `catalogs/seed/` (registry and 12 rule YAMLs), `docs/examples/`, the Jinja template under `templates/` if only `transform.py` uses it, `SEED_*` constants in `paths.py`, and `tests/test_seed_catalog.py`. Rewrite `tests/test_catalogs.py::test_every_seed_control_merged_once` to check the catalogs directly. Remove `CanonicalRule`/`Finding` from `shared/.../contracts.py` and `tests/test_rule_schema.py` only if no other user remains. Rewrite `docs/AUTHORING-GUIDE.md` for the extraction, approval and compile path
    - _Requirements: 3, 5_
  - [x] 16.3 [P1 -> 28.1] Remove `calm-app-generation-framework/src/calm_generation/calm_finos.py` and its test in `tests/test_fixtures_and_readers.py` (its only importers were `pipeline.py` and `applicability.py`). Decide on `validate_v12.py`: keep it and wire it into `docs/TESTING.md` as a manual meta-schema check, or delete it. Delete the empty `governance_execution/gateway/` package and any other empty or placeholder file found by the importer scan
    - _Requirements: 7, 10_
  - [x] 16.4 [P1 -> 28.1] Check and document: run `uv run vulture` (or an equivalent import scan) over `src/` and `scripts/`, list anything else unused, delete or justify each. Update `docs/STRUCTURE.md`, `docs/REUSE.md`, `docs/deliberate-changes.md`, `docs/spike-notes.md`, `docs/execution_flow.md` (section 3h) and `README.md`. Run `uv run pytest`, `AGIP_REAL_TOOLS=1` golden tests and `bash scripts/demo.sh`; decisions for V1-V4 must be unchanged
    - _Requirements: 26.9_

- [x] 17. [P0 -> 21] (Superseded: folded into 21.1, 21.2, 21.5, 21.7) CCC as a proper source (today `sources_ccc.py` has no caller, and the two CCC catalog entries `CCC.KMS` and `CCC.VPC` are hand-written with `path: "core/core"`)
  - [x] 17.1 [P0 -> 21] Inspect the checkout at `../common-cloud-controls`: list catalogs, file layout (`controls.yaml`, `threats.yaml`, `capabilities.yaml`), IDs, and the fields that map to AIGF and NIST. Choose the in-scope catalogs (`core/core`, `ai-ml/multi-agent-refarch`), record the commit hash in `docs/spike-notes.md`, and add a `CCC_PATH` setting (like the AIGF path)
    - _Requirements: 3_
  - [x] 17.2 [P0 -> 21] Harden `sources_ccc.read`: same `SourceItem` shape as AIGF, stable sorted output, control, threat and capability linking, `SourceError(path, field, message)` for every bad entry, no crash on unknown fields. Add fixture-based tests including malformed files
    - _Requirements: 3_
  - [x] 17.3 [P0 -> 21] Add an ingestion command `python -m rule_authoring.ingest --source aigf|ccc --path <dir> [--ids ...] [--provider replay|bedrock]`: read with the adapter, call `extraction.extract` through the `ModelGateway`, write the DRAFT with its `Extraction_Record`, and print a summary. This is also the missing CLI entry point for AIGF extraction
    - _Requirements: 3, 4_
  - [x] 17.4 [P0 -> 21] Add a CCC input shape to the extraction prompt (`prompts/extraction.v1.md`, new prompt version): control objective, assessment requirements and threat mappings go in as structured input. Extraction must keep CCC IDs unchanged and fill `references` from the source mappings, not from model guesses
    - _Requirements: 4_
  - [x] 17.5 [P0 -> 21] Replace the hand-written `CCC.KMS` and `CCC.VPC` entries: extend `seed_recordings.py` to cover CCC items, run the ingest path in replay mode, set a real `source.path`, approve, compile. Rulesets must compile to the same rules or the diff must be explained
    - _Requirements: 4, 5, 6_
  - [x] 17.6 [P0 -> 21] Cross-framework links: fill `references` between CCC, AIGF and NIST from the CCC mappings, make `consistency.py` fail on a reference to an ID that exists in no catalog, and make `core/trace.py` follow CCC IDs back to the CCC source
    - _Requirements: 5, 25_
  - [x] 17.7 [P0 -> 21] Tests and docs: adapter and extraction-from-recording tests for CCC, a CCC step in `docs/functional_manual_testing.md` (section 2) and `docs/execution_flow.md`
    - _Requirements: 3, 4, 26.9_

- [ ] 18. [P0 -> 21] (Superseded: folded into 21.1, 21.2, 21.4, 21.5, 21.6, 21.7) Risk rules from the AIGF risk catalog (today `risks.catalog.yaml` holds 6 hand-written entries, `approved_by: seed-import`, from the 24 AIGF `ri-*` files; `sources_aigf.read` can read risks but no step extracts them)
  - [x] 18.1 [P0 -> 21] Document how the 6 current risk rules were made and which of the 24 AIGF risks they cover, in `docs/execution_flow.md` and `rule-authoring-framework/docs/AUTHORING-GUIDE.md`
    - _Requirements: 5_
  - [ ] 18.2 [P0 -> 21] Extend the ingest command to read `../ai-governance-framework/docs/_risks/ri-*.md` and extract risk items (`kind: risk_rule`): dimension from the Scoring_Profile dimension list, candidate Spectral rule over the CALM metadata vocabulary in `controls.catalog.yaml`. A risk with no expressible check is stored as a DRAFT with no rule and reported, never dropped
    - _Requirements: 3, 4_
  - [x] 18.3 [P0 -> 21] Treat model-proposed likelihood and impact as suggestions only: approval must record who confirmed them, and `approval.py` refuses a risk whose likelihood or impact is unconfirmed. Severity stays computed by the Scoring_Profile
    - _Requirements: 4, 18_
  - [x] 18.4 [P0 -> 21] Link risks to controls using the related mitigation IDs that `sources_aigf` already parses. `consistency.py` fails on a link to a missing control
    - _Requirements: 5_
  - [x] 18.5 [P0 -> 21] Add `python -m rule_authoring.coverage`: one row per AIGF risk (and per CCC threat when 17 is done) with state `APPROVED rule`, `DRAFT`, or `not expressible`, plus counts
    - _Requirements: 5_
  - [ ] 18.6 [P0 -> 21] Compile and re-run: approve the new risk rules, recompile, regenerate recordings, and run the golden tests. V1-V4 decisions must not change unless the change is explained in `docs/deliberate-changes.md`; update `expected.yaml` and the docs
    - _Requirements: 6, 26.1_

---

# Revised backlog (proposal alignment)

Rules for tasks 19-28: preserve working code, module boundaries and contracts. A task is done only when its "Done when" tests pass; a file or class existing is not enough. Automated tests never need live Bedrock, Decider or Fluxnova. Each phase ends at a review gate (CP-A to CP-G): stop and report completed tasks, changed files, test commands, results and gaps. Fixed scope: 8 CALM patterns (P02, P03, P07, P08, P11, P12, P13, P14) and RA03-LITE only. Decider moves from Advisory to Accepted Classification (Option B). Fluxnova is required and comes last.

- [x] 19. Phase 0: baseline and delta report (P0)
  - [x] 19.1 [P0] Record branch, commit and a full `uv run pytest` baseline. For every task marked `[x]`, inspect the code and tests and classify it COMPLETE / PARTIAL / INCORRECTLY_MARKED with evidence (file, test, gap). Write `docs/implementation-delta.md`
    - Done when: every `[x]` task has a status and evidence line; the baseline test counts are recorded
  - [x] 19.2 [P0] Update this file from the delta report: reopen PARTIAL and INCORRECTLY_MARKED tasks, add P0/P1/P2 to every open task, and link each to its revised task (20-28). Remove the `*` from the tests listed in 20.2
    - Done when: no `[x]` task contradicts the delta report
    - _Depends: 19.1_

- [x] 20. Phase A: core contracts and correctness (P0; existing tasks 2, 14)
  - [x] 20.1 [P0] Extend `shared/src/agip_shared/contracts.py` only where needed: framework identity, FrameworkExecution (start, step, wait, resume, fail, retry, cancel, complete), artifact provenance and version, HumanTask, HumanTaskOutcome, source and knowledge lifecycle states, AssessmentRequirement, Evidence, accepted Decider classification, workflow execution reference. No duplicate contracts
    - Done when: round-trip and invalid-value tests pass for every new contract
    - _Proposal: A01, E01, E02, H02_
  - [x] 20.2 [P0] Make these tests mandatory and implement them (Hypothesis, at least 100 examples for pure-core properties): 2.3, 2.8, 3.3, 5.4, 5.5, 5.6, 6.5, 7.2, 7.3, 7.5, 8.2, 8.4, 8.6, 9.2, 9.4, 9.6, 9.7, 10.3, 10.5, 10.7, 10.8, 10.9, 11.2, 11.5, 13.4, 13.7, 14.6, 14.7. Replace 14.5 with the Option B properties in 23.3
    - Done when: all listed tests exist and pass in `uv run pytest`
    - _Proposal: A02_
  - [x] 20.3 [P0] Adapter and failure safety: tests for missing executable, timeout, invalid output, provider error and persistence failure on the CALM, Spectral, Decider and ModelGateway adapters and the artifact store
    - Done when: no failure path yields VALID or PASS, and a failed or incomplete mandatory stage yields no normal decision
    - _Proposal: A03_
  - [x] 20.4 [P0] Immutable artifacts and replay: every assessment records Trace_ID, input artifact IDs and hashes, framework versions, catalog and ruleset versions, taxonomy and scoring profile versions, Decider output and policy version, evaluator versions, mode and stage outputs
    - Done when: a test changes a catalog after an assessment and shows the stored assessment and its replay are unchanged
    - _Proposal: A04_
- [x] CP-A. Gate A: contracts and critical tests pass. Stop for review

- [x] 21. Phase B: Rule Authoring framework (P0; existing 3-5, absorbs 17 and 18)
  - [x] 21.1 [P0] Source ingestion. CCC: inspect `../common-cloud-controls`, record its commit, support `core/core` and `ai-ml/multi-agent-refarch`, keep native IDs, parse controls, threats and capabilities, keep AIGF and NIST mappings from the source, report malformed data with path and field. AIGF: all in-scope `ri-*` and `mi-*` with native IDs, paths and references. Add `python -m rule_authoring.ingest --source aigf|ccc`
    - Done when: fixture tests (including malformed files) pass for both adapters, and the CLI ingests both real checkouts
    - _Proposal: B01; old 17.1-17.3_
  - [x] 21.2 [P0] Extraction through ModelGateway for AIGF risks and mitigations and CCC controls, threats and assessment requirements. Every record stays DRAFT, keeps source ID and version, Extraction_Record, prompt, model, version and input hash, and passes schema validation. Inexpressible or incomplete items are reported, not dropped. New prompt version for the CCC input shape
    - Done when: extraction from recordings passes for AIGF control, AIGF risk and CCC control samples, and an inexpressible sample is reported
    - _Proposal: B02; old 17.4, 18.2_
  - [x] 21.3 [P0] Typed knowledge: Principle, Guideline, Risk, Risk Scenario, Mitigation, Control, Policy, Requirement, Assessment Requirement, Evidence Criterion, Evaluation Procedure, Recommendation, Informational Statement. Only executable types compile to Spectral
    - Done when: a test shows non-executable types are stored, never compiled, and appear in coverage
    - _Proposal: B03_
  - [x] 21.4 [P0] Approval lifecycle DRAFT -> IN_REVIEW -> APPROVED / REJECTED -> DEPRECATED, with reviewer, role, rationale, timestamp, version, supersession and immutable history. Model-proposed likelihood and impact need recorded human confirmation before approval
    - Done when: tests cover every valid and invalid transition, the unconfirmed-risk refusal and "only APPROVED compiles"
    - _Proposal: B04; old 18.3_
  - [x] 21.5 [P0] Catalog integrity: unique Rule_Code, cross-catalog consistency, reference integrity (CCC, AIGF, NIST), risk-to-mitigation and control links, source traceability, deterministic compile, inexpressible reporting, ruleset version and hash. Replace hand-written `CCC.KMS` and `CCC.VPC` with ingested items
    - Done when: `consistency` fails on a dangling reference or link, and compile is byte-identical across two runs
    - _Proposal: B05; old 17.5, 17.6, 18.4_
  - [x] 21.6 [P0] `python -m rule_authoring.coverage`: per source risk, control and threat, the state APPROVED rule / DRAFT / IN_REVIEW / REJECTED / not expressible / missing extraction, with the source mapping
    - Done when: the report covers all 24 AIGF risks and the in-scope CCC items, and a test checks the counts on fixtures
    - _Proposal: B06; old 18.5_
  - [x] 21.7 [P0] Independent journey without CALM Generation or Governance: ingest AIGF and CCC, extract from recordings, review and edit, approve, compile, run Spectral on independent CALM fixtures, inspect lineage and coverage. Write `rule-authoring-framework/docs/WALKTHROUGH.md`, document how the 6 current risk rules were made, and re-run golden tests (decision changes go in `docs/deliberate-changes.md`)
    - Done when: the journey test passes with no import of `calm_generation` or `governance_execution`
    - _Proposal: B07; old 17.7, 18.1, 18.6_
- [x] CP-B. Gate B: Rule Authoring works independently. Stop for review

- [x] 22. Phase C: CALM App Generation (P0; existing 6-8; 8 patterns and RA03-LITE only)
  - [x] 22.1 [P0] Pattern library validation for all 8 patterns: CALM 1.2 schema, relationships, referenced Rule_Code IDs exist, technology neutral, source and version metadata. Invalid patterns cannot be published (use calm ai for generation)
    - Done when: mandatory tests pass for each pattern and for a broken pattern
    - _Proposal: C01_
  - [x] 22.2 [P0] Pattern lifecycle DRAFT -> IN_REVIEW -> APPROVED -> PUBLISHED -> DEPRECATED with review, rejection, revision and version history. Only approved, valid patterns can be composed (use calm ai for generation)
    - Done when: transition tests pass, and composing with an unapproved pattern is refused
    - _Proposal: C02_
  - [x] 22.3 [P0] Composer: one CALM pattern out, component and relationship conflicts name both patterns, selection order does not change normalized output, no risk or control logic added, source versions and hashes recorded (use calm ai for RA generation)
    - Done when: property tests for determinism, order independence and conflicts pass
    - _Proposal: C03_
  - [x] 22.4 [P0] RA03-LITE lifecycle: content and relationship validation, review, approval, publication, version history, source pattern manifest, composed CALM hash (use calm ai for RA generation)
    - Done when: RA03-LITE moves through the lifecycle in a test, and an unpublished RA cannot be instantiated
    - _Proposal: C04_
  - [x] 22.5 [P0] Instantiation: attributes form (required and optional, type and allowed values), option choices, `calm generate`, deterministic placeholder fill, unfilled-placeholder rejection, `calm validate -p`, generation manifest, artifact persistence. CLI behaviour per spike notes. No LLM
    - Done when: identical inputs give an identical output hash, and invalid attributes and leftovers are rejected
    - _Proposal: C05_
  - [x] 22.6 [P0] Standalone CLI/API `python -m calm_generation` with subcommands: list patterns, show versions, compose, review/publish RA, attributes form, instantiate, validate/inspect. No Governance import
    - Done when: CLI tests pass and an import-boundary test shows no `governance_execution` dependency
    - _Proposal: C06_
  - [x] 22.7 [P0] Independent journey: inspect, select, compose RA03-LITE, trigger a conflict, review and publish, form, instantiate V1, reject invalid attributes, V4 INVALID, reproduce the hash. Write `calm-app-generation-framework/docs/WALKTHROUGH.md`
    - Done when: the journey test passes
    - _Proposal: C07_
- [x] CP-C. Gate C: CALM Generation works independently. Stop for review

- [x] 23. Phase D: Governance Execution and Decider Option B (P0; existing 9-11)
  - [x] 23.1 [P0] Facts keep fact ID, CALM element ID, attribute, raw value, normalized value, JSON path, extraction method, classification metadata, taxonomy version, mapping status and provenance. Raw values are never overwritten
    - Done when: property test shows raw values survive every mapping and classification path
    - _Proposal: D01_
  - [x] 23.2 [P0] Decider Option B: change design decision D8 to Accepted Classification in `design.md`. Call the Decider only for eligible UNMAPPED facts with no deterministic mapping. Outcomes ACCEPTED / HUMAN_REVIEW / ABSTAIN / ERROR under the current policy (choice/score: confidence >= 0.80 and top-2 margin >= 0.20; noul: >= 0.90 or <= 0.10). ACCEPTED adds a normalized classification with model, version, input hash, answer, confidence, margin, policy version, timestamp, provenance. HUMAN_REVIEW persists a HumanTask and sets WAITING_FOR_HUMAN when the value is needed. ABSTAIN and ERROR keep UNKNOWN/UNMAPPED, never a risk-reducing default
    - Done when: unit tests cover all four outcomes
    - _Proposal: D02_
  - [x] 23.3 [P0] Replace the advisory-only property (old 14.5) with 7 properties: accepted keeps original and full provenance; Decider cannot set likelihood, impact, severity, control status, gates or decision; accepted facts take part in risk applicability; unaccepted stay UNKNOWN/UNMAPPED; thresholds applied exactly; missing, invalid or failed answers never accepted; replay with the same policy gives the same FactSet and downstream result
    - Done when: all 7 Hypothesis properties pass
    - _Proposal: D03_
  - [x] 23.4 [P0] Deterministic assessment: two parallel Spectral lanes, Rule_Code joins, control status, gap, triggered scenarios, likelihood and impact, severity matrix, risk profile, gates, decision matrix, remediation
    - Done when: V1-V4 golden tests pass and no Decider value reaches scoring or decision (static and runtime test)
    - _Proposal: D04_
  - [x] 23.5 [P0] Risk lifecycle: Exposure -> Scenario -> Inherent -> Mitigation -> Control/Evidence -> Residual -> Decision. Residual is conservative: no reduction without supporting evidence, no subtraction of control scores, uncertainty kept
    - Done when: a test shows residual equals inherent when evidence is missing or DESIGN-only
    - _Proposal: D05_
  - [x] 23.6 [P0] AssessmentRequirement and Evidence: requirement ID, related control/risk, evidence ID, type, source, app and version, timestamp, hash, maturity (DESIGN / IMPLEMENTATION / OPERATING), validity, evaluation status, reviewer and rationale. Spectral = DESIGN only; IMPLEMENTATION and OPERATING = NOT_VERIFIED
    - Done when: a test shows missing evidence is never PASS
    - _Proposal: D06_
  - [x] 23.7 [P0] Separate statuses. Assessment: QUEUED / RUNNING / WAITING_FOR_HUMAN / COMPLETED / FAILED / BLOCKED. Validation: VALID / INVALID / INCOMPLETE / ERROR. Decision: APPROVED / APPROVED_WITH_CONDITIONS / RESTRICTED / REJECTED / INDETERMINATE. Invalid CALM is BLOCKED, not REJECTED. Unevaluable mandatory trigger gives INDETERMINATE
    - Done when: V4 is BLOCKED with no decision, and status tests pass. Update golden expectations with a documented reason
    - _Proposal: D07_
  - [x] 23.8 [P0] Risk acceptance: risk ref, app and assessment ref, authorized actor and role, rationale, scope, expiry, audit history. Ordinary approval cannot override mandatory gates
    - Done when: tests cover authorized, unauthorized, expired and gate-override attempts
    - _Proposal: D08_
  - [x] 23.9 [P0] Standalone CLI/API that assesses external CALM JSON using frozen approved catalogs and rulesets. Tests: valid, invalid, known and unknown facts, accepted and unaccepted classification, triggered risk, failed mandatory control, missing evidence, provider failure, gate precedence, INDETERMINATE, human review, replay
    - Done when: all scenarios pass with no runtime import of `calm_generation` or `rule_authoring`
    - _Proposal: D09_
- [x] CP-D. Gate D: Governance works independently with Option B. Stop for review

- [x] 24. Phase E: common HumanTask lifecycle (P0; before Fluxnova)
  - [x] 24.1 [P0] HumanTask store using the 20.1 contract: ID, framework, type, subject refs, trace ID, status, role or actor, permitted actions, created and due, context, required evidence
    - Done when: create/read tests pass on the store
    - _Proposal: E01_
  - [x] 24.2 [P0] HumanTaskOutcome: task ID, actor, role, action, rationale, timestamp, outcome artifact, previous and resulting state. Immutable
    - Done when: a test shows an outcome cannot be rewritten
    - _Proposal: E02_
  - [x] 24.3 [P0] Persist and resume: create, assign, claim, complete, reject, request changes, cancel, resume execution. Survives restart. Server-side authorization. Direct Adapter supports WAITING_FOR_HUMAN and resume
    - Done when: a test stops the process mid-wait, restarts and resumes to a decision
    - _Proposal: E03, 1.4_
  - [x] 24.4 [P0] Scenarios on the common contract: rule review, risk likelihood/impact confirmation, pattern approval, RA approval, Decider classification review, evidence review, remediation review, risk acceptance
    - Done when: one test per scenario passes through the shared contract
    - _Proposal: E04_
  - [x] 24.5 [P0] One Review Queue across all three frameworks, filtered by framework, type, status, reviewer, application, priority, with the context and lineage needed to decide. Reviewers claim, approve, reject, request changes and cancel from the UI (action buttons call the server-side lifecycle from 24.3; rationale required; UI shows only actions permitted for the signed-in role)
    - Done when: dashboard tests cover the filters, the context panel, and each action from the UI including a denied action for an unauthorized role
    - _Proposal: E05_
  - [x] 24.6 [P0] MVP actors and roles with server-side checks, no self-approval where separation of duties applies, and artifact approval never grants a financial or privileged action
    - Done when: tests cover unauthorized and invalid transitions
    - _Proposal: E06_
- [x] CP-E1. Human tasks done (Gate E closes after 25)

- [x] 25. Phase F: registries, dashboard, execution visibility, lineage (P0; extends 13, keeps existing pages)
  - [x] 25.1 [P0] Platform overview: assessment counts and outcomes, execution status, failed and blocked runs, waiting tasks, critical risks, framework health, recent changes, active versions
    - _Proposal: F01_
  - [x] 25.2 [P0] Workbenches for Rule Authoring, CALM Generation and Governance, each with its own capabilities and execution history
    - _Proposal: F02_
  - [x] 25.3 [P0] Reusable registry and detail components for sources, risks, controls, assessment requirements, patterns, RAs, rulesets, governance config and scoring profiles, evaluators, models and prompts, with status, version, provenance and relationships
    - _Proposal: F03_
  - [x] 25.4 [P0] Execution dashboard: timeline, stage status and duration, input/output refs, errors and retries, framework and executor, catalog and ruleset versions, CALM hash, Decider model and outcomes, human tasks, workflow IDs. Reads persisted records only
    - _Proposal: F04_
  - [x] 25.5 [P0] Lineage both ways: decision -> gate/matrix -> risk/control -> rule -> CALM element -> pattern/RA -> source, and source -> rules -> patterns/RA -> assessments -> decisions. Accepted classifications shown as inferred facts
    - _Proposal: F05_
  - [ ] 25.6 [P0] Change impact: for a changed source, rule, pattern, RA or scoring profile, list impacted artifacts and assessments and recommend re-assessment or review. Historical decisions are never rewritten
    - _Proposal: F06_
  - [ ] 25.7 [P0] Compare assessments and app versions; export a self-contained report with decision, status, risk profile, gaps, evidence, review outcomes, accepted classifications, provenance and versions
    - _Proposal: F07_
  - [x] 25.8 [P0] Dashboard tests: every route, key actions, authorization, registry navigation, task completion, lineage traversal, upload validation, export, and both labels on every page
    - Done when (25.1-25.8): 25.8 passes
    - _Proposal: F08_
- [x] CP-E. Gate E: human tasks, registries, dashboard and lineage cover all three frameworks. Stop for review

- [x] 26. Phase G: independent and integrated acceptance (P0; keeps 14)
  - [x] 26.1 [P0] Rule Authoring acceptance suite (from 21.7) runs alone
    - _Proposal: G01_
  - [x] 26.2 [P0] CALM acceptance suite (from 22.7) runs alone
    - _Proposal: G02_
  - [x] 26.3 [P0] Governance acceptance on an externally generated CALM file with frozen catalogs and rulesets (from 23.9)
    - _Proposal: G03_
  - [x] 26.4 [P0] Cross-framework contract tests: each framework's output as the next one's input, with version and schema compatibility, provenance and deterministic joins
    - _Proposal: G04_
  - [x] 26.5 [P0] Integrated E2E covering all 13 steps: ingest, extract, approve, compile, approve patterns, publish RA03-LITE, instantiate, assess, accept a classification, evaluate, decide, complete a human task, inspect execution and lineage, replay. V1-V4 golden tests kept; expected outcomes change only with a documented reason
    - _Proposal: G05_
  - [x] 26.6 [P0] Walkthroughs: one per framework and one integrated, none needing Fluxnova
    - Done when (26.1-26.6): all suites pass in one `uv run pytest` run and each suite also passes alone
    - _Proposal: G06_
- [x] CP-F. Gate F: integrated E2E and replay pass. Stop for review

- [ ] 27. Phase H: Fluxnova orchestration (P1, required; replaces 12.2-12.10; starts only after CP-F)
  - [ ] 27.1 [P1] Re-run the spike on a pinned Fluxnova version (not `latest`): health, deploy, start, fetch-and-lock, complete, failure, user-task list and complete, process status, variables and correlation. Record version, image digest and REST paths in `docs/spike/fluxnova.md`. Resolve any missing capability before going further
    - _Proposal: H01_
  - [ ] 27.2 [P1] Check the 20.1 FrameworkExecution contract covers start, step, wait, human task, resume, failure, retry, cancel, complete with business logic left in the framework services
    - _Proposal: H02_
  - [ ] 27.3 [P1] Three BPMN workflows in `governance-execution-framework/src/governance_execution/exec/bpmn/`: Knowledge Lifecycle, Architecture Lifecycle, Assessment Lifecycle. Rule approval is not in the assessment workflow. The assessment workflow creates and waits on human tasks via the common contract
    - _Proposal: H03_
  - [ ] 27.4 [P1] Pinned Docker config, REST client on the confirmed paths, timeouts, error mapping, health checks, process deployment and versioning
    - _Proposal: H04_
  - [ ] 27.5 [P1] Workers and `FluxnovaExecutor` calling the same framework services as Direct Adapter. Variables carry artifact IDs and trace IDs only. OTel context propagated. A failed step is never marked successful. Executor chosen by `EXECUTOR`
    - _Proposal: H05_
  - [ ] 27.6 [P1] Fluxnova user tasks map to the same HumanTask and HumanTaskOutcome records. An authorized user action completes the task and resumes the right process
    - _Proposal: H06_
  - [ ] 27.7 [P1] Reliability tests: duplicate delivery, idempotent steps, retry limits, timeouts, worker restart, engine restart, process recovery, cancellation, failed-process recovery, human wait and resume
    - _Proposal: H07_
  - [ ] 27.8 [P1] Parity: same inputs through Direct Adapter and Fluxnova; compare decisions, statuses, deterministic artifact hashes, human task outcomes, traceability and failure semantics. Any difference is documented and accepted
    - _Proposal: H08_
  - [ ] 27.9 [P1] Dashboard shows executor, process definition and version, instance ID, current task, workflow status, retries and failures, human-task status
    - _Proposal: H09_
  - [ ] 27.10 [P1] Docs (deploy, workflow deploy, run, task completion, recovery, troubleshooting) and a smoke suite marked `fluxnova`, skipped when the engine is down, run in the Fluxnova acceptance environment
    - Done when (27.1-27.10): parity and reliability suites pass against the pinned engine, and all three lifecycles run under Fluxnova
    - _Proposal: H10_
- [ ] CP-G. Gate G: Fluxnova orchestrates all three lifecycles and parity passes. Stop for review

- [x] 28. Phase I: cleanup and documentation (P1; after CP-F)
  - [x] 28.1 [P1] Run task 16 now. Check importers and usage first; do not delete `scoring.py`, old catalog paths, `calm_finos.py` or contracts unless the new architecture and tests no longer use them
    - Done when: full suite and golden tests pass after deletion
    - _Proposal: I_
  - [x] 28.2 [P1] Update README, STRUCTURE, REUSE, TESTING, functional_manual_testing, execution_flow, spike notes, AUTHORING-GUIDE, deliberate-changes, the dependency graph below, with commands for independent, integrated and Fluxnova tests
    - _Proposal: I_
  - [x] 28.3 [P1] Put deferred scope in `backlog.md`: the other 7 CALM patterns, RA01, RA02, SSO and enterprise IAM, full RBAC, runtime cloud evidence collectors, operating-effectiveness automation, automatic rule learning and promotion, automatic scoring changes, multi-tenant deployment, advanced notifications and escalation
    - _Proposal: 11_

MVP done only when gates CP-A to CP-G have all passed (proposal section 12, items 1-13).

## MVP-4h scope (agreed 2026-11-17)

Fluxnova is out of the current MVP. Gates CP-B to CP-F run as automated checks (the gate's suites pass in `uv run pytest`), not as review stops. One report at the end. V4 changes from decision BLOCKED to assessment status BLOCKED with no decision; the reason is recorded in `docs/deliberate-changes.md`. No ruleset changes, because the offline Spectral recordings are keyed by ruleset bytes and Spectral is not installed.

| Package | Tasks | Simplification |
|---|---|---|
| A. Rule Authoring | 21.7 | Only recorded samples extracted; coverage report shows the gap |
| B. CALM Generation | 22.1-22.7 | - |
| C. Governance + Option B | 23.1-23.4, 23.6, 23.7, 23.9 | - |
| D. Residual risk, risk acceptance | 23.5, 23.8 | Residual = inherent unless supporting evidence; no full mitigation model |
| E. Human tasks | 24.1-24.4, 24.6 (simple) | Roles from config, no self-approval; 3 scenarios: Decider review, remediation review, rule review (others on the shared contract) |
| F. Dashboard | 24.5, 25.1-25.5, 25.8 | Basic queue filters; 25.6 as "assessments that used this artifact" |
| G. Acceptance, docs | 26.1-26.6, 28.1-28.3 | - |

Deferred to `backlog.md` (linked to proposal IDs): task 27 Fluxnova (H01-H10) with CP-G; 25.6 full change impact (F06); 25.7 compare (F07); full RBAC and multi-reviewer (E06); live Bedrock re-extraction and extraction of all 24 AIGF risks (B02); advanced queue filters (E05).

## Notes

- Tasks marked `*` are optional (tests, stretch items: live re-extraction 4.3, Fluxnova wiring 12.2/12.3 if the spike fails).
- Golden E2E tests (14.3, 14.4) are required. The tests listed in 20.2 are mandatory (no `*`); other property and unit tests stay optional.
- Status after the 19.1 audit is in `ai-governance-intelligence-platform/docs/implementation-delta.md`. Tags `[Pn -> X]` give the priority and the revised task that closes the item.
- Old-to-new numbering for the split of former task 3: 3.4-3.7 are now 4.1-4.4; 3.8-3.14 are now 5.1-5.7; former tasks 4-13 are now 6-15 (same sub-task order, N -> N+2); former CP3/CP6/CP9/CP10 are now CP5/CP8/CP11/CP12.
- The dependency graph below is built from real dependencies. Each sub-task sits in the earliest wave after all the tasks it depends on; completed tasks keep their original waves.
- Anything outside this scope goes in `backlog.md`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["0.1"] },
    { "id": 1, "tasks": ["0.2"] },
    { "id": 2, "tasks": ["0.3", "0.4", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6"] },
    { "id": 3, "tasks": ["1.7", "2.1", "2.2"] },
    { "id": 4, "tasks": ["2.3", "2.4", "2.5", "2.6", "2.7", "3.1", "3.2", "6.1", "7.1", "8.1", "8.3", "9.3"] },
    { "id": 5, "tasks": ["2.8", "2.9", "3.3", "4.1", "5.1", "7.2", "7.3", "8.2", "8.4", "9.4", "9.5", "10.1"] },
    { "id": 6, "tasks": ["4.2", "5.2", "6.2", "6.4", "9.1", "9.6", "9.7", "9.8"] },
    { "id": 7, "tasks": ["4.3", "4.4", "6.3", "9.2", "10.2", "10.4", "10.6"] },
    { "id": 8, "tasks": ["5.3", "6.5", "7.4", "10.3", "10.5", "10.7", "10.8", "10.9", "11.1", "14.5"] },
    { "id": 9, "tasks": ["5.4", "5.5", "5.6", "5.7", "7.5", "7.6", "8.5", "8.7", "11.2"] },
    { "id": 10, "tasks": ["8.6", "8.8", "11.3"] },
    { "id": 11, "tasks": ["11.4"] },
    { "id": 12, "tasks": ["11.5", "12.1", "12.2", "14.1", "14.2"] },
    { "id": 13, "tasks": ["12.3", "13.1", "14.3", "14.6", "14.7"] },
    { "id": 14, "tasks": ["13.2", "13.5", "14.4", "15.1", "15.2"] },
    { "id": 15, "tasks": ["13.3"] },
    { "id": 16, "tasks": ["13.4", "13.6"] },
    { "id": 17, "tasks": ["13.7"] },
    { "id": 18, "tasks": ["19.1"] },
    { "id": 19, "tasks": ["19.2"] },
    { "id": 20, "tasks": ["20.1"] },
    { "id": 21, "tasks": ["20.2", "20.3", "20.4"] },
    { "id": 22, "tasks": ["21.1", "22.1", "23.1"] },
    { "id": 23, "tasks": ["21.2", "22.2", "23.2"] },
    { "id": 24, "tasks": ["21.3", "22.3", "23.3"] },
    { "id": 25, "tasks": ["21.4", "22.4", "23.4"] },
    { "id": 26, "tasks": ["21.5", "22.5", "23.5"] },
    { "id": 27, "tasks": ["21.6", "22.6", "23.6"] },
    { "id": 28, "tasks": ["21.7", "22.7", "23.7"] },
    { "id": 29, "tasks": ["23.8"] },
    { "id": 30, "tasks": ["23.9"] },
    { "id": 31, "tasks": ["24.1", "24.2"] },
    { "id": 32, "tasks": ["24.3"] },
    { "id": 33, "tasks": ["24.4", "24.5", "24.6"] },
    { "id": 34, "tasks": ["25.1", "25.2", "25.3"] },
    { "id": 35, "tasks": ["25.4", "25.5"] },
    { "id": 36, "tasks": ["25.6", "25.7"] },
    { "id": 37, "tasks": ["25.8"] },
    { "id": 38, "tasks": ["26.1", "26.2", "26.3"] },
    { "id": 39, "tasks": ["26.4"] },
    { "id": 40, "tasks": ["26.5", "26.6"] },
    { "id": 41, "tasks": ["27.1"] },
    { "id": 42, "tasks": ["27.2"] },
    { "id": 43, "tasks": ["27.3", "27.4"] },
    { "id": 44, "tasks": ["27.5"] },
    { "id": 45, "tasks": ["27.6"] },
    { "id": 46, "tasks": ["27.7", "27.8", "27.9"] },
    { "id": 47, "tasks": ["27.10"] },
    { "id": 48, "tasks": ["28.1"] },
    { "id": 49, "tasks": ["28.2", "28.3"] }
  ]
}
```
