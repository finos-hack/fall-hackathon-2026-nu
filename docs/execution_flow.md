# Execution flow by framework

Order of files invoked and what each does. Paths are relative to `ai-governance-intelligence-platform/`. Built from reading the source on 2026-11-16 and updated after the dashboard, hash-rule and versioning work; the legacy section lists what the main flow does not use.

Shared helpers used by all three frameworks (`shared/src/agip_shared/`):
`hashing.py` (sha256 and canonical JSON/hash), `contracts.py` (pydantic models: `AgentTask`, `AgentResult`, `SpectralRun`, `FactSet`, `RiskProfile`, `Decision`, `Extraction_Record` ...), `settings.py` (env-driven Settings), `paths.py` (`resolve_within` path containment), `gateway/model_gateway.py` (LLM access: `none`, `replay`, `bedrock`; scrubs secrets and paths), `gateway/recorder.py` (reads and writes recorded LLM outputs), `gateway/runtime_strands.py` (Bedrock via Strands; `StrandsRuntime(temperature=, steering=, steering_retries=)`; steering is a Strands `SteeringHandler` that rejects a model answer failing a check and retries with guidance, at most 2 times; `run_agent` runs a tool-using agent), `versioned_write.py` (hash rule: a `.versions` index per folder keeps `inputs_hash` and `content_hash` for each file; same inputs skip regeneration, changed content gets version +1).

---

## 1. Rule Authoring (`rule-authoring-framework/src/rule_authoring/`)

Purpose: turn AIGF/CCC material (or uploaded documents) into approved catalog entries, then compile them into Spectral rulesets. Only step 2 uses an LLM; risk likelihood and impact come from the Decider (`scoring.py`).

