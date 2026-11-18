# CALM app generation framework

Purpose: read, generate and validate CALM architectures: build patterns and reference architectures (RA), compose templates, and instantiate applications.

Boundaries: depends only on `agip_shared`. Does not know about rules or governance decisions.

Layout: `src/calm_generation/`, `patterns/` (P02, P03, P07, P08, P11 to P17 as JSON, plus `SPECS.md`), `templates/` (per RA: `<RA>.json`, `.compose.yaml`, `.questions.yaml`, `.consistency.yaml`), `registry/lifecycle.yaml` (status, versions and review history), `prompts/pattern-draft.v1.md`, `fixtures/variants/` (example CALM models), `docs/VOCABULARY.md`, `tests/`.

Content:
- Seed patterns P02 to P14 (P02 is at version 2), P15 High-Impact Action Approval and P16 Controlled Remediation (published), and P17 "New Pattern" (created from the dashboard, kept).
- Templates: RA03-LITE (ra-version 2, recomposed after the P02 change) and RA05-CYBER-REMEDIATION (P08, P11, P12, P14, P15, P16).

Entry points:
- `uv run python -m calm_generation --help` (patterns, versions, compose, submit, approve, publish, reject, deprecate, form, instantiate, validate)
- `uv run python -m calm_generation.composer` rebuilds `templates/RA03-LITE.json`

Modules used by the dashboard:
- `pattern_builder.py`: YAML spec to a validated CALM pattern (nodes with metadata or port, relationships, related controls and risks); a field name already in the library must keep its exact schema.
- `ra_agent.py`: Strands agent that composes a reference architecture from published patterns only. The Composer, `calm validate -p` and the question checks run in the loop (code-driven, at most 4 rounds). Weak spot: balancing `oneOf` choices.
- `ra_builder.py`: preview (writes nothing), save as DRAFT, approve and publish; edit existing RAs.
- `questions.py`: requirement questions per RA, derived by rule (one per option, enum, number and boolean field); `<RA>.consistency.yaml` holds the attributes implied by an option, and contradictions are rejected before `calm generate`.
- `draft_agent.py`: Strands pattern drafting for the Fluxnova run (`PatternDraftAgent(cache_dir=)` caches drafts by inputs hash).

Notes:
- `calm generate` receives only the template (`-p`) and option choices; attribute values are filled afterwards by `placeholders.fill`.
- Hash rule (`agip_shared.versioned_write`): saving an unchanged pattern or RA writes nothing; a change raises its version. Approving a pattern or RA marks the file `APPROVED` (`mark_approved`). Generate CALM offers only PUBLISHED RAs.
