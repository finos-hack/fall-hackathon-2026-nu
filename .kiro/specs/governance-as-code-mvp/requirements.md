# Requirements Document

## Introduction

The Governance-as-Code MVP is the hackathon slice of the Agent Governance Intelligence Platform (AGIP), defined in `agent_governance_intelligence_platform_detailed_proposal.md` (the Proposal). It demonstrates, at design time and with synthetic data, one application: **Invoice-to-Payment Lite** (Reference Architecture template `RA03-LITE`).

The Platform has three frameworks:

1. **Rule Authoring.** Turns FINOS AIGF and CCC sources into two normalized YAML catalogs (Control Rules, Risk Assessment Rules), each with remediation, and compiles them into two versioned Spectral rulesets. An LLM proposes; a human approves.
2. **CALM.** A Pattern Library (CALM 1.2 patterns), a Composer that merges selected patterns into one RA template (a CALM 1.2 pattern), and an instantiation flow that produces and validates an application CALM model with `calm generate` and `calm validate`.
3. **Governance.** Extracts facts, runs two Spectral rulesets on the application CALM JSON, assesses control gaps and the risk profile, issues a deterministic decision from a Decision Matrix Catalog, and produces remediation guidance.

**Scope rule.** Anything not needed to show these features for this one application goes in `backlog.md`, not into the build.

**Foundation.** The MVP is built in a NEW standalone repository `ai-governance-intelligence-platform`. Selected modules are COPIED (not moved) from the draft repository `cyber-grc-finos-framework/design-time-agent-security`: `src/models/rule.py`; `src/validator/{calm_finos, applicability, risk_tier, scoring, findings, pipeline}.py`; `governance/controls/registry.yaml`; `governance/rules/*.yaml`; `architecture/calm/VOCABULARY.md`; `architecture/examples/*.json`; `scripts/validate_calm_v12.py`; `scripts/ingest_finos_mitigations.py`; `rule-authoring/` (`transform.py`, `rule.yaml.j2`, `AUTHORING-GUIDE.md`, `mi-*.md`); and the tests that depend only on these files. NOT copied: `src/agent`, `demo*.py`, `agent_runtime.py`, AgentCore files, `uv.lock`, `evaluator.py` (Spectral replaces it). The draft repository is not modified.

**Principles.** CALM is the canonical architecture. Models propose; only validated facts and deterministic rules decide. Missing evidence is never PASS. Unknown is a first-class result. A Spectral pass on CALM is design-level evidence only. Everything that can change a decision is versioned. The assessment path runs without any LLM.

**Fixed decisions.**
1. `risk_tier.py` yields the Agent_Approval_Tier (approval path) only and never sets severity.
2. Risk severity is per triggered risk: likelihood (1-5) x impact (1-5) through the Proposal section 8.4 matrix in a versioned Scoring_Profile labelled "illustrative, not approved policy". Dimensions are never summed.
3. CALMGuard is reused as concepts and assets only, with no runtime dependency.
4. Strands Decider 2B is advisory, runs locally, and is used only where no deterministic check exists.
5. Fluxnova is in scope behind a 30-minute spike gate with a development-only fallback.

### Out of scope

Everything listed in `backlog.md`, including build-time and runtime evidence, residual-risk reassessment, and live (non-recorded) LLM flows beyond the optional paths named below.

## Glossary