| # | File | Invoked by | What it does inside |
|---|---|---|---|
| 1 | `sources_aigf.py` | `seed_recordings.py`, tests, manual call | `read(paths)` expands paths, parses `ri-*.md` / `mi-*.md` YAML frontmatter, returns sorted `SourceItem`s and `SourceError`s (malformed files skipped, reported with path and field). Deterministic. No LLM |
| 1 | `sources_ccc.py` | manual call only (no importer found) | Same contract for FINOS CCC `controls.yaml`, `threats.yaml`, `capabilities.yaml`. Collects references, returns `SourceItem`s and `SourceError`s |
| 2 | `extraction.py` | `seed_recordings.py`, tests (no CLI or pipeline step calls it) | `body_of_markdown` strips frontmatter. `extract()` builds the input, loads the prompt file, calls `ModelGateway.complete("extraction", version, ...)`, validates the reply against the `Extraction` pydantic schema (candidate rule, triggers, likelihood, impact, remediation) and returns a `DRAFT` item with `extraction_input_hash` and `prompt_version`. `item_key` makes the stable ID (`mi-6` becomes `AIGF-MI-006`). For AIGF and uploaded (`UPL`) items the Rule_Code is fixed by code (`rule_code_for`): an existing catalog code is kept, else `risk-aigf-ri-001`, `ctl-aigf-mi-006` or `ctl-upl-<slug>`. The prompt is extended at run time with the allowed Scoring_Profile dimensions and the checkable taxonomy fields. `_rule_problem` drops a candidate rule unless it tests a taxonomy field with `given` = `$.nodes[?(@['node-type']=='<type>')].metadata` and a `pattern` or `enumeration`; the DRAFT is kept as inexpressible with the reason. `steering_check()` applies the same checks live through Strands steering. The prompt (`prompts/extraction.v1.md`) asks for `candidate_rule: null` plus `inexpressible_reason` when no field fits. `to_catalog_entry` converts a stored DRAFT into a catalog entry with `spectral_rules`, control configurations or risk fields |
| 2 | `extract_sources.py` | `rule_authoring.ingest --extract`; dashboard `POST /rules/new` (`extract_uploads`) | Runs `extraction.extract` over source or uploaded items, writes drafts under the hash rule (unchanged input and prompt: no new call), scores AIGF risks through `scoring.py`, and returns a summary (drafted, inexpressible, errors, missing, unchanged, versions) |
| 2 | `scoring.py` | `extract_sources.py`; `ingest --scores decider\|llm` | `DeciderScorer` asks the Strands Decider two `score` questions per risk (likelihood, impact) with the Scoring_Profile scales and keeps the most probable level and its confidence. Confidence below 0.5 is flagged `low_confidence`. Answers are recorded by input hash in `fixtures/recordings/decider-scores` (or `<data>/llm-records/decider-scores`). If the Decider is unavailable it falls back to the LLM scores and records the reason |
| 2 | `upload.py` | dashboard `rules.py` | `parse_upload(name, bytes)` for `.md`/`.markdown` (AIGF `ri-`/`mi-` files keep AIGF IDs, other Markdown becomes `UPL-<slug>`) and `.yaml`/`.yml` CCC fragments. UTF-8, 1 MB per file, 20 items per run; other types are rejected with a message. Never raises on bad input |
| 2 | `seed_recordings.py` | `python -m rule_authoring.seed_recordings <aigf_docs>` | Reads AIGF items, builds the "model output" from the already-approved catalog entry (`output_for`), writes it through the `Recorder` with model `recorded-seed`. Lets replay mode run extraction with no Bedrock |
| 3 | `merge.py` | `python -m rule_authoring.merge [--drafts DIR] [--catalogs DIR] [--ids ...]`; dashboard after each upload | Merges drafts into `controls`/`risks` catalogs: new item becomes DRAFT; same content is unchanged; changed APPROVED item becomes DRAFT with version +1 and keeps `previous_approved`, which compile still uses until the new version is approved |
| 3 | `versioning.py` | `merge.py`, `approval.py`, `compile.py`, dashboard | `find_entry`, `catalog_file`, content hash of an entry (lifecycle fields excluded) and `write_catalog`, which keeps the YAML comment header |
| 3 | `approval.py` | `python -m rule_authoring.approval approve <id> --by <name>`; dashboard `POST /api/rules/{id}/approve` | Moves one item through `DRAFT -> IN_REVIEW -> APPROVED`, stamping approver, role, rationale and time; records the catalog version on approval. Risks need `confirm` of likelihood and impact first. `approve_in_catalog` edits `*.catalog.yaml`; `approve` works against any store. Errors if the item is not DRAFT |
| 4 | `consistency.py` | `python -m rule_authoring.consistency`; called inside `compile.compile_all` | Loads both catalogs, fails on duplicate items, conflicting content, duplicate Rule_Code, and a referenced Rule_Code defined nowhere. Names both locations. Exit 1 on error |
| 5 | `compile.py` | `python -m rule_authoring.compile`; `demo.sh`; `governance_execution.coordinator` (via `ruleset_info`) | `compile_all`: runs `consistency.check`, loads custom functions from `rulesets/functions`, compiles `controls.catalog.yaml` and `risks.catalog.yaml` keeping only APPROVED items (a `previous_approved` copy stands in for a changed item until it is approved), sorts rules by Rule_Code, writes `rulesets/controls.spectral.yaml` and `risks.spectral.yaml`. Unchanged rules leave the ruleset bytes alone; a change raises the catalog top-level `version:` (edited in place), which is the ruleset header version (both are 2 now). Reports inexpressible rules by code. `ruleset_info` returns version and hash of a ruleset |
| - | `paths.py` | all of the above | `FRAMEWORK_ROOT`, seed dir, registry path |

Order for a new rule: `sources_*` or `upload.parse_upload` -> `extraction.extract` (LLM, DRAFT; `scoring` for risks) -> `merge` into the catalog as DRAFT -> `approval` -> `consistency` -> `compile` -> rulesets used by Governance. The dashboard runs the same chain (section 3f).

Config and data it reads or writes: `catalogs/controls.catalog.yaml`, `catalogs/risks.catalog.yaml`, `catalogs/drafts/`, the extraction prompt file (`PROMPT_FILE` in `extraction.py`), `governance-execution-framework/config/taxonomy.yaml` and the Scoring_Profile (read only), `rulesets/*.spectral.yaml`, `rulesets/functions/`, `.versions` index files.

---

## 2. CALM App Generation (`calm-app-generation-framework/src/calm_generation/`)

Purpose: build the patterns and the reference-architecture (RA) templates, then turn a filled attributes form into an App_Model. The build-time scripts and the instantiate path use no LLM. The only LLM use is the two optional dashboard agents (pattern draft, `ra_agent.py`).

