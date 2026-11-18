# Backlog: Governance-as-Code (post-MVP)

Items not needed to show all platform features end to end for the single Invoice-to-Payment Lite app at design time. "Proposal" means `agent_governance_intelligence_platform_detailed_proposal.md`. "User decision" means the MVP scope decision recorded in this spec.

## Pattern Library

- P01, P04, P05, P06, P09, P10, P15: define the remaining patterns. Source: Proposal pattern library; user decision (MVP defines only the 8 patterns the Lite template uses).

## Reference Architectures and Applications

- Full RA03 Invoice-to-Payment with 8 agents and multi-agent orchestration. Source: Proposal; user decision (Lite replaces it).
- RA01 Vendor Onboarding. Source: Proposal; user decision.
- RA02 Employee Onboarding. Source: Proposal; user decision.
- LLM turning free-text requirements into the Attributes_Form. Source: user decision.

## Decider and Evaluation

- Decider for other classification tasks (evidence type, template recommendation). Source: user decision.
- Labelled Decider datasets, an evaluation script, and calibration. Source: user decision.

## Evidence

- Build-time and runtime evidence tools (IaC, config, and test evaluators). Source: Proposal; user decision.
- Evidence layers L2 (build-time) and L3 (runtime operating evidence). Source: Proposal; user decision.
- Runtime business scenarios (duplicate invoice, purchase-order mismatch) and a test harness. Source: user decision.

## Rules and Knowledge

- Full CCC coverage (MVP includes 1 or 2 controls). Source: Proposal; user decision.
- Other AIGF risks and mitigations beyond Invoice-Lite. Source: Proposal; user decision.
- Knowledge proposals API. Source: Proposal; user decision.
- Automated re-extraction when sources change. Source: Proposal; user decision.

## Reporting and Remediation

- LLM narrative reports. Source: user decision.
- Automated remediation patches (CALM JSON patch). Auto-applying remediation stays human-only in the MVP. Source: user decision.

## Governance Process

- Risk acceptance workflow. Source: Proposal; user decision.

## LLM Providers

- Further LLM providers beyond configuration. Source: user decision.

## CALM Tooling

- CALM Hub publishing (`calm hub push`). Source: user decision.
- CALM diff, docify, and timeline. Source: user decision.
- CALM 1.3 support. Source: user decision.

## Observability

- OTel backend and metrics (MVP exports spans to console or file). Source: user decision.

## Platform and Deployment

- Authentication, roles, and multi-tenancy. Source: user decision.
- Cloud deployment. Source: user decision.
- React UI (MVP uses server-rendered Jinja2 with vanilla JS). Source: user decision.
- Migration from PGlite to Postgres. Source: user decision.