- **Platform**: The AGIP MVP in the new repository `ai-governance-intelligence-platform`.
- **Application**: Invoice-to-Payment Lite, the single demonstration application (design time, synthetic data).
- **AIGF**: FINOS AI Governance Framework in `ai-governance-framework`; risks in `docs/_risks/ri-*.md`, mitigations in `docs/_mitigations/mi-*.md`, each with YAML frontmatter and markdown prose.
- **CCC**: FINOS Common Cloud Controls catalogs: `common-cloud-controls/catalogs/{core/core, ai-ml/multi-agent-refarch}/{controls,threats,capabilities}.yaml`.
- **Source_Adapter**: Deterministic reader of AIGF frontmatter or CCC YAML that outputs native IDs, titles, and references.
- **ModelGateway**: Interface for generative model access with configurable provider, model, and region. Default Bedrock via Strands; "none" is a valid provider.
- **Extraction_Record**: Persisted LLM extraction with prompt version, model, input hash, and output.
- **Rule_Status**: `DRAFT` or `APPROVED`. Only `APPROVED` rules are compiled.
- **Control_Rules_Catalog**: Normalized YAML catalog: control (native AIGF mitigation or CCC control ID) -> one or more rule configurations -> Spectral rules, with severity, mandatory flag, remediation, and source references.
- **Risk_Rules_Catalog**: Normalized YAML catalog: one rule per AIGF risk with dimension triggers expressed as Spectral rules over CALM metadata, likelihood 1-5, impact 1-5, remediation, and source references.
- **Spectral_Ruleset**: A Spectral-compatible YAML file `rules: {code: {description, message, severity, given, then: {field, function, functionOptions}}}`. Two exist: `controls.spectral.yaml` and `risks.spectral.yaml`.
- **Rule_Code**: The Spectral rule key; the join key between a Spectral result and a catalog item.
- **Custom_Function**: A JavaScript Spectral function, permitted only when no core function fits.
- **Pattern**: A technology-neutral CALM 1.2 pattern JSON in the Pattern_Library, with metadata listing related control rule IDs and risk rule IDs.
- **Pattern_Library**: Approved Patterns stored as files plus catalog DB records, separate from the CALM Catalog's copies.
- **CALM_AI_Assets**: Prompt and skill files in `architecture-as-code/calm-ai`.
- **Composer**: Deterministic component outside the CALM CLI that merges selected Patterns into one RA_Template.
- **RA_Template**: One CALM 1.2 pattern composed from Patterns, with RA ID, version, and source Pattern versions. Status `DRAFT` or `PUBLISHED`.
- **CALM_Catalog**: Store of RA_Templates and App_Models.
- **Attributes_Form**: Structured YAML form generated from an RA_Template's fields and options.
- **Placeholder_Fill**: Deterministic step replacing every `calm generate` placeholder (`[[ NAME ]]`, `[[ BOOLEAN_X ]]`, `[[ REF_X ]]`, and `-1` for numbers) with attribute values.
- **App_Model**: The CALM 1.2 architecture JSON of one Application instance after Placeholder_Fill.
- **Generation_Manifest**: Record of one instantiation (see Requirement 10).
- **Variant**: A design-time variant of the Application (V1-V4).
- **CALM_CLI / CALM_Adapter**: Official `calm` CLI; the single component that invokes it with argument lists, a temp directory, and a timeout.
- **Spectral_Adapter**: The single component that invokes the Spectral CLI the same way.
- **Fact**: A discovered attribute with provenance (element ID, JSON path, raw value, normalized value, taxonomy version, mapping status).
- **Dimension**: Autonomy, Data Exposure, Privilege & Capability, Connectivity, Decision Impact, Human Oversight, or Operational Criticality.
- **UNMAPPED**: Mapping status of a Fact matching no Taxonomy entry.
- **Decider**: Strands Decider 2B at `http://localhost:8000`, advisory only.
- **Acceptance_Policy**: Per-task rule deciding `ACCEPTED`, `ABSTAIN`, or `HUMAN_REVIEW` for a Decider answer.
- **Input_Hash**: SHA-256 of canonical JSON (sorted keys, no whitespace) of model name, state, and questions.
- **Control_Gap_Assessment**: Per-control status and a gap level derived from Spectral results.
- **Gap_Level**: `none`, `minor`, `major`, or `critical`.
- **Risk_Profile**: Triggered risks with likelihood, impact, and severity, plus the worst severity as the profile level.
- **Scoring_Profile**: Versioned likelihood/impact scales, severity matrix, and bands. Labelled "illustrative, not approved policy".
- **Agent_Approval_Tier**: Output of `risk_tier.py` (sign-off roles and cadence); not a severity.
- **Mandatory_Gate**: A versioned rule that forces an outcome ahead of the Decision_Matrix.
- **Decision_Matrix**: Versioned Decision Matrix Catalog mapping Gap_Level x risk profile level to a decision.
- **Governance_Decision**: `APPROVED`, `APPROVED_WITH_CONDITIONS`, `RESTRICTED`, `REJECTED`, or `INDETERMINATE`.
- **Remediation_Agent**: Component producing a Fix Prompt or Summary from remediation text; never edits CALM or changes a decision.
- **Unit**: One of five framework-neutral components: Rule Authoring, CALM Builder, Control Assessment, Risk Assessment, Decision & Remediation.
- **AgentTask / AgentResult**: Framework-neutral Pydantic contract passing artifact IDs only.
- **Coordinator**: Thin component invoking Units through the contract.
- **AgentRuntime**: Interface behind which the Strands adapter runs LLM tasks.
- **Workflow_Engine**: Fluxnova BPM (Docker `finos/fluxnova-bpm-platform:latest`, port 8080, REST `/engine-rest`).
- **External_Task_Worker**: Python worker that polls a topic and runs one pipeline step.
- **Direct_Adapter**: Development-only pipeline runner used if the Fluxnova spike fails.
- **Executor**: The runner of an assessment (Workflow_Engine or Direct_Adapter).
- **Artifact**: An immutable, versioned, ID-addressed output stored as a disk file with catalog or run metadata.
- **Trace_ID**: The correlation ID of one assessment.
- **Replay_Mode**: Execution using recorded LLM and Decider outputs.
- **Dashboard**: FastAPI + Jinja2 application on port 8001 reading only persisted Artifacts.
- **Static_Export**: Self-contained HTML export of an assessment report.
- **Spike_Notes**: File recording spike results, versions, output shapes, and contingencies.

## Requirements

### Requirement 1: Repository Foundation and Reuse Record