### 2a. Build time (run when patterns or a composition spec change; the dashboard writes the same files, section 3f)

| # | File | Invoked by | What it does inside |
|---|---|---|---|
| 1 | `scripts/build_patterns.py` | `uv run python scripts/build_patterns.py` | Builds the seed pattern JSON files (`patterns/P*.json`) from a specification table: nodes, ports, `connects` relationships, controls, risks. Deterministic. The library now holds P02, P03, P07, P08, P11-P17 (P15 and P16 come from `scripts/build_cyber.py`, P17 was created in the UI) |
| 1 | `scripts/build_cyber.py` | `uv run python scripts/build_cyber.py` | Idempotent (hash rule). Adds the cyber remediation pieces: taxonomy attributes, patterns P15 High-Impact Action Approval and P16 Controlled Remediation, catalog rules AIGF-MI-024, AIGF-MI-018, AIGF-RI-024, and the RA05-CYBER-REMEDIATION compose, question and consistency files |
| 1 | `pattern_builder.py` | dashboard Build Pattern | `check_spec` validates a YAML spec; `field_conflicts` requires a field name that already exists in the library to keep its exact schema; `build` makes the CALM pattern; `save` writes a DRAFT under the hash rule (unchanged: no write; changed: version +1, registry entry back to DRAFT); `mark_approved` sets PUBLISHED and file status APPROVED; `next_id` suggests the next free id |
| 1 | `draft_agent.py` | `calm_generation` workflow; Build Pattern | `PatternDraftAgent(cache_dir=)` drafts a pattern from a spec and caches by inputs hash (same inputs: no model call) |
| 2 | `pattern_library.py` | `composer.main`, tests | `load_patterns` reads `patterns/`. `publish(pattern, validator, store, approver)` accepts a pattern only if `calm validate -p` reports no errors and an approver is named. `as_candidate` marks live-drafted patterns CANDIDATE. `publish_template` does the same for templates |
| 3 | `composer.py` | `python -m calm_generation.composer [spec]` | Reads `templates/RA03-LITE.compose.yaml`. `compose()` merges the chosen pattern nodes property by property (same property defined differently = conflict naming both patterns), applies `bind` constants, adds `connects` and `options` relationships, writes sorted-key `templates/RA03-LITE.json` with source-pattern hashes in metadata. Prints `RA03-LITE.json sha256=...` |
| 3b | `ra_agent.py` | dashboard Build Reference Architecture | `generate(description, ra_id, complete, calm=, max_rounds=4)`: the Strands agent proposes a compose spec from PUBLISHED patterns only; the code loop runs the Composer, `calm validate -p` and the question checks and sends errors back for up to 4 rounds. `questions_for` derives one question per option, enum, number and boolean field |
| 3b | `ra_builder.py` | dashboard Build Reference Architecture | `preview` composes and checks compose, questions and consistency text without writing; `save` writes template, compose, questions and consistency files under the hash rule as DRAFT (`ra-version` +1 on change) |
| 3b | `questions.py` | `ra_builder.py`, Generate CALM | `load_questions(ra_id)` reads `templates/<ra>.questions.yaml`; `check_questions` checks them against the form; `apply_answer` turns an answer into attribute values (`set`) and option choices (`options`); `summary` text for the report |
| 4 | `attributes.py` | `scripts/build_forms.py` | `form_for(template, text, status)` lists one attribute per free (non-const) metadata property plus one entry per options relationship. Refuses unpublished templates (`TemplateNotPublished`) |
| 5 | `scripts/build_forms.py` | `uv run python scripts/build_forms.py` | Writes `governance-execution-framework/forms/ra03-lite.attributes.yaml` and the filled `v1` to `v4.attributes.yaml` variant forms (RA03-LITE is now ra-version 2, recomposed from P02 v2) |

### 2b. Instantiate time (called from Governance `units/calm_builder.instantiate`)

