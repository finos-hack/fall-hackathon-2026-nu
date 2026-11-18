# Backlog (deferred scope)

Items below are not part of this MVP. Each line gives the proposal ID and why it was deferred.

| Item | Proposal ID | Why deferred |
|---|---|---|
| Gate CP-G | H01-H10 | Not implemented. Fluxnova orchestration itself runs (scripts/fluxnova_e2e.py); Direct_Adapter covers the MVP flow |
| Full change impact analysis (task 25.6) | F06 | Needs stored baselines across several assessments. Not needed for the V1-V4 demo |
| Compare assessments (task 25.7) | F07 | Depends on change impact data. Replay already shows one assessment end to end |
| Full RBAC, SSO and enterprise IAM, multi-reviewer approval | E06 | Enterprise identity needs an external identity provider. The dashboard Approve button has no login and records a fixed actor (dashboard-reviewer, role governance_admin) |
| Extraction of all 24 AIGF risks | B02 | Bedrock extraction works live, but recorded extractions cover only the seeded items |
| Advanced review-queue filters, notifications and escalation | E05 | The basic review queue is enough for the demo. Notifications need a delivery channel |
| RA01 and RA02 | none | RA03-LITE (8 patterns) and RA05-CYBER-REMEDIATION (6 patterns) are enough to prove the flow. More patterns and RAs can be built in the dashboard |
| Runtime cloud evidence collectors and operating-effectiveness automation | none | The MVP gives design-level evidence only. Runtime data needs cloud access and a collector design |
| Automatic rule learning and promotion | none | Rules reach APPROVED only through a named human. Automatic promotion would bypass that control |
| Automatic scoring changes | none | Scoring outputs are illustrative. Changes stay manual and reviewed |
| Multi-tenant deployment | none | The MVP runs one application on one local store |
| Role-based checks and real reviewer identity on Approve | E06 | The MVP Approve button works for anyone who opens the dashboard and records `dashboard-reviewer`. Needs login and role checks (for example `governance_admin`) |
| Neutral gate id and RI-024 remediation text | none | Gate id `G2-PAYMENT-AUTH` (`config/gates.yaml`, `expected.yaml`) and the AIGF-RI-024 remediation text are payment-specific, but the gate now also fires for production-change agents |
| RA agent balancing `oneOf` choices | none | The Strands RA agent composes templates well but is weak at balancing `oneOf` option choices. A human fixes them in the editor |
| Decider risk scores below the confidence threshold | none | Nova 2 Lite plus the Decider gave about 0.45 confidence for every risk (threshold 0.5, flagged `low_confidence`). A human must confirm the scores. Needs a stronger model or better scale descriptions |
| Previous version in force for patterns and RAs | none | A changed APPROVED rule keeps its previous version in force until approval. A changed pattern or RA goes back to DRAFT and disappears from Generate CALM until it is approved again |
| Template choice and requirement questions in the Fluxnova run | none | `scripts/fluxnova_e2e.py` always uses RA03-LITE. Choosing a template and answering questions exist only in the dashboard (Generate CALM) |
| PDF and Word upload in Generate Rules | none | Only `.md`, `.markdown`, `.yaml` and `.yml` are read (UTF-8, 1 MB per file, 20 items per run). Text extraction from PDF and Word is not built |
| Taxonomy fields for uploaded rules | none | `config/taxonomy.yaml` lacks fields that some uploaded rules need (for example `model_version`). Such rules are kept as inexpressible DRAFTs until the field is added |