**User Story:** As a developer, I want a new repository that reuses proven draft modules, so that validated code and tests carry forward without touching the draft.

#### Acceptance Criteria

1. THE Platform SHALL be built in the new repository `ai-governance-intelligence-platform` using copies of the modules listed in the Introduction Foundation paragraph.
2. THE Platform SHALL NOT add a runtime dependency on `calm-guard` or on the draft repository, and SHALL leave the draft repository unmodified.
3. THE Platform SHALL provide `docs/REUSE.md` listing each copied file, its source path, the draft commit hash, and its new role.
4. WHEN the copied tests are run in the new repository, THE Platform SHALL show each passing or listed in a deliberate-change list in Spike_Notes with a reason.
5. THE Platform SHALL keep `risk_tier.py` output as Agent_Approval_Tier only, and the consistency test SHALL fail IF any code path uses it or summed Dimension values to set a severity.
6. THE Platform SHALL document one Git Bash command that installs dependencies and runs all tests with no cloud infrastructure.

### Requirement 2: Tooling Spike Gate

**User Story:** As a developer, I want external tools verified first, so that integration risks surface before dependent code is written.

#### Acceptance Criteria

1. WHEN the spike is run, THE Platform SHALL record the CALM_CLI version and the `calm validate -a <arch> -f json` and `calm validate -p <pattern> -a <arch> -f json` output shapes for a valid, a warning-only, and an invalid case, confirming that VALID means `hasErrors` is false.
2. WHEN the spike is run, THE Platform SHALL run `calm generate -p <template> --option-choices <file> -o <out>` twice and record byte-identity and placeholder behaviour, including `[[ NAME ]]`, `[[ BOOLEAN_X ]]`, `[[ REF_X ]]`, and `-1` for numbers.
3. WHEN the spike is run, THE Platform SHALL validate the draft example models with the CALM_CLI, recording whether `ai:agent`, `ai:llm`, and `ai:tool` node types are accepted and whether custom relationship verbs are rejected (CALM 1.2 allows `interacts`, `connects`, `deployed-in`, `composed-of`, `options`).
4. IF the CALM_CLI rejects custom node types or relationship verbs, THEN THE Platform SHALL carry the semantics in `metadata` (and `connects` plus `metadata` for relationships) and SHALL record the choice in Spike_Notes.
5. WHEN the spike is run, THE Platform SHALL record the Spectral CLI version and the JSON output of `spectral lint <file> -r <ruleset> -f json` on a CALM JSON file.
6. WHEN the spike is run, THE Platform SHALL send one `POST /v1/systemone` and one `GET /health` to the Decider and record request, response, and client-side latency.
7. WHEN the spike is run, THE Platform SHALL record whether py-pglite starts in TCP mode on Windows at port 5433 and whether data persists across restarts.
8. WHERE the Fluxnova spike is attempted, THE Platform SHALL limit it to 30 minutes and confirm the REST paths for deployment, external-task fetch-and-lock, complete, failure, and user-task handling.
9. WHEN the spike is run, THE Platform SHALL record whether Bedrock model access works from the configured region.
10. IF any tool is unavailable, THEN THE Platform SHALL record the failure and the chosen contingency in Spike_Notes.
11. THE Platform SHALL take CLI flags, output shapes, and REST paths from Spike_Notes and SHALL NOT use values assumed from the Proposal.

### Requirement 3: Rule Source Adapters

**User Story:** As a rule author, I want sources read deterministically, so that native IDs and references are never produced by a model.

#### Acceptance Criteria

1. WHEN AIGF risk and mitigation files are provided, THE Source_Adapter SHALL read frontmatter and output native ID, title, and references for each.
2. WHEN CCC catalog files are provided, THE Source_Adapter SHALL read controls, threats, and capabilities and output native ID, title, and references for each.
3. THE Platform SHALL process AIGF sources first and SHALL include only 1 or 2 CCC controls in the MVP.
4. IF a source file has missing or malformed frontmatter or YAML, THEN THE Source_Adapter SHALL report the file path and field and SHALL skip that file.
5. THE Source_Adapter SHALL produce identical output for identical input files.

### Requirement 4: LLM Rule Extraction and Approval

**User Story:** As a rule author, I want an LLM to propose rule content from prose that a human then approves, so that authoring is faster but never unreviewed.

#### Acceptance Criteria

1. WHEN a source item is selected, THE Rule Authoring unit SHALL use the ModelGateway (Strands plus Bedrock, provider, model, and region configurable) to extract dimension triggers, likelihood criteria, impact criteria, remediation, and a candidate Spectral rule from the markdown prose.
2. THE Rule Authoring unit SHALL validate each extraction against a schema and store it with Rule_Status `DRAFT`, and SHALL reject schema-invalid output with a reported reason.
3. WHEN a human approves a `DRAFT` rule through a dashboard action or a Fluxnova user task, THE Platform SHALL set its Rule_Status to `APPROVED` and record the approver and timestamp.
4. THE Platform SHALL compile only `APPROVED` rules.
5. THE Platform SHALL persist an Extraction_Record (prompt version, model, input hash, output) for each extraction.
6. THE demo SHALL use recorded approved extraction outputs, and WHERE live re-extraction is enabled, THE Platform SHALL treat its output as a new `DRAFT`.
7. THE Platform SHALL exclude secrets and file paths from LLM inputs.