| # | File | What it does inside |
|---|---|---|
| 1 | `attributes.py` `validate` | Checks the filled form: presence, type, allowed values, lower bounds, placeholder coverage. Upper bounds are left to `calm validate`. Also `option_choices`, `attributes_hash` and `consistency_errors`, which reads `templates/<ra>.consistency.yaml` and rejects an attribute that contradicts the chosen option (an empty attribute is derived from the option) |
| 2 | (Governance) `adapters/calm.py` `generate` | Runs `calm generate -p <template> --option-choices ...` |
| 3 | `placeholders.py` `fill` | Replaces `[[ NAME ]]`, `[[ BOOLEAN_X ]]` and `-1` placeholders from the form values and adds omitted enum properties. Any leftover placeholder or missing required property is returned with its JSON path and no model is produced |
| 4 | `composer.COMPOSER_VERSION` | Recorded in the Generation_Manifest |
| 5 | (Governance) `adapters/calm.py` `validate` | Runs `calm validate -p <template> -a <model>` |

Not in the main flow: `validate_v12.py` and `calm_finos.py` were removed in task 16.

---

## 3. Governance Execution (`governance-execution-framework/src/governance_execution/`)

Purpose: take one App_Model, validate it, assess controls and risks, decide, and show the result. LLM use is limited to remediation text. The Decider is advisory and only sees UNMAPPED facts.

### 3a. Entry points

| Entry | File chain |
|---|---|
| `bash scripts/demo.sh` | `uv sync` -> `rule_authoring.consistency` -> `rule_authoring.compile` -> `governance_execution.demo` -> `dashboard.app` |
| `python -m governance_execution.demo` | `demo.py` -> `exec/factory.py` -> per variant `units/calm_builder.instantiate` -> `exec/coordinator.run` |
| Dashboard `POST /rules/new`, `/rules/runs/{run}/compile` | `dashboard/routers/rules.py` -> `rule_authoring.upload`, `extract_sources`, `merge`, `compile` (section 3f) |
| Dashboard `POST /patterns/new`, `/architectures/generate`, `/architectures/new` | `dashboard/routers/architecture.py` -> `calm_generation.pattern_builder`, `ra_agent`, `ra_builder` |
| Dashboard `POST /applications/new/template`, `/applications/new` | `dashboard/routers/mvp.py` -> `units/requirements.py`, `calm_generation.questions`, then the same `instantiate` and `coordinator.run` |
| Dashboard `POST /catalogs/{kind}/{id}/approve`, `/api/assessments/{trace}/approve` | `dashboard/routers/mvp.py` -> `rule_authoring.approval`, `calm_generation.lifecycle`, `humantasks`, then resume |
| Dashboard `POST /api/instantiate`, `/api/upload`, `/api/assess`, `/api/replay/{trace}` | `dashboard/routers/api.py` -> same `instantiate` and `coordinator.run`, or `obs/replay.py` |
| `scripts/seed_recordings.py` | Same chain, with a recording gateway; writes LLM and Decider fixtures (and CLI recordings with `--record-cli`) |

### 3b. Wiring: `exec/factory.py` `build(mode, ...)`

1. Reads `Settings`. Opens `MemoryRepository` (`store/repository.py`).
2. Chooses CLI runners: `real` (`adapters/calm.default_runner`, `adapters/spectral.default_runner`), `record`, or `replay` (`adapters/recorded.py`).
3. Builds `CalmAdapter` and `SpectralAdapter`. `resolve_spectral` finds `.tools/node_modules/.bin/spectral`.
4. Builds the `ModelGateway` (none for `no-llm`, replay recordings for `replay`, otherwise from settings, Bedrock through `StrandsRuntime`).
5. Loads config via `UnitContext.default_config()` (`config/*.yaml` plus the two catalogs) and builds `DeciderGateway` (`adapters/decider.py`).
6. Returns `Coordinator(ctx)` and `DirectAdapter()`.

### 3c. Instantiate: `units/calm_builder.instantiate(form, ...)`

1. Refuses a template that is not `PUBLISHED`.
2. `calm_generation.attributes.validate` (status `BLOCKED_ATTRIBUTES` on errors).
3. `calm.generate` -> `placeholders.fill` (status `LEFTOVERS` if any placeholder remains).
4. Builds the Generation_Manifest (template hash, source patterns, attributes hash, option choices, CLI version, output hash, fill record).
5. `calm.validate` -> `validation_dict`; `guidance_for` turns each error path into a correction hint for the form attribute (V4 path).
6. With a sink: writes `app_model`, `generation_manifest`, `calm_validation` artifacts and a CALM_Catalog entry when VALID.

