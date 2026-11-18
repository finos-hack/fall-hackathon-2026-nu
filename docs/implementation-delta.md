# Implementation delta report (task 19.1)

## Baseline

- Branch `main`, commit `1344197` ("initial commit").
- The working tree holds uncommitted changes, made outside this task, that perform part of task 16. These files are staged as deleted: `pipeline.py`, `applicability.py`, `findings.py`, `scoring.py`, `gateway/__init__.py` (governance), `calm_finos.py`, `validate_v12.py`, `rule-authoring-framework/catalogs/seed/`, `docs/examples/`, `ingest_finos.py`, `transform.py`, `templates/rule.yaml.j2`, `tests/test_pipeline.py`, `tests/test_rule_schema.py`, `tests/test_seed_catalog.py`. These files are modified: `README.md`, `test_risk_tier.py`, `paths.py`, `agip_shared/__init__.py`, `contracts.py`. These docs are untracked: `docs/TESTING.md`, `docs/execution_flow.md`, `docs/functional_manual_testing.md`.
- `uv run pytest -q`: collection stops with 1 error. `calm-app-generation-framework/tests/test_fixtures_and_readers.py` imports the deleted `calm_generation.calm_finos`.
- `uv run pytest -q --ignore=calm-app-generation-framework/tests/test_fixtures_and_readers.py`: **225 passed, 2 failed**.
  - `tests/test_consistency_guards.py::test_pipeline_and_scoring_severity_independent_of_risk_tier`. It reads the deleted `pipeline.py`.
  - `rule-authoring-framework/tests/test_catalogs.py::test_every_seed_control_merged_once`. It reads the deleted `catalogs/seed/registry.yaml`.
- All 75 governance-execution tests pass, golden V1-V4 included.

## Status of every `[x]` task

