# Governance execution framework

Purpose: runtime for governance assessment: applicability, findings, scoring, approval tier, orchestration, and the dashboard.

Boundaries: consumes `rule_authoring` (catalogs, rulesets, upload and extraction for Generate Rules) and `calm_generation` (patterns, RA builder, templates for Build Pattern, Build Reference Architecture and Generate CALM) plus `agip_shared`. Nothing depends on it. The rule evaluator is injected; calm-guard is not a dependency. The approval tier never sets severity.

Layout: `src/governance_execution/` (`core` facts, gap, gates, decision, catalogs; `units`; `adapters` calm, spectral, decider; `exec` Coordinator, Direct_Adapter, Fluxnova; `store`; `obs`; `dashboard`; `risk_tier.py`; `cli.py`), `forms/`, `prompts/`, `config/` (`taxonomy.yaml`, `scoring_profile.yaml`, `gates.yaml`, `decision_matrix.yaml`, `gap_rule.yaml`, `decider_policy.yaml`, `roles.yaml`), `fixtures/recordings/` (`decider/`, `cli/`, `llm/`), `tests/`.

Entry points:
- `uv run python -m governance_execution assess|replay|show|resume ...`
- `uv run python -m governance_execution.dashboard.app` (http://127.0.0.1:8001)

Dashboard (MVP, no login): menu Overview; Catalog (Controls Catalog, Risk Profile Catalog, CALM Patterns Catalog); Source Registry; Generate Rules (`/rules/new`, router `routers/rules.py`); Architecture (Build Pattern `/patterns/new`, Build Reference Architecture `/architectures/new`, both in `routers/architecture.py`; Generate CALM `/applications/new` in `routers/mvp.py`); Assessments. Items waiting on a human show PENDING HUMAN REVIEW with an Approve button (`POST /catalogs/{kind}/{id}/approve`, `POST /api/assessments/{trace}/approve`); the MVP approves as `dashboard-reviewer`, role `governance_admin`, without role checks.

Changes in this area:
- Decider adapter (`adapters/decider.py`, `default_post`): translates the platform request (a questions list) to the Strands Decider schema (`questions: {name: {type, instructions, criteria}}`) and back. Earlier live calls were rejected by the server schema. Choice questions may carry `descriptions`.
- `config/taxonomy.yaml` has the attributes `action_capability`, `action_approval_path`, `remediation_scope`, `host_tagging` and `environment`.
- `units/risk_assessment.py` (`approval_tier_inputs`) follows the hackathon `scoring-rubric.json`: approval path `via-human-approval` caps autonomy at 2, `direct` raises it to at least 3, and `action_capability` `production-change` counts as 4. `risk_tier.py` thresholds (17/13/9/5) and the three overrides are unchanged. `core/catalogs.applicability` treats a production-change agent as `agent_can_perform_high_impact_action`.
- Catalog rules AIGF-MI-024 (CFG-HITL-PRODUCTION, mandatory, critical; gate G2 rejects when it fails), AIGF-MI-018 (CFG-REMEDIATION-SCOPE) and AIGF-RI-024 (`risk-production-change-without-approval`), built by `scripts/build_cyber.py`.
- Governance catalog store (`store/repository.py`): different content at the same (id, version) creates a new DRAFT version; lifecycle fields are not content.
- `forms/*.attributes.yaml` are regenerated with `scripts/build_forms.py` (RA03-LITE ra-version 2); CLI recordings were refreshed.