### Requirement 5: Normalized Rule Catalogs and Single-Source Consistency

**User Story:** As a governance lead, I want two source-neutral catalogs with remediation, so that controls and risks are authored and traced uniformly.

#### Acceptance Criteria

1. THE Control_Rules_Catalog SHALL map each control (native AIGF mitigation or CCC control ID) to one or more rule configurations, each referencing Spectral Rule_Codes and carrying severity, mandatory flag, remediation, and source references.
2. THE Risk_Rules_Catalog SHALL contain one rule per AIGF risk with dimension triggers expressed as Spectral rules over CALM metadata, likelihood 1-5, impact 1-5, remediation, and source references.
3. THE Platform SHALL store both catalogs as YAML, version them, and require non-empty remediation on every item.
4. THE Platform SHALL keep catalog-only fields (severity, mandatory flag, remediation, likelihood, impact) in the catalogs and join them to Spectral results by Rule_Code.
5. THE Platform SHALL merge the draft `registry.yaml` and `rules/*.yaml` into the two catalogs, with each definition in exactly one place.
6. IF a definition appears in more than one source with differing content, THEN THE consistency check SHALL fail and report both locations.
7. IF a Rule_Code is duplicated or referenced but undefined, THEN THE consistency check SHALL fail.

### Requirement 6: Spectral Ruleset Compilation

**User Story:** As a rule author, I want catalogs compiled to Spectral rulesets, so that governance rules execute with a standard linter.

#### Acceptance Criteria

1. WHEN the compile step is run, THE Platform SHALL generate `controls.spectral.yaml` from the Control_Rules_Catalog and `risks.spectral.yaml` from the Risk_Rules_Catalog, each containing only `APPROVED` rules and carrying a version.
2. THE Platform SHALL emit each rule as `{description, message, severity, given (JSONPath), then {field, function, functionOptions}}`.
3. THE Platform SHALL use Spectral core functions where one fits, and SHALL list every Custom_Function with the reason no core function fits.
4. WHEN identical catalogs are compiled, THE Platform SHALL produce byte-identical rulesets.
5. IF a catalog rule cannot be expressed as a Spectral rule, THEN THE Platform SHALL report it by Rule_Code and SHALL NOT omit it silently.
6. THE Platform SHALL record the ruleset version and SHA-256 in each assessment.

### Requirement 7: Architecture Pattern Library

**User Story:** As an architect, I want approved, technology-neutral CALM patterns, so that reference architectures are built from governed parts.

#### Acceptance Criteria

1. THE Pattern_Library SHALL contain P02 API Gateway, P03 Application Service, P07 External System Integration, P08 Relational Data Store, P11 LLM Inference, P12 Tool-Using Agent, P13 Human-in-the-Loop, and P14 Autonomous Agent Execution, each a CALM 1.2 pattern JSON.
2. WHEN a Pattern is drafted, THE Platform SHALL use the LLM with CALM_AI_Assets and the pattern specification, run `calm validate` on the result, and require human approval before publishing it to the Pattern_Library.
3. THE Platform SHALL record in each Pattern's metadata the related control rule IDs and risk rule IDs.
4. THE Pattern_Library SHALL keep its own copy of each Pattern as a file plus a catalog DB record, with version and status.
5. THE Platform SHALL express each Pattern without naming a specific technology.
6. THE CALM Pattern RA Generator SHALL draft Pattern candidates through the ModelGateway, and THE Platform SHALL treat every generated Pattern as an unapproved candidate until it passes `calm validate` and a reviewer approves it as a HumanTask. THE demo MAY use pre-approved Patterns, and provider `none` or `replay` SHALL return recorded candidates.
7. IF a Pattern fails `calm validate`, THEN THE Platform SHALL reject it and report each error.

### Requirement 8: RA Template Composition

**User Story:** As an architect, I want selected patterns merged into one template, so that `calm generate` (which takes exactly one pattern) can instantiate applications.

#### Acceptance Criteria