| Task | Status | Evidence (file / test) | Gap |
|---|---|---|---|
| 0.1 | COMPLETE | `pyproject.toml`; framework `config/ catalogs/ rulesets/ fixtures/`; README install command | Strands and `botocore[crt]` are not declared as dependencies |
| 0.2 | PARTIAL | Four framework dirs exist | Uncommitted deletions break `test_fixtures_and_readers.py` |
| 0.3 | PARTIAL | `docs/REUSE.md`, `docs/deliberate-changes.md` | REUSE.md still lists deleted files |
| 0.4 | INCORRECTLY_MARKED | `tests/test_consistency_guards.py` | The severity guard test fails on the deleted `pipeline.py` |
| CP0 | INCORRECTLY_MARKED | Baseline above | 1 collection error and 2 failures |
| 1.1 | COMPLETE | `docs/spike/1.1-calm.md`, `scripts/spike/calm_spike.sh` | - |
| 1.2 | PARTIAL | `docs/spike/spectral.md` | `spike-notes.md` still says "to be re-checked" |
| 1.3 | COMPLETE | `docs/spike/decider.md` (service down, fallback recorded) | Real response shape never captured |
| 1.4 | COMPLETE | `docs/spike/pglite.md` | Not re-run on the current Node version |
| 1.5 | PARTIAL | `docs/spike/bedrock.md` | Credentials expired, so model access is unverified. Contingency recorded |
| 1.6 | PARTIAL | `docs/spike/fluxnova.md` FAIL (no Docker) | No REST paths confirmed. Moved to 27.1 |
| 1.7 | PARTIAL | `docs/spike-notes.md` | Status table stale. Deliberate-change list only linked |
| 2.1 | COMPLETE | `shared/.../contracts.py`, `shared/tests/test_contracts.py` | Uses deprecated `datetime.utcnow` |
| 2.2 | COMPLETE | `hashing.py`, `paths.py`, `test_hashing_paths.py` (symlink escape) | - |
| 2.4 | COMPLETE | `store/db.py`, `schema.sql`, `artifacts.py`, `repository.py`, `test_store.py` | Live pglite backend untested |
| 2.5 | COMPLETE | `adapters/calm.py`, `test_calm_adapter.py` | No explicit timeout or missing-tool test (20.3) |
| 2.6 | COMPLETE | `adapters/spectral.py`, `test_spectral_adapter.py` | `SpectralRun` lacks exit code and duration |
| 2.7 | COMPLETE | `obs/otel.py`, `test_otel.py` | File export only through an injected exporter |
| 3.1 | COMPLETE | `sources_aigf.py`, used by `seed_recordings.py` | No dedicated adapter tests (3.3) |
| 3.2 | INCORRECTLY_MARKED | `sources_ccc.py` has no caller or test | `CCC.KMS`/`CCC.VPC` are hand-written. Moved to 21.1 and 21.5 |
| 4.1 | COMPLETE | `shared/.../gateway/`, `test_gateway.py` | Recorder optional. Strands not in `pyproject.toml` |
| 4.2 | COMPLETE | `units/rule_authoring.py`, `extraction.py`, `test_extraction.py` | Only 2 recorded extractions |
| 4.4 | COMPLETE | `approval.py`, `test_approval.py` | - |
| CP4 | INCORRECTLY_MARKED | Baseline above | Same failures as CP0 |
| 5.1 | PARTIAL | catalogs and `config/*.yaml` | `test_every_seed_control_merged_once` fails. Risks hand-merged (`seed-import`) |
| 5.2 | COMPLETE | `consistency.py`, `test_consistency.py` | - |
| 5.3 | PARTIAL | `compile.py` | Recorded extractions not approved by a seed step. Ruleset header lacks SHA. `functions/` empty |
| CP5 | INCORRECTLY_MARKED | Baseline above | Tests fail |
| 6.1 | COMPLETE | `pattern-draft.v1.md`, `patterns/SPECS.md` | - |
| 6.2 | PARTIAL | 8 pattern JSONs | Only a stub validator, no real `calm validate`. P03 has no related risks |
| 6.3 | PARTIAL | `pattern_library.publish` | Only tests call it. No DB records. `approved_at` empty |
| 7.1 | COMPLETE | `composer.py`, determinism test | - |
| 7.4 | PARTIAL | `RA03-LITE.json`, conflict test | Not published to CALM_Catalog. No real `calm validate` |
| 8.1 | COMPLETE | `attributes.py` refuses non-PUBLISHED | - |
| 8.3 | COMPLETE | `placeholders.py` | `[[ REF_X ]]` not explicitly tested |
| 8.5 | COMPLETE | `units/calm_builder.py` | - |
| 8.7 | COMPLETE | `forms/ra03-lite.attributes.yaml`, `v1`-`v4` | - |
| CP8 | INCORRECTLY_MARKED | Baseline above | Tests fail |
| 9.1 | COMPLETE | `core/facts.py`, `test_facts_decider.py` | - |
| 9.3 | COMPLETE | `core/acceptance.py`, `decider_policy.yaml` | - |
| 9.5 | COMPLETE | `adapters/decider.py` | Cache also stores ERROR results |
| 10.1 | COMPLETE | `core/spectral_runs.py`, `direct_adapter.py` | - |
| 10.2 | COMPLETE | `control_assessment.py`, `core/gap.py` | - |
| 10.4 | PARTIAL | `units/risk_assessment.py` (`matrix_lookup`) | `scoring.py` deleted. Guard test fails |
| 10.6 | COMPLETE | `core/gates.py`, `core/decision.py` | - |
| 11.1 | COMPLETE | `units/decision_remediation.py` | - |
| 11.3 | COMPLETE | `units/registry.py` | - |
| 11.4 | PARTIAL | `exec/coordinator.py` | Signature differs from spec. No unit-error test (11.5) |
| CP11 | PARTIAL | 75/75 governance tests | Repo-wide failures |
| 12.1 | COMPLETE | `exec/direct_adapter.py` | - |
| CP12 | PARTIAL | As CP11 | Repo-wide failures |
| 13.1 | COMPLETE | `dashboard/app.py`, vendored mermaid | No committed TestClient tests (13.7) |
| 13.2 | COMPLETE | `routers/pages.py` | Not covered by tests |
| 13.3 | COMPLETE | `core/trace.py` | No unit test (13.4) |
| 13.5 | COMPLETE | `routers/api.py` | Body read fully when no Content-Length |
| 13.6 | COMPLETE | `/export` self-contained | - |
| 14.1 | COMPLETE | `fixtures/variants/expected.yaml`, recordings | One Decider recording shared by all variants |
| 14.2 | COMPLETE | `obs/replay.py`, `test_replay_names_missing_record` | - |
| 14.3 | COMPLETE | `tests/golden/test_golden.py` | Real-tool path not run in this audit |
| 14.4 | COMPLETE | no-LLM, replay and favourable-Decider tests | - |
| 15.1 | COMPLETE | `README.md` | - |
| 15.2 | COMPLETE | `scripts/demo.sh` | Not run in this audit |

## Reopened tasks and where they are fixed

| Task | Fixed in |
|---|---|
| 0.2, 0.4, CP0, CP4, CP5, CP8, CP11, CP12, 5.1, 10.4 | 20.2 (restore a green suite after the uncommitted deletions) |
| 0.3, 1.2, 1.7 | 28.2 |
| 1.5 | 21.2 (live path stays optional) |
| 1.6 | 27.1 |
| 3.2 | 21.1, 21.5 |
| 5.3 | 21.5 |
| 6.2, 6.3 | 22.1, 22.2 |
| 7.4 | 22.4 |
| 11.4 | 20.3, 23.7 |