### 3d. Assess: `exec/coordinator.Coordinator.run(app_model, executor, template_id, source)`

Order, with the file that does each step. Every step is one `AgentTask` through `Coordinator.run_step` -> `units/registry.invoke` and passes artifact references only.

| # | Step | Unit and action (`units/registry.py`) | Inner files and logic |
|---|---|---|---|
| 0 | open trace | `obs/otel.Tracing.assessment` | New Trace_ID, one span per stage, secret scrubbing |
| 0 | store input | `store/sink.py` -> `store/artifacts.py` | Writes `app_model` as an immutable artifact (`<data>/artifacts/<trace>/<kind>/<id>.json`, canonical JSON, SHA-256) and records it in the repository |
| 1 | `validate_calm` | `calm_builder_unit` (`validate`) | `CalmAdapter.validate` against the template; writes `calm_validation`. Status VALID continues with `GOVERNANCE_STEPS`; anything else switches to `BLOCKED_STEPS` (step 6 and 7 only) |
| 2 | `extract_facts` | `risk_unit` (`facts`) | `core/facts.extract` maps node metadata to the taxonomy (`config/taxonomy.yaml`) as MAPPED / UNMAPPED / UNKNOWN facts. If a Decider is set: `core/catalogs.checked_fields` finds fields already covered by rules, `adapters/decider.classify_unmapped` asks the Decider only about UNMAPPED facts (`default_post` translates the platform request, a list of questions, into the Strands Decider schema `questions: {name: {type, instructions, criteria}}` and the answers back; choice questions may carry `descriptions`), `core/acceptance.evaluate` accepts or rejects each answer (`config/decider_policy.yaml`). Writes `facts` and `decider_calls` |
| 3a | `spectral_controls` (parallel) | `control_unit` (`lint`) | `core/spectral_runs.run_one` -> `SpectralAdapter.lint` with `rulesets/controls.spectral.yaml`. Writes `spectral_controls_raw` and `spectral_controls_parsed` |
| 3b | `spectral_risks` (parallel) | `risk_unit` (`lint`) | Same with `risks.spectral.yaml` |
| 4 | `control_gap` | `control_unit` (`assess`) | `units/control_assessment.assess` joins findings to controls by Rule_Code (PASS = design-level evidence only, Spectral ERROR = ERROR never PASS), `core/gap.gap_level` applies `config/gap_rule.yaml`. Writes `control_gap` |
| 5 | `risk_profile` | `risk_unit` (`assess`) | `units/risk_assessment.assess` finds triggered risks, looks up severity in `config/scoring_profile.yaml` (likelihood x impact matrix), takes the highest as profile level, marks mandatory triggers UNEVALUABLE when inputs are UNMAPPED or Spectral errored, and computes the separate approval tier with `risk_tier.classify_risk`. Writes `risk_profile` |
| 6 | `decide` | `decision_unit` (`decide`) | `units/decision_remediation.decide` -> `core/decision.decide`: evaluates `core/gates.evaluate` in order (`config/gates.yaml`, first that fires wins; G2 fires when AIGF-MI-024 fails (a payment or production-changing action without human approval; the gate id is still `G2-PAYMENT-AUTH`); G3 = unevaluable mandatory trigger gives INDETERMINATE), then `config/decision_matrix.yaml`, then the design-only cap. No LLM or Decider input. Writes `decision` |
| 7 | `remediate` | `decision_unit` (`remediate`) | `collect` gathers catalog remediation text plus CALM guidance; `remediate` asks the `ModelGateway` for a Fix Prompt, or returns a deterministic numbered list in `no-llm` mode. Writes `remediation` |
| 8 | wrap up | `coordinator.collect_versions`, `sink`, `repo.save_assessment` | Writes `versions` (rulesets, catalogs, config versions, prompt versions, model, Decider, CLI versions, app model hash), `trace` (step log), and the assessment record with executor, mode, decision, status |

If any step returns ERROR, `run` writes a `unit_error` artifact, sets assessment status `FAILED` and reports no decision.

