# Deliberate changes (feeds spike-notes.md)

Status after restructure: `uv run pytest` runs all frameworks, 79 passed.

## Former failures: RESOLVED
| Item | Resolution |
|---|---|
| test_task3 `test_rule_files_exist`, `test_all_rules_parse_and_validate`, `test_aigf_rules_count`, `test_ccc_rules_count` | Now `rule-authoring-framework/tests/test_seed_catalog.py`, reading `rule_authoring.paths.SEED_RULES_DIR` (`catalogs/seed/rules`). `registry.yaml` sits outside the rules dir. |

## Formerly not importable: RESOLVED
| Item | Resolution |
|---|---|
| `legacy/pipeline.py` | Now `governance_execution/pipeline.py`. Imports of evaluator, calm-guard and config removed. Callers inject an `Evaluator` callable. Evaluator stays dropped (Spectral replaces it). Severity and scoring logic unchanged. |

## Hard-coded old paths: RESOLVED
| File | Resolution |
|---|---|
| `applicability.py` | Registry path from `rule_authoring.paths.SEED_REGISTRY` |
| `validate_calm_v12.py` | Now `calm_generation.validate_v12`; meta dir via `--meta-dir`/`CALM_META_DIR`; default models are the fixture variants; `demo_2` import dropped (its three inline models are no longer validated) |
| `transform.py` | Output/registry defaults from `rule_authoring.paths`; template at `rule-authoring-framework/templates/rule.yaml.j2` |
| `ingest_finos.py` | Registry and rules paths from `rule_authoring.paths` |

## Tests not copied (unchanged)
| Test | Reason |
|---|---|
| test_validator | Depends on code not in scope |
| test_adapters_and_pipeline | Depends on code not in scope |
| test_agent | Depends on `src/agent`, not copied |
| test_runtime | Depends on `agent_runtime.py`, not copied |

## Open
| Item | Note |
|---|---|
| Pydantic v1-style validators in `agip_shared.contracts` | Deprecation warnings only; migrate when contracts are reworked |

## Catalog merge (task 5.1)
| Item | Decision |
|---|---|
| Severity conflicts between `registry.yaml` and `rules/*.yaml` (EXTERNAL-CONNECTIVITY-001, EXTERNAL-CONNECTIVITY-GOVERNANCE-001, MCP-SERVER-SECURITY-001, TOOL-CHAIN-VALIDATION-001; none in OBSERVABILITY/ACCEPTANCE rule files) | Registry severity kept as `registry_severity`; enforced severity is set per configuration in `controls.catalog.yaml` |
| `EXTERNAL-CONNECTIVITY-CONTROL-001` (rule file only, duplicate of AIGF mi-17) | Merged into `AIGF-MI-017` |
| Control IDs | Draft IDs (for example AGENT-ACTION-001) become native IDs (AIGF-MI-018, CCC.KMS); draft ID kept as `registry_id` |
| New control `AIGF-MI-024` (HITL approval gate) | Added for gate G2; the draft repo had none |
| Draft evidence-key/extractor assessment model | Replaced by Spectral rules over CALM metadata (`spectral_rules`) |

## Separate statuses; invalid CALM gets no decision (task 23.7, agreed with user 2026-11-17)
| Item | Decision |
|---|---|
| Three status values | Assessment status (QUEUED, RUNNING, WAITING_FOR_HUMAN, COMPLETED, FAILED, BLOCKED), validation status (VALID, INVALID, INCOMPLETE, ERROR) and decision (APPROVED, APPROVED_WITH_CONDITIONS, RESTRICTED, REJECTED, INDETERMINATE) are stored separately on the assessment record |
| V4 (invalid CALM) | Was decision `BLOCKED` from gate G1. Now assessment status `BLOCKED`, validation `INVALID`, decision `null`. `BLOCKED` is removed from the decision outcomes and gate G1 is removed from `gates.yaml` (a status is not a verdict on the application). Reason: a blocked run never evaluated governance, so reporting a governance decision for it was misleading |
| Unit error or validator error | Assessment `FAILED`, no decision (was `ERROR`) |
| Unevaluable mandatory trigger | Assessment `COMPLETED`, decision `INDETERMINATE` (unchanged, gate G3) |
| Pending human tasks | Run continues and lists them; `WAITING_FOR_HUMAN` only if `decider_policy.block_on_pending_human` is true (default off, so V1-V4 stay COMPLETED) |

## CCC.KMS / CCC.VPC re-sourced (task 21.5)
| Item | Decision |
|---|---|
| `CCC.KMS`, `CCC.VPC` in `controls.catalog.yaml` | Hand-written CCC IDs replaced as `source` by ingested `CCC.Core.CN02` (Encrypt Data for Storage) and `CCC.Core.CN05` (Prevent Access from Untrusted Entities), path `catalogs/core/core/controls.yaml`. `control_id`, Rule_Codes and patterns are unchanged; a history entry records the re-source. |
| Dangling `CCC.IAM` / `CCC.VPC` references | Pointed at `CCC.Core.CN03` / `CCC.Core.CN05` so the new reference integrity check passes |

## Decider Option B (design decision D8)
| Item | Decision |
|---|---|
| Decider scope | Only eligible UNMAPPED facts with no deterministic mapping are sent. An answer that passes `config/decider_policy.yaml` is stored as an accepted classification and the fact becomes INFERRED (raw answer kept). HUMAN_REVIEW creates a human task. ABSTAIN and ERROR leave the fact UNKNOWN or UNMAPPED |
| Effect on the decision | None directly. Gates and the decision matrix read facts, never the Decider response |

