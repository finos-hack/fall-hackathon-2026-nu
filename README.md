# ai-governance-intelligence-platform

**Hackathon Track:** {Track 2: Extend & Utilize FINOS Governance-as-Code}

Governance-as-code MVP, assessed at design time. It turns FINOS AIGF and CCC guidance (or uploaded control documents) into approved rules, builds an application's CALM model from approved patterns and reference architectures, and decides whether the design may proceed. The demo applications are Invoice-to-Payment Lite (RA03-LITE) and a cyber remediation agent (RA05-CYBER-REMEDIATION).

The result is design-level evidence only. Build-time and runtime evidence are out of scope. Deferred scope is listed in `backlog.md`. Scoring outputs (severity matrix, gap rule, gates, decision matrix) are **illustrative, not approved policy**.

The platform is three frameworks, each with its own code, tests and data, that run on their own:

| Folder | Package | Purpose |
|---|---|---|
| `rule-authoring-framework/` | `rule_authoring` | AIGF/CCC adapters, uploaded documents, LLM extraction to DRAFT, Decider risk scoring, merge under the hash rule, human approval, control and risk catalogs, consistency check, compile to Spectral rulesets |
| `calm-app-generation-framework/` | `calm_generation` | Pattern library, pattern builder, Composer, RA agent and builder, templates RA03-LITE and RA05-CYBER-REMEDIATION, Attributes_Form, requirement questions, Placeholder_Fill |
| `governance-execution-framework/` | `governance_execution` | CALM/Spectral/Decider adapters, facts, control gap, risk profile, gates and decision matrix, remediation, Coordinator, Direct_Adapter, store, OpenTelemetry, replay, dashboard |
| `shared/` | `agip_shared` | Contracts, hashing, path safety, settings, ModelGateway |

Flow: catalogs -> Spectral rulesets | patterns -> Composer -> template -> attributes form -> `calm generate` -> Placeholder_Fill -> `calm validate -p` -> App_Model -> facts -> two parallel Spectral runs -> control gap + risk profile -> gates, decision matrix, design-only cap -> remediation.

## Installation

Tool prerequisites:

| Tool | Needed for | Install |
|---|---|---|
| Python 3.12, `uv` | everything | https://docs.astral.sh/uv/ |
| `calm` 1.60.1 (`@finos/calm-cli`) | real generate/validate | `npm i -g @finos/calm-cli@1.60.1` |
| `spectral` 6.17.1 | real rule runs | `npm i --prefix .tools @stoplight/spectral-cli@6.17.1` (found automatically) or on `PATH` |
| Docker | Fluxnova orchestration (optional) | Docker Desktop |
| py-pglite | optional store backend | `uv sync --extra pglite` |

Install Python dependencies (Git Bash on Windows, or any shell on OS X & Linux; no cloud infrastructure needed):

```sh
uv sync
```

Connection settings are in `.env` (template `.env.example`).

## Usage example

### Demo

```sh
bash scripts/demo.sh              # recorded tool outputs
REAL_TOOLS=1 bash scripts/demo.sh # installed calm and spectral
```

It compiles the rulesets, instantiates and assesses variants V1-V4, prints the decisions, and opens the dashboard.

| Variant | Result |
|---|---|
| V1 | `APPROVED_WITH_CONDITIONS` |
| V2 | `REJECTED` (gate G2, payment without approval) |
| V3 | `RESTRICTED` (minor gap x High risk) |
| V4 | status `BLOCKED`, no decision (invalid CALM) |

Cyber remediation (RA05-CYBER-REMEDIATION):

| Case | Inputs | Result |
|---|---|---|
| cyber-fixed | analyst approval and decision audit | risk tier High (Tier 2), `APPROVED_WITH_CONDITIONS` |
| cyber-blocked | direct production changes, no audit | risk tier Critical (Tier 1), `REJECTED` by gate G2 |

### Run each framework on its own

Run from the repository folder; every command accepts `--help`.

Rule Authoring:

```sh
uv run python -m rule_authoring.ingest --source aigf|ccc [--path <checkout>] [--ids ...] [--extract --provider replay|bedrock]
uv run python -m rule_authoring.merge
uv run python -m rule_authoring.consistency
uv run python -m rule_authoring.compile [--strict]
uv run python -m rule_authoring.approval {submit,approve,reject,deprecate,confirm} <id> --by <name>
```

CALM App Generation:

```sh
uv run python -m calm_generation --help
uv run python -m calm_generation instantiate --form <attributes.yaml> [--out <file>]
uv run python -m calm_generation validate <file>
```

Governance Execution:

```sh
uv run python -m governance_execution assess <calm.json> [--mode normal|no-llm|replay] [--decider http|fixture] [--cli real|replay]
uv run python -m governance_execution replay <trace>
uv run python -m governance_execution show <trace>
uv run python -m governance_execution resume <trace>
uv run python -m governance_execution.dashboard.app        # dashboard on http://127.0.0.1:8001
```

### Dashboard

No login in the MVP. Menu: Overview, Catalog (Controls, Risk Profile, CALM Patterns), Source Registry, Generate Rules (`/rules/new`), Architecture (Build Pattern `/patterns/new`, Build Reference Architecture `/architectures/new`, Generate CALM `/applications/new`), Assessments.