### 3d-1. Statuses and Option B

Three values are stored separately on the assessment record:

| Field | Values |
|---|---|
| Assessment status | QUEUED, RUNNING, WAITING_FOR_HUMAN, COMPLETED, FAILED, BLOCKED |
| Validation status | VALID, INVALID, INCOMPLETE, ERROR |
| Decision | APPROVED, APPROVED_WITH_CONDITIONS, RESTRICTED, REJECTED, INDETERMINATE (or none) |

- `BLOCKED`: CALM validation is not VALID, so only steps 6 and 7 run. The decision stays empty. No gate G1 exists (see `deliberate-changes.md`).
- `INDETERMINATE`: a mandatory risk trigger could not be evaluated (gate G3). The assessment status is `COMPLETED`.
- Option B (Decider): only UNMAPPED facts with no deterministic mapping go to the Decider. An answer that passes `config/decider_policy.yaml` becomes a recorded accepted classification and the fact becomes INFERRED (raw answer kept). A HUMAN_REVIEW answer creates a human task. ABSTAIN or ERROR leave the fact UNKNOWN or UNMAPPED. The decision never reads Decider output directly.
- Human task wait and resume: pending human tasks are listed in the report and the run continues. Only when `decider_policy.block_on_pending_human` is true does the run stop with status `WAITING_FOR_HUMAN`. Resume after the task is answered with `uv run python -m governance_execution resume <trace>` (see `resume --help` for options).

### 3e. Executor: `exec/direct_adapter.py`

`DirectAdapter.execute` walks the step list in order. Consecutive steps with the same `parallel_group` (the two Spectral lanes) run in a `ThreadPoolExecutor`, with the OTel context attached to each thread. It appends a log row per step, stops on the first non-OK step, and merges output artifact references into `refs` for the next step. Its label `Direct_Adapter` (development-only) is stored on the assessment. Fluxnova is not implemented.

### 3f. Read side

| File | What it does |
|---|---|
| `dashboard/app.py` | `create_app` builds FastAPI + Jinja2 on port 8001, mounts `routers/mvp.py`, `rules.py`, `architecture.py`, `pages.py` and `api.py`. Sidebar (`templates/base.html`): Overview; Catalog (Controls Catalog, Risk Profile Catalog, CALM Patterns Catalog); Source Registry; Generate Rules; Architecture (Build Pattern, Build Reference Architecture, Generate CALM); Assessments |
| `dashboard/data.py` `ReportStore` | Reads persisted artifacts only: summaries, bundle per trace, risk matrix, Mermaid for architecture (nodes coloured by worst finding) and flow |
| `core/trace.py` | Builds the traceability graph: decision -> gate or matrix cell -> control or risk -> Rule_Code and JSON path -> CALM element -> pattern and template version -> AIGF/CCC source ID. Walkable both ways |
| `routers/pages.py` | HTML pages: assessments, report, flow, architecture, risk matrix, decider, trace explorer, static export, catalogs (`/catalogs/controls`, `/risks`, `/patterns`, `/templates`), `/source-registry/{section}`, versions, variants, `/healthz` |
| `routers/mvp.py` | Overview (6 metrics), review queue (`/review`, `POST /api/review/{id}/act`, `/api/assessments/{trace}/resume`), registry and lineage pages, Generate CALM (`/applications/new`, `/applications/new/template`), and the MVP approve endpoints: `POST /catalogs/{kind}/{id}/approve` (controls and risks go APPROVED, a risk click also confirms likelihood and impact; patterns and RAs go APPROVED then PUBLISHED) and `POST /api/assessments/{trace}/approve` (one value per open Decider task, claim and complete as `dashboard-reviewer` / `governance_admin`, then resume). No login; role checks are in the backlog |
| `routers/rules.py` | Generate Rules: `GET/POST /rules/new` (upload, extract, merge as DRAFT, redirect), `GET /rules/runs/{run}` (results, current catalog status, Approve buttons), `POST /rules/runs/{run}/compile`. Runs are kept in `<data>/rule-runs/<run_id>/` (uploads, drafts, `summary.json`). Uses Bedrock with temperature 0.1 and steering when `MODEL_PROVIDER=bedrock`, otherwise recordings only |
| `routers/architecture.py` | Build Pattern: `GET/POST /patterns/new` (`action=draft` asks the Strands agent, `action=save` validates and saves a DRAFT; a revised pattern lists the RAs composed from the old version with a Recompose link). Build Reference Architecture: `GET /architectures/new`, `POST /architectures/generate` (agent), `POST /architectures/new` (`action=preview` writes nothing, `action=save` writes a DRAFT). Agent drafts need `MODEL_PROVIDER=bedrock` and `BEDROCK_MODEL_ID`; manual YAML editing works without them |
| `routers/api.py` | `/api/upload` (1 MB limit), `/api/assess`, `/api/instantiate`, `/api/attributes-form/{id}`, `/api/rules/{id}/approve`, `/api/replay/{trace}` |
| `obs/replay.py` | `replay(trace, coordinator, executor)` re-runs the assessment on recordings with zero model calls, new Trace_ID, compares normalised artifact fingerprints. A missing recording fails and names it |

