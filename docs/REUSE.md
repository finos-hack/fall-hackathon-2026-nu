# Reuse map
Draft repo: cyber-grc-finos-framework/design-time-agent-security
Draft commit for every row: `73250812cff557cda61dc30b7ede328b8b670292`

## Files still in the repo

| Destination | Source path (draft repo) | New role |
|---|---|---|
| `shared/src/agip_shared/contracts.py` | `src/models/rule.py` | Shared contracts (CanonicalRule, Finding, AssessmentArtifact); basis for catalog item models |
| `governance-execution-framework/src/governance_execution/risk_tier.py` | `src/validator/risk_tier.py` | Agent_Approval_Tier only. Thresholds (17/13/9/5) and the three overrides match the hackathon scoring-rubric.json; the inputs in units/risk_assessment.py were aligned to it |
| `calm-app-generation-framework/docs/VOCABULARY.md` | `architecture/calm/VOCABULARY.md` | Metadata vocabulary for triggers and taxonomy |
| `calm-app-generation-framework/fixtures/variants/customer-support-compliant.json` | `architecture/examples/customer-support-compliant.json` | Seed for fixture variants V1-V4 |
| `calm-app-generation-framework/fixtures/variants/customer-support-gap.json` | `architecture/examples/customer-support-gap.json` | Seed for fixture variants V1-V4 |
| `rule-authoring-framework/docs/AUTHORING-GUIDE.md` | `rule-authoring/AUTHORING-GUIDE.md` | Guide |
| `governance-execution-framework/tests/test_risk_tier.py` | `tests/test_risk_tier.py` | Dependent test; passes |

## Removed in task 16 (rows kept for provenance)

| Former destination | Source path (draft repo) | Why removed |
|---|---|---|
| `calm_generation/calm_finos.py` | `src/validator/calm_finos.py` | Only the removed pipeline imported it |
| `governance_execution/applicability.py` | `src/validator/applicability.py` | Only the removed pipeline used it |
| `governance_execution/scoring.py` | `src/validator/scoring.py` | Severity comes from `scoring_profile.yaml`; only the removed pipeline used it |
| `governance_execution/findings.py` | `src/validator/findings.py` | Spectral results are mapped in `units/control_assessment.py` |
| `governance_execution/pipeline.py` | `src/validator/pipeline.py` | The Coordinator replaces it |
| `rule-authoring-framework/catalogs/seed/registry.yaml` | `governance/controls/registry.yaml` | Merged into `controls.catalog.yaml` |
| `rule-authoring-framework/catalogs/seed/rules/*.yaml` (12 files) | `governance/rules/*.yaml` | Merged into the catalogs |
| `calm_generation/validate_v12.py` | `scripts/validate_calm_v12.py` | `calm validate` replaces it |
| `rule_authoring/ingest_finos.py` | `scripts/ingest_finos_mitigations.py` | Replaced by `sources_aigf.py` and `ingest.py` |
| `rule-authoring-framework/docs/examples/mi-*.md` (3 files) | `rule-authoring/mi-*.md` | Replaced by recorded extractions |
| `rule-authoring-framework/templates/rule.yaml.j2` | `rule-authoring/rule.yaml.j2` | `compile.py` writes rulesets directly |
| `rule_authoring/transform.py` | `rule-authoring/transform.py` | Same |
| `rule-authoring-framework/tests/test_rule_schema.py` | `tests/test_rule_schema.py` | Tested removed code |
| `rule-authoring-framework/tests/test_seed_catalog.py` | `tests/test_task3_aigf_ccc_rules.py` | Read the removed seed catalog |

Files added after the copy (for example ersioned_write.py, upload.py, merge.py, pattern_builder.py, a_agent.py, scripts/build_cyber.py) have no draft source; they are listed in docs/STRUCTURE.md.

Not copied: `src/agent`, `demo*.py`, `agent_runtime.py`, AgentCore files, `evaluator.py` (Spectral replaces it), calm-guard bridge.
This file replaces the former `docs/copy-manifest.txt`.
