# Rule authoring framework

Purpose: turn AIGF/CCC controls and mitigations (or uploaded control documents) into canonical rules, catalogs and rulesets.

Boundaries: depends only on `agip_shared`. Knows nothing of CALM models or assessments. The one read of another framework's data is the checkable taxonomy fields in `governance-execution-framework/config/taxonomy.yaml`, loaded at runtime for the extraction prompt and rule checks.

Layout: `src/rule_authoring/`, `catalogs/` (`controls.catalog.yaml`, `risks.catalog.yaml`, `sources/`, `drafts/` when extraction has run), `rulesets/` (`controls.spectral.yaml`, `risks.spectral.yaml`), `prompts/` (`extraction.v1.md`, `extraction.v2.md`), `docs/` (authoring guide, walkthrough), `fixtures/recordings/` (`llm/`, `decider-scores/`), `tests/`.

Entry points:
- `uv run python -m rule_authoring.ingest --source aigf|ccc [--extract --provider replay|bedrock] [--temperature T] [--scores decider|llm] [--steering-retries N]` (see `docs/AUTHORING-GUIDE.md`)
- `uv run python -m rule_authoring.merge [--drafts DIR] [--catalogs DIR] [--ids ID ...]`: merge DRAFTs into the catalogs
- `uv run python -m rule_authoring.approval`, `.coverage`, `.consistency`, `.compile`
- `rule_authoring.upload.parse_upload`: uploaded `.md`/`.markdown`/`.yaml`/`.yml` to source items (used by the dashboard's Generate Rules)

Extraction (`extraction.py`):
- Rule_Code is fixed by code (`rule_code_for`): an existing catalog code is kept, otherwise `risk-aigf-ri-001`, `ctl-aigf-mi-006` or `ctl-upl-<slug>`.
- A candidate rule must test a taxonomy field, with `given` = `$.nodes[?(@['node-type']=='<type>')].metadata` for a node type that has the field, and `pattern` (match/notMatch) or `enumeration` values. An invalid rule is dropped and the DRAFT is kept as inexpressible with the reason (`candidate_rule: null`, `inexpressible_reason`).
- `steering_check()` applies the same checks live. With `--provider bedrock` (temperature 0.1) the Strands steering handler rejects a failing answer and retries with guidance, at most `--steering-retries` times.
- Risk likelihood and impact come from the Strands Decider (`scoring.DeciderScorer`, `--scores decider`, AIGF risks only). Confidence below 0.5 is flagged `low_confidence`. Answers are recorded by input hash in `fixtures/recordings/decider-scores`. If the Decider fails, the LLM scores are used and the reason is stored.

Versioning (hash rule, `agip_shared.versioned_write`): a `.versions` index per folder holds `inputs_hash` and `content_hash`.
- Sources and drafts: unchanged inputs are not regenerated; a changed draft raises the catalog version by 1.
- `merge`: new item -> DRAFT; same -> unchanged; changed APPROVED item -> DRAFT with version + 1, and the approved entry (`previous_approved`) stays in force for `compile` until the new version is approved. Approval records the version.
- `compile`: unchanged rules leave the ruleset bytes alone; changed rules raise the catalog's top-level `version:` (now 2), which is the ruleset header version. Catalog writes keep the YAML comment header.