1. WHEN Patterns are selected, THE Composer SHALL merge them into ONE CALM 1.2 pattern using `const` for fixed values, CALM `options` relationships for variation, and placeholders for free fields.
2. THE Composer SHALL record the RA ID, RA version, and each source Pattern ID and version in the RA_Template.
3. THE RA03-LITE template SHALL include API Gateway, Invoice Processing Service, Invoice Intelligence Agent (`ai:agent`), Payment Agent (`ai:agent`), Foundation Model (`ai:llm`), Payment Tool (`ai:tool`), Payment API (external, simulated), Human Approval Service, Audit Service, and Invoice DB.
4. THE RA03-LITE template SHALL give each agent its own node with permitted tools, autonomy, and privilege in metadata.
5. WHEN the Composer output passes `calm validate`, THE Platform SHALL publish it to the CALM_Catalog with status `DRAFT` or `PUBLISHED`.
6. IF two Patterns define the same component ID with different definitions, THEN THE Composer SHALL report the conflict naming both Patterns and SHALL NOT produce output.
7. WHEN identical Patterns, versions, and Composer version are provided, THE Composer SHALL produce byte-identical output.
8. THE Composer SHALL NOT calculate risk or add controls absent from the Patterns.
9. THE CALM Pattern RA Generator SHALL propose the Pattern selection and placeholder values for an RA_Template from a brief, and the Composer SHALL build the template from that selection. THE generator SHALL NOT write the final template JSON, add controls or calculate risk. THE Platform SHALL publish the template only after `calm validate` passes and a reviewer approves it as a HumanTask.

### Requirement 9: Application Attributes and Validation

**User Story:** As an application owner, I want a generated form for my template's variable fields, so that I supply only valid, complete attributes.

#### Acceptance Criteria

1. WHEN a user selects a `PUBLISHED` template, THE Platform SHALL generate an Attributes_Form in YAML from the template's fields and options.
2. THE Platform SHALL refuse to instantiate a template with status `DRAFT`.
3. WHEN a filled Attributes_Form is submitted, THE Platform SHALL validate required fields, allowed values, types, and coverage of every placeholder, without using the Decider.
4. IF attribute validation reports any error, THEN THE Platform SHALL block instantiation and report each error with field name.
5. THE Platform SHALL provide filled Attributes_Forms for Variants V1, V2, V3, and V4.

### Requirement 10: Generation, Placeholder Fill, and Manifest

**User Story:** As a reviewer, I want the application model generated by the official CLI and filled deterministically, so that it is reproducible and auditable.

#### Acceptance Criteria

1. WHEN attributes are valid, THE Platform SHALL write an option-choices file keyed by option unique-id with the choice description as value, and run `calm generate -p <template> --option-choices <file> -o <out>` through the CALM_Adapter, with no LLM.
2. WHEN generation completes, THE Platform SHALL run Placeholder_Fill to replace every placeholder using the validated attributes.
3. IF any placeholder remains after Placeholder_Fill, THEN THE Platform SHALL report each leftover placeholder with its JSON path and SHALL NOT produce an App_Model.
4. THE Platform SHALL write a Generation_Manifest with template ID and version, source pattern versions, attributes hash, option choices, CALM_CLI version, template hash, output hash, and the fill record.
5. WHEN identical template, attributes, and CALM_CLI version are provided, THE Platform SHALL produce an App_Model with an identical SHA-256.
6. THE Platform SHALL store the App_Model in the CALM_Catalog and set `"$schema"` to the CALM 1.2 schema URL.

### Requirement 11: CALM Validation

**User Story:** As a reviewer, I want every application model validated against its template, so that invalid CALM never reaches assessment.

#### Acceptance Criteria

1. WHEN an App_Model is produced or uploaded, THE CALM_Adapter SHALL run `calm validate -p <template> -a <app> -f json` and return `VALID` if and only if `hasErrors` is false.
2. WHEN `hasWarnings` is true and `hasErrors` is false, THE CALM_Adapter SHALL return `VALID` and include each warning.
3. IF validation reports errors, THEN THE CALM_Adapter SHALL return each error with `code`, `severity`, `message`, and `path`, and THE Platform SHALL block assessment and return correction guidance (Variant V4).
4. IF the CALM_CLI is unavailable or its output cannot be parsed, THEN THE CALM_Adapter SHALL return `ERROR` and SHALL NOT return `VALID`.
5. THE CALM_Adapter SHALL pass arguments as a list without shell interpolation, use a temp directory, enforce a timeout, and record CLI version, exit code, and duration.
6. THE Platform SHALL report CALM validation results separately from Spectral governance results.

### Requirement 12: Input Safety

**User Story:** As a security reviewer, I want uploads and paths constrained, so that the Platform cannot be abused through its inputs.

#### Acceptance Criteria

1. WHEN a file is uploaded, THE Platform SHALL reject files larger than 1 MB and files that are not valid JSON or YAML.
2. THE Platform SHALL treat uploaded content as data and SHALL NOT execute it.
3. THE Platform SHALL reject any artifact or file path that resolves outside the application data directory.
4. WHEN a valid uploaded CALM model is accepted, THE Platform SHALL store it as an immutable Artifact and run it through Requirement 11 and the same assessment path as a generated model.
5. THE Platform SHALL keep secrets out of artifacts, logs, traces, LLM inputs, and Decider inputs.

### Requirement 13: Facts and Dimensions

**User Story:** As a risk analyst, I want facts extracted with provenance, so that every finding traces to an architecture element.

#### Acceptance Criteria