- **Generate Rules**: upload `.md`/`.yaml` control documents (UTF-8, max 1 MB per file, 20 items per run). Rules are extracted, merged as DRAFT, approved per item, then compiled to rulesets.
- **Build Pattern**: write a YAML spec or let the Strands agent draft it from a description. Approving publishes the pattern.
- **Build Reference Architecture**: the RA agent composes a template from published patterns only. Preview, Save as DRAFT, Approve.
- **Generate CALM**: choose a published reference architecture, answer requirement questions, then the app is generated, filled, validated and assessed.
- **Pending human review**: DRAFT/IN_REVIEW items and `WAITING_FOR_HUMAN` assessments show an Approve button.

### Run on Fluxnova (optional)

[Fluxnova](https://github.com/finos/fluxnova-bpm-platform) (a FINOS fork of Camunda 7) orchestrates the three frameworks through three BPMN workflows: `knowledge_lifecycle`, `architecture_lifecycle`, `assessment_lifecycle`. A Python worker (`scripts/fluxnova_e2e.py`) polls the engine; no code runs inside the container.

```sh
docker run -d --name fluxnova -p 8080:8080 finos/fluxnova-bpm-platform:latest
curl http://localhost:8080/engine-rest/version

uv run python scripts/fluxnova_e2e.py            # about 2-3 minutes, reviews automatic
uv run python scripts/fluxnova_e2e.py --manual   # real human reviews in Tasklist (demo / demo)
```

`.env` settings:

```sh
FLUXNOVA_URL=http://localhost:8080/engine-rest
MODEL_PROVIDER=bedrock
AWS_PROFILE=<profile with Bedrock access>
AWS_REGION=us-west-2
BEDROCK_MODEL_ID=us.amazon.nova-2-lite-v1:0
DECIDER_PROVIDER=http
DECIDER_URL=http://<decider-host>:8000
```

Results are written to `_out/fluxnova/<run-id>/` (`report.json`, `rules/`, `calm/`). Exit code 0 means all workflows completed and Fluxnova matched Direct_Adapter for V1-V4.

### Modes, providers and ports

| Setting | Values | Notes |
|---|---|---|
| Assessment mode | `normal`, `no-llm`, `replay` | `no-llm` gives a deterministic remediation list. `replay` uses recordings only |
| `MODEL_PROVIDER` | `bedrock`, `none`, `replay` | LLM is used for extraction, pattern drafting and remediation text, never for the decision |
| `DECIDER_PROVIDER` | `http`, `fixture` | Advisory only |
| `EXECUTOR` | `direct`, `fluxnova` | `fluxnova` falls back to `direct` with a warning when the engine is down |
| Dashboard | port 8001 | |
| py-pglite | port 5433 | optional store backend |

### Versioning (hash rule)

Generated files are written through `shared/src/agip_shared/versioned_write.py`. A `.versions` sidecar records `inputs_hash` (same inputs: step skipped) and `content_hash` (changed content: version + 1). Details: `docs/STRUCTURE.md`, `docs/REUSE.md`, `docs/deliberate-changes.md`, `docs/spike-notes.md`, `docs/execution_flow.md`.

## Development setup

Tests are offline (about 670 tests, around 7 minutes) and use recorded CALM, Spectral, LLM and Decider outputs.

```sh
uv sync && uv run pytest
```

Run the golden tests against the real CLIs:

```sh
AGIP_REAL_TOOLS=1 uv run pytest governance-execution-framework/tests/golden
```

Per-framework and end-to-end steps: `docs/TESTING.md`. Build commands:

```sh
uv run python scripts/build_patterns.py                     # rebuild the pattern JSON files
uv run python scripts/build_forms.py                        # rebuild the attributes forms
uv run python scripts/build_cyber.py                        # P15, P16, RA05 rules and rulesets (idempotent)
uv run python scripts/seed_recordings.py [--record-cli]     # refresh recorded outputs
```

## Roadmap

This project was built during a time-boxed FINOS hackathon. Goals after the hackathon, if the project continues (full list in `backlog.md`):

1. Add build-time and runtime evidence beyond the current design-level assessment.
2. Add login and role checks to the dashboard.
3. Verify the Decider live and have humans confirm risk scores (live Nova 2 Lite runs gave confidence near 0.45).
4. Replace the illustrative scoring outputs with approved policy.
5. Let the Fluxnova run choose templates and answer requirement questions (currently RA03-LITE only, dashboard-only otherwise).

## Contributing

Coding agents should follow [AGENTS.md](./AGENTS.md), which requires a Developer Certificate of Origin sign-off on every commit.

**All commits** must be signed with a DCO signature to avoid being flagged by the DCO Bot. This means that your commit log message must contain a line that looks like the following one, with your actual name and email address:

```
Signed-off-by: Sridevi P <sridevi.infosec@gmail.com> ; Manoj Kumar S <manojaiconf26@gmail.com>
```

See [CONTRIBUTING.md](./CONTRIBUTING.md) for more information.

## License

Copyright 2026 FINOS

Distributed under the [Apache License, Version 2.0](http://www.apache.org/licenses/LICENSE-2.0).

SPDX-License-Identifier: [Apache-2.0](https://spdx.org/licenses/Apache-2.0)