### 3g. Storage

The governance catalog store keeps the hash rule: different content at the same (id, version) is stored as a new DRAFT version (lifecycle fields are not content). `store/repository.py` has three backends behind one interface: `MemoryRepository` (used by demo, factory and tests, backed by files), `SqlRepository` (py-pglite or SQLite), and YAML seed loading. `store/db.py` starts py-pglite on TCP 5433. `store/artifacts.py` is the immutable file store (rewriting different content raises `ArtifactImmutableError`; reads can verify the hash).

### 3h. Removed in task 16

`pipeline.py`, `applicability.py`, `findings.py`, `scoring.py` of Governance (the older rule-registry pipeline; not related to `rule_authoring/scoring.py`), `calm_finos.py`, `validate_v12.py`, `ingest_finos.py`, `transform.py`, `catalogs/seed/` and the empty `governance_execution/gateway/` package no longer exist. `risk_tier.py` stays and only computes the approval tier inside `units/risk_assessment.py`, never severity (a consistency test guards this). `units/rule_authoring.py` in Governance exposes a `ruleset_info` action and `extract_and_store`, and is not part of the assessment step list.

---

### 3i. Generate CALM from the dashboard (`routers/mvp.py`, `units/requirements.py`)

| # | Step | File and logic |
|---|---|---|
| 1 | Pick the template | `POST /applications/new/template`: only PUBLISHED templates are offered. With "choose for me", `requirements.choose_template` asks the Decider to pick from the description (policy-gated) |
| 2 | Questions | `calm_generation.questions.load_questions` reads `templates/<ra>.questions.yaml`; each answer sets attributes and/or option choices. "Not sure, I will describe it" goes to `requirements.answer_questions` (Decider maps the sentence to an answer, policy-gated). `requirements.infer_values` fills remaining empty options and enum attributes from the description |
| 3 | Check | `attributes.validate` and `consistency_errors` (`templates/<ra>.consistency.yaml`): a contradiction is rejected before `calm generate` and shown on the form |
| 4 | Generate | `calm generate -p <template> --option-choices` receives only the template and the option choices; attribute values are filled afterwards by `placeholders.fill`; then `calm validate`, then `Coordinator.run` as in 3d. The same template files are reused for every app |
| 5 | Report | Section "Inputs and requirements" lists each value and who set it (user answer, Decider, derived from option) |

`scripts/fluxnova_e2e.py` (option `--attributes FILE...`) runs the same chain without the UI (optional free-text `requirements:` filled by the Decider under the same policy).

---

## 4. End-to-end order (what `demo.sh` runs)

1. `rule_authoring.consistency` then `rule_authoring.compile` -> `rulesets/*.spectral.yaml`.
2. `governance_execution.demo`: `factory.build` -> for each of V1-V4: `calm_builder.instantiate` -> `Coordinator.run` (steps 0 to 8 above) -> prints the decision.
3. `dashboard.app` serves the stored artifacts on port 8001.

Build-time prerequisites, done once and committed: `build_patterns.py`, `build_cyber.py`, `composer`, `build_forms.py`, `seed_recordings.py`. The dashboard writes straight into the repo pattern, template, registry and catalog files (no scratch copy), so run `git status` after using it.