1. WHEN an assessment starts, THE Risk Assessment unit SHALL extract Facts for the seven Dimensions from App_Model metadata.
2. THE Risk Assessment unit SHALL record on each Fact the element ID, JSON path, raw value, normalized value, taxonomy version, and mapping status.
3. THE Risk Assessment unit SHALL apply deterministic Taxonomy mapping before any Decider call.
4. WHEN a raw attribute matches no Taxonomy entry, THE Risk Assessment unit SHALL retain the Fact as `UNMAPPED`.
5. THE Risk Assessment unit SHALL extract per-agent Facts (permitted tools, autonomy, privilege) from each `ai:agent` node.
6. THE Platform SHALL persist the Fact set, taxonomy version, and App_Model hash as an immutable Artifact.
7. THE test suite SHALL include an attribute outside the Taxonomy that remains `UNMAPPED` and is shown in the Dashboard.

### Requirement 14: Decider Use and Acceptance Policy

**User Story:** As an approver, I want Decider output accepted only under an explicit policy, so that a small model cannot weaken a governance outcome.

#### Acceptance Criteria

1. THE Platform SHALL call the Decider only to classify `UNMAPPED` attributes for which no deterministic check exists.
2. THE Platform SHALL send `POST /v1/systemone` with `{state, questions, model, images}` using question types `noul` (`{noul}`), `choice` (`{choice, probabilities, confidence}`), and `score` (`{score, legend, probabilities, confidence}`), and parse `{model, answers, usage}`.
3. THE Platform SHALL read base URL, model, and timeout from configuration and measure latency client-side.
4. WHEN a `choice` or `score` answer has confidence at or above the task threshold AND a top-2 probability margin at or above the task minimum, THE Acceptance_Policy SHALL return `ACCEPTED`.
5. WHEN a `noul` answer is at or above 0.9 or at or below 0.1 (configurable), THE Acceptance_Policy SHALL return `ACCEPTED` and SHALL NOT read a confidence field.
6. WHEN an answer fails the thresholds, THE Acceptance_Policy SHALL return `ABSTAIN` (recorded as `UNKNOWN`) or `HUMAN_REVIEW`, as configured per task.
7. IF an answer is missing, invalid, or has undeterminable confidence, THEN THE Acceptance_Policy SHALL treat it as not accepted.
8. THE Platform SHALL NOT describe Decider scores as calibrated probabilities.
9. THE Platform SHALL allow accepted labels to feed risk triggers and SHALL NOT allow any Decider output to set a severity or a Governance_Decision directly.

### Requirement 15: Decider Audit, Cache, Fixtures, and Fallback

**User Story:** As an auditor, I want each Decider call recorded and the pipeline independent of the server, so that advisory influence is reviewable.

#### Acceptance Criteria

1. WHEN the Decider is called, THE Platform SHALL persist a record with model, state, question, answer, confidence where present, latency, Input_Hash, acceptance outcome, timestamp, and Trace_ID.
2. WHEN an Input_Hash is cached, THE Platform SHALL return the cached result without a network call and record a cache hit.
3. THE Platform SHALL build `state` from a fixed field list, limited to 4000 characters with a documented truncation order, and SHALL exclude full CALM JSON, secrets, and file paths.
4. IF the Decider is unreachable, returns an HTTP error, or times out, THEN THE Platform SHALL return an unavailable result without an unhandled exception, record `UNKNOWN`, and SHALL NOT apply any risk-reducing default.
5. WHEN the Decider was unavailable for any question, THE Dashboard SHALL state this and list the affected questions.
6. WHERE the provider is `fixture`, THE Platform SHALL answer from fixtures keyed by Input_Hash, and IF a fixture is missing THEN return `fixture_missing`.
7. THE Platform SHALL run all automated tests with `fixture` or rule-based providers and no running Decider.

### Requirement 16: Spectral Execution

**User Story:** As an assessor, I want both rulesets run against the application model through one adapter, so that results are consistent and traceable.

#### Acceptance Criteria

1. WHEN an App_Model is VALID, THE Spectral_Adapter SHALL run `spectral lint <app.json> -r <controls.spectral.yaml> -f json` and the same command with `risks.spectral.yaml`, in parallel.
2. THE Spectral_Adapter SHALL pass arguments as a list, use a temp directory, enforce a timeout, and record Spectral version, exit code, and duration.
3. THE Spectral_Adapter SHALL parse each result into code, path, severity, and message according to the output shape recorded in Spike_Notes.
4. IF Spectral is unavailable, times out, or returns unparsable output, THEN THE Spectral_Adapter SHALL return `ERROR` for that run and SHALL NOT report PASS.
5. THE Platform SHALL keep the raw and parsed results of both runs as Artifacts.

### Requirement 17: Control Gap Assessment

**User Story:** As a governance lead, I want control status and a gap level, so that I can see which mitigations are missing.

#### Acceptance Criteria