## Cyber remediation: rubric mapping and approval path (step C)
| Item | Decision |
|---|---|
| Rubric mapping | `units/risk_assessment.py approval_tier_inputs` follows the hackathon `scoring-rubric.json`. Action capability is the higher of the write `privilege` and the new `action_capability` (read-only 1, reversible-write 2, business-write 3, production-change 4). The tier thresholds (17/13/9/5) and the three overrides in `risk_tier.py` were already identical to the rubric and are unchanged |
| Approval path effect on autonomy | `action_approval_path: via-human-approval` caps the autonomy score at 2 ("human approves key actions"); `direct` raises it to at least 3. Only `action_approval_path` does this: the payment path (`payment_approval_path`) does not, so the RA03-LITE variants keep their tiers |
| New taxonomy attributes | `action_capability`, `action_approval_path`, `remediation_scope`, `host_tagging`, `environment` in `config/taxonomy.yaml`, with patterns P15 and P16 and the catalog items AIGF-MI-024 `CFG-HITL-PRODUCTION` (mandatory, critical; gate G2 rejects when it fails), AIGF-MI-018 `CFG-REMEDIATION-SCOPE` (high) and the AIGF-RI-024 rule `risk-production-change-without-approval`. A production-change agent also makes `agent_can_perform_high_impact_action` apply |
| Known leftovers | Gate id `G2-PAYMENT-AUTH` and the AIGF-RI-024 remediation text still say payment (see `backlog.md`) |

## Rule authoring: determinism and versions
| Item | Decision |
|---|---|
| Rule_Code and fields fixed by code | For AIGF and uploaded (`UPL`) items the Rule_Code comes from `rule_code_for` (catalog code kept, else `risk-aigf-ri-001`, `ctl-aigf-mi-006`, `ctl-upl-<slug>`), not from the model. A candidate risk rule must test a taxonomy field with a `given` for a node type of that field, using `pattern` or `enumeration`; otherwise the rule is dropped and the DRAFT is kept as inexpressible with the reason |
| Model settings | Bedrock extraction runs at temperature 0.1 with Strands steering (retry with guidance, at most 2). A recorded answer is reused only when input, prompt text, model and parameters match |
| Risk scores from the Decider | Likelihood and impact come from two Decider `score` questions (most probable level, confidence kept, below 0.5 flagged). If the Decider fails, the model's scores stay and the reason is recorded. A human still confirms them before approval |
| Hash rule for catalog items | `rule_authoring.merge` adds new items as DRAFT, leaves same content alone, and gives changed content version + 1. A changed APPROVED item becomes DRAFT and the approved entry is kept as `previous_approved`, which compile keeps using until the new version is approved |
| Compile version from the catalog | Unchanged rules leave the ruleset bytes alone. Changed rules raise the catalog's top-level `version:` (edited in place), and that number is the ruleset header version. Catalog writes keep the YAML comment header |

## MVP direct approve (no roles)
| Item | Decision |
|---|---|
| Approve button | Dashboard Approve for catalog items, patterns, reference architectures and waiting assessments records the fixed actor `dashboard-reviewer` with role `governance_admin` and the rationale "approved in dashboard (MVP, no role check)". There is no login and no role check; this is in `backlog.md` (E06). Approving a risk also records the confirmation of its likelihood and impact. Patterns and reference architectures go to PUBLISHED |
| Reason | The demo needs one-click review; the human-task path with roles stays available through the CLI and the HumanTask store |

## Decider adapter wire format
| Item | Decision |
|---|---|
| Request and answer shape | The platform keeps its own request shape (a `questions` list, answers as a list), which the input hash and fixtures use. `adapters/decider.py default_post` translates it to the server schema (`questions: {name: {type, instructions, criteria}}`, answers keyed by name) and back. Earlier live calls were rejected by the server because the platform shape was sent as is |
| Choice questions | May carry `descriptions`, sent as the `criteria` text of each choice |

## Patterns and reference architectures built in the dashboard
| Item | Decision |
|---|---|
| Field-reuse rule for patterns | A metadata field name already used by a library pattern must keep exactly its schema (unless one side is a `const`), or use another name. `pattern_builder.field_conflicts` rejects a clash at save time, because the Composer would report a conflict when both patterns feed one component. The pattern drafting agent gets the library fields in its prompt and is steered by the same check |
| Hash rule for patterns and RAs | Identical content is not rewritten. Changed content is version + 1 and goes back to DRAFT. P02 is v2 and RA03-LITE was recomposed as ra-version 2 (P02 wording); the older RA version stays in the registry as SUPERSEDED |
| Questions files | `templates/<ra>.questions.yaml` holds the business questions of Generate CALM. Each answer sets template attributes or option choices. The RA agent derives them by rule (one per option and per enum, number or boolean field); free-text fields stay under Advanced |
| Consistency rules | `templates/<ra>.consistency.yaml` ties an attribute to an option choice. An empty attribute is set from the option; a contradicting value is rejected before `calm generate`. Applied by the dashboard path; the command-line `instantiate` checks attributes only |
| Template reuse | `calm generate` receives only the template and the option choices. Attribute values are filled afterwards, so the template file is the same for every application |
## Removed in task 16 (28.2 note)
`pipeline.py`, `applicability.py`, `findings.py`, `scoring.py`, `calm_finos.py`, `validate_v12.py`, `ingest_finos.py`, `transform.py` and `catalogs/seed/` no longer exist. The "Formerly not importable" and "Hard-coded old paths" tables above describe their state before removal.