## Cleanup (28.1)

Checked 2026-11-17. Nothing was deleted by this check.

Task 16 deletions:

| Item | State |
|---|---|
| `governance_execution/pipeline.py`, `applicability.py`, `findings.py`, `scoring.py` | Gone |
| `calm_generation/calm_finos.py`, `validate_v12.py` | Gone |
| `rule_authoring/ingest_finos.py`, `transform.py` | Gone |
| `rule-authoring-framework/catalogs/seed/` | Gone |
| `governance_execution/gateway/` (empty package) | Gone. `shared/src/agip_shared/gateway/` is the live ModelGateway and stays |
| `_out/cat/seed/` | Present, but it is an untracked scratch copy made by the TESTING.md section 3.3 steps, not source. Remove with `rm -rf _out/cat _out/rs` |

Dead-code scan: `vulture` is not installed (`uv run python -m vulture` reports no module), so a grep scan was used instead.

- Every non-`__init__` module under `*/src` was searched by name across `.py`, `.toml`, `.sh`, `.md`, `.json` and `.yaml` files outside `.venv`, `_out` and `.git`. Every module is referenced by at least one other file. No orphan modules found.
- No import of any deleted module remains in code or tests (grep for the eight module names found none).
- Limit: this finds unreferenced modules only. It does not find unused functions inside a module.

## Deliberate changes after the baseline (cyber remediation and dashboard MVP)

These items differ from the original task text on purpose. Each row names the evidence file and what is still open.
Rationale is in `docs/deliberate-changes.md`.

| Area | Change | Evidence | Gap |
|---|---|---|---|
| Rubric mapping | Approval-tier inputs follow the hackathon `scoring-rubric.json`: action capability 1 to 4 from `action_capability` and `privilege`; thresholds and overrides unchanged | `units/risk_assessment.py`, `risk_tier.py`, `config/taxonomy.yaml` | The rubric file lives outside the platform repo (`files_finos hackathon5/`) |
| Approval path and autonomy | `action_approval_path` `via-human-approval` caps autonomy at 2; `direct` raises it to at least 3 | `units/risk_assessment.py _agent_autonomy` | Payment agents use `payment_approval_path`, which has no such effect |
| Compile version | Changed rules raise the catalog `version:` (in place); that is the ruleset header version. Unchanged rules leave the bytes alone | `rule_authoring/compile.py compile_all`, `versioning.write_catalog` | None |
| Hash rule and `previous_approved` | `rule_authoring.merge`: new is DRAFT, same is unchanged, changed is version + 1; a changed APPROVED item keeps the approved entry in force until approval | `rule_authoring/merge.py`, `shared/.../versioned_write.py` | Patterns and RAs have no previous version in force (they return to DRAFT); see `backlog.md` |
| Extraction determinism | Rule_Code fixed by code for AIGF and uploads; rules checked against taxonomy fields; temperature 0.1 with Strands steering; Decider risk scores | `rule_authoring/extraction.py`, `scoring.py`, `shared/.../gateway/runtime_strands.py` | Decider confidence about 0.45 with Nova 2 Lite, so every score is low-confidence and needs human confirmation |
| MVP direct approve | Dashboard Approve records `dashboard-reviewer` / `governance_admin` with no login or role check | `dashboard/routers/mvp.py` (`approve_catalog_item`, `approve_assessment`) | Role checks and real reviewer identity are in `backlog.md` (E06) |
| Decider adapter wire format | Platform request (questions list) is translated to the server schema and back | `adapters/decider.py default_post`, `_server_question` | None |
| Field-reuse rule for patterns | A field already in the library must keep its schema, or use another name | `calm_generation/pattern_builder.py field_conflicts` | None |
| Consistency rules and questions files | `templates/<ra>.consistency.yaml` and `<ra>.questions.yaml` per reference architecture | `calm_generation/attributes.py`, `questions.py`, `ra_builder.py` | The command-line `instantiate` does not apply the consistency rules; `scripts/fluxnova_e2e.py` always uses RA03-LITE |
| Library and RAs | P15, P16 added (P17 created in the UI); P02 v2; RA03-LITE ra-version 2; RA05-CYBER-REMEDIATION added; catalogs and rulesets at version 2 | `calm-app-generation-framework/patterns/`, `templates/`, `registry/lifecycle.yaml`, `scripts/build_cyber.py` | Gate id `G2-PAYMENT-AUTH` and the AIGF-RI-024 remediation text still say payment |