1. THE Control Assessment unit SHALL map Spectral results to controls by Rule_Code and assign each control `PASS`, `FAIL`, `ERROR`, or `NOT_APPLICABLE`.
2. WHEN a control's rules produce no finding, THE Control Assessment unit SHALL assign `PASS` and label it design-level evidence only.
3. THE Control Assessment unit SHALL derive Gap_Level (`none`, `minor`, `major`, `critical`) from the severities of failed controls using a documented, versioned rule.
4. IF a control's Spectral run returned `ERROR`, THEN THE Control Assessment unit SHALL assign `ERROR` and SHALL NOT assign `PASS`.
5. THE Control Assessment unit SHALL attach catalog remediation to each `FAIL` control.

### Requirement 18: Risk Profile Assessment

**User Story:** As a risk analyst, I want per-risk severity from likelihood and impact, so that the risk profile reflects the application.

#### Acceptance Criteria

1. WHEN a risk Spectral rule fires, THE Risk Assessment unit SHALL mark that risk as triggered and read likelihood and impact from the Risk_Rules_Catalog.
2. THE Risk Assessment unit SHALL compute severity per triggered risk through the Proposal section 8.4 matrix in a versioned Scoring_Profile labelled "illustrative, not approved policy", and SHALL record severity for every triggered risk regardless of approval tier.
3. THE Risk Assessment unit SHALL set the risk profile level to the worst severity among triggered risks.
4. THE Risk Assessment unit SHALL compute the Agent_Approval_Tier with `risk_tier.py` for the approval path only.
5. IF a mandatory trigger cannot be evaluated because its attribute is `UNMAPPED` or `UNKNOWN`, THEN THE Risk Assessment unit SHALL mark the input `INDETERMINATE`.
6. WHEN identical inputs and Scoring_Profile are provided, THE Risk Assessment unit SHALL produce identical results.

### Requirement 19: Governance Decision

**User Story:** As an approver, I want a deterministic, traceable decision, so that I can defend the outcome.

#### Acceptance Criteria

1. THE Decision & Remediation unit SHALL evaluate Mandatory_Gates first and in this order of override: payment authorization control `FAIL` yields `REJECTED`; invalid CALM yields blocked; a mandatory trigger that cannot be evaluated yields `INDETERMINATE`.
2. WHEN no Mandatory_Gate fires, THE Decision & Remediation unit SHALL look up Gap_Level x risk profile level in the versioned Decision_Matrix and return `APPROVED`, `APPROVED_WITH_CONDITIONS`, `RESTRICTED`, `REJECTED`, or `INDETERMINATE`.
3. WHEN the matrix result would be `APPROVED` on design-only evidence, THE Decision & Remediation unit SHALL return `APPROVED_WITH_CONDITIONS` with the condition "design approved; build-time and runtime evidence required".
4. THE Decision & Remediation unit SHALL record every Mandatory_Gate and matrix cell evaluated or fired.
5. THE Decision & Remediation unit SHALL NOT use any LLM or Decider input in the decision.
6. WHEN identical inputs and Decision_Matrix version are provided, THE Decision & Remediation unit SHALL return an identical decision.

### Requirement 20: Report and Remediation Agent

**User Story:** As a developer of the Application, I want a clear report and a fix prompt, so that I can correct the design and re-run.

#### Acceptance Criteria

1. THE Platform SHALL produce a report with control gaps, risk profile, decision, and remediations, viewable in the Dashboard and as a Static_Export.
2. WHEN an assessment completes, THE Remediation_Agent SHALL collect remediation text from failed controls and triggered risks and produce a Fix Prompt or Summary through the ModelGateway.
3. WHERE no LLM is available or the mode is no-LLM, THE Remediation_Agent SHALL produce a deterministic list of the same remediation texts and the assessment SHALL complete.
4. WHEN a human takes the output (Fluxnova user task or Dashboard) and corrects attributes or CALM, THE Platform SHALL run a new assessment with a new Trace_ID.
5. THE Remediation_Agent SHALL NOT edit CALM and SHALL NOT change a Governance_Decision.

### Requirement 21: Units, Coordinator, and Runtime

**User Story:** As a developer, I want framework-neutral units, so that Strands is replaceable and the assessment path needs no LLM.

#### Acceptance Criteria

1. THE Platform SHALL implement five Units (Rule Authoring, CALM Builder, Control Assessment, Risk Assessment, Decision & Remediation) behind AgentTask and AgentResult, passing artifact IDs only.
2. THE Platform SHALL keep Strands types out of domain code, with only the AgentRuntime adapter running LLM tasks.
3. THE Coordinator SHALL invoke Units only through the AgentTask contract.
4. WHERE the mode is no-LLM, THE Platform SHALL complete the assessment path and produce a deterministic remediation list.
5. WHEN a Unit returns an error, THE Coordinator SHALL record it in the Artifact set and SHALL NOT report a decision derived from missing results.

### Requirement 22: Workflow Orchestration

**User Story:** As an operator, I want the pipeline run as a BPMN workflow, so that stages and human tasks are visible and controllable.

#### Acceptance Criteria

1. THE Workflow_Engine SHALL run a BPMN process with an external task per stage, a parallel gateway for the two Spectral runs, and user tasks for invalid-CALM correction, remediation review, and optional rule approval.
2. THE External_Task_Worker SHALL call exactly one pipeline step per task and pass artifact IDs only.
3. THE Platform SHALL use the REST paths confirmed in the Fluxnova spike.
4. IF the Fluxnova spike fails, THEN THE Platform SHALL use the Direct_Adapter, labelled development-only in the Dashboard and Spike_Notes.
5. THE Dashboard SHALL display the Executor of each assessment.

### Requirement 23: Storage, Artifacts, and Versions

**User Story:** As an auditor, I want immutable, versioned artifacts, so that any decision can be reproduced and defended.

#### Acceptance Criteria

1. THE Platform SHALL store catalogs (patterns, CALM catalog, rule catalogs, decision matrix) and run metadata in py-pglite (TCP mode, port 5433) and artifact files on disk.
2. IF py-pglite is not persistent, THEN THE Platform SHALL seed catalogs from YAML at startup and export runs to files, and IF py-pglite is unusable THEN use SQLite as last resort.
3. THE Platform SHALL treat each Artifact as immutable, addressed by ID and SHA-256.
4. THE Platform SHALL record in each assessment the versions of patterns, template, CALM_CLI, Spectral, rulesets, catalogs, Scoring_Profile, Decision_Matrix, Decider model and Acceptance_Policy, LLM model and prompt versions, and workflow.
5. THE Platform SHALL use ports 8080 (Fluxnova), 8000 (Decider), 8001 (Platform), and 5433 (PGlite).

### Requirement 24: Observability and Replay

**User Story:** As an auditor, I want one trace per assessment and exact replay, so that results can be re-verified.

#### Acceptance Criteria

1. THE Platform SHALL emit one OpenTelemetry trace per assessment to console or file, with a span per stage and the Trace_ID on all Artifacts.
2. WHEN Replay_Mode is run for an assessment, THE Platform SHALL use recorded LLM and Decider outputs and make no model calls.
3. WHEN Replay_Mode is run, THE Platform SHALL produce results identical to the original, including the decision.
4. IF a recorded output is missing during replay, THEN THE Platform SHALL fail the replay and name the missing record.
5. THE Platform SHALL keep secrets out of traces and logs.

### Requirement 25: Governance Dashboard

**User Story:** As a reviewer, I want one dashboard over persisted artifacts, so that I can inspect and trace every result.

#### Acceptance Criteria

1. THE Dashboard SHALL be served by FastAPI with Jinja2 and vanilla JavaScript on port 8001, vendor Mermaid locally (no CDN), and read only persisted Artifacts.
2. THE Dashboard SHALL show an assessments list, a pipeline flow with the parallel Spectral lanes and the Executor, and an architecture diagram from CALM with nodes coloured by worst finding.
3. THE Dashboard SHALL provide a traceability explorer from decision to gate or matrix cell, to control or risk, to Spectral Rule_Code and JSON path, to CALM element, to pattern and template version, to AIGF or CCC source ID, and the reverse.
4. THE Dashboard SHALL show a 5x5 risk matrix, a control gap table, a remediation and Fix Prompt panel, a Decider panel (including unavailable questions), a catalog browser, a versions view, and a variant comparison.
5. THE Dashboard SHALL offer JSON downloads of Artifacts and a Static_Export of the report.
6. THE Dashboard SHALL label Scoring_Profile outputs "illustrative, not approved policy" and Spectral passes "design-level evidence only".

### Requirement 26: Golden Variants and Acceptance Tests

**User Story:** As a developer, I want golden cases and property tests, so that behaviour is verified end to end with no external services.

#### Acceptance Criteria

1. THE Platform SHALL provide fixtures and recorded outputs for four Variants: V1 compliant yields `APPROVED_WITH_CONDITIONS`; V2 approval bypass (Payment Agent to Payment API direct, unrestricted write) yields `REJECTED` by a Mandatory_Gate; V3 partial (audit service missing and autonomous Payment Agent) yields a high risk profile with minor gaps and `RESTRICTED`; V4 invalid instance is blocked.
2. WHEN no LLM is available, THE Platform SHALL complete V1-V3 with a deterministic remediation list.
3. WHEN replay is run for each Variant, THE Platform SHALL produce results identical to the original.
4. WHEN the most favourable Decider answers are substituted for every classification, THE Platform SHALL return the same severities and decision.
5. THE test suite SHALL include unit tests for Decider unavailable and low-confidence answers.
6. THE test suite SHALL verify determinism of the Composer, generate plus fill, scoring, and decision.
7. THE test suite SHALL verify that a leftover placeholder is rejected.
8. THE test suite SHALL verify `INDETERMINATE` when a mandatory trigger is unevaluable.
9. THE test suite SHALL run without Bedrock, the Decider, or Fluxnova.
