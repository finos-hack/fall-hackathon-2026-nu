# Testing guide

How to test each framework on its own and the platform end to end. Run every command from the
`ai-governance-intelligence-platform` folder in Git Bash.

## 0. Setup

```bash
uv sync
calm --version                                   # 1.60.1, only for real-tool runs
.tools/node_modules/.bin/spectral --version      # 6.17.1, only for real-tool runs
mkdir -p _out                                    # scratch folder (gitignored)
```

Install the tools if they are missing:

```bash
npm i -g @finos/calm-cli@1.60.1
npm i --prefix .tools @stoplight/spectral-cli@6.17.1
```

For offline runs, set these in `.env` so no Bedrock or Decider call is attempted:

```
MODEL_PROVIDER=replay
DECIDER_PROVIDER=fixture
```

| Test source | What it uses |
|---|---|
| Automated tests (default) | Recorded CALM, Spectral, LLM and Decider outputs. No tools or network |
| `AGIP_REAL_TOOLS=1` | Real `calm` and `spectral`. LLM and Decider are still recorded |
| Manual commands below | Real `calm` and `spectral` unless noted |

## 1. All automated tests

```bash
uv run pytest -q shared/tests rule-authoring-framework/tests calm-app-generation-framework/tests governance-execution-framework/tests
                                  # the four framework suites: 558 passed, 1 skipped (about 4 min)
uv run pytest -q tests            # cross-framework guards: dependency direction, consistency, imports, integrated journey
```

### Independent suites (one framework at a time)

| Suite | Command | Result |
|---|---|---|
| Shared | `uv run pytest shared/tests -q` | 112 passed |
| Rule Authoring | `uv run pytest rule-authoring-framework/tests -q` | 112 passed, 1 skipped (real Spectral step, skipped when Spectral is not on PATH) |
| CALM App Generation | `uv run pytest calm-app-generation-framework/tests -q` | 51 passed |
| Governance Execution (includes golden) | `uv run pytest governance-execution-framework/tests -q` | 283 passed |
| Governance Execution (no golden) | `uv run pytest governance-execution-framework/tests -q --ignore=governance-execution-framework/tests/golden` | subset of the line above |

Total of the four suites: 558 passed, 1 skipped. The suites cover the new code from this round: the hash rule and versioning (`versioned_write`, `versioning`, `merge`), upload parsing, taxonomy-based rule checks and steering, Decider scoring, the Decider request translation, pattern and RA builders, requirement questions and consistency rules, and the dashboard routes (Generate Rules, Build Pattern, Build Reference Architecture, Generate CALM, approve endpoints). The dashboard can add patterns and revise versions, so the library now holds P02, P03, P07, P08 and P11 to P17, and pattern, template and ruleset versions come from the files.

### Acceptance suites (marker `acceptance`)

Each framework has one standalone acceptance suite: Rule Authoring `tests/test_journey.py`, CALM Generation `tests/test_journey.py`, and Governance Execution `tests/test_cli_standalone.py` (external CALM, frozen catalogs). Each runs alone:

```bash
uv run pytest -q rule-authoring-framework/tests/test_journey.py
uv run pytest -q calm-app-generation-framework/tests/test_journey.py
uv run pytest -q governance-execution-framework/tests/test_cli_standalone.py
uv run pytest -q -m acceptance     # all three
```

### Integrated suite

```bash
uv run pytest governance-execution-framework/tests/golden -v                      # V1-V4, recorded tool outputs
AGIP_REAL_TOOLS=1 uv run pytest governance-execution-framework/tests/golden -v    # real calm and spectral
```

All suites are offline. No test needs Bedrock, the Decider, Docker or Fluxnova (deferred, see `backlog.md`).

## 2. Shared package (`shared/`)

Covers contracts, hashing, path containment, settings and the ModelGateway (none, replay and bedrock providers, secret and path scrubbing).

```bash
uv run pytest shared/tests -q
```

Manual check: the gateway refuses to run with `provider: none`, and replay names a missing record.

```bash
uv run python - <<'EOF'
from agip_shared.gateway import ModelGateway, Recorder, sanitize
print(sanitize({"api_key": "x", "note": "see C:\\Users\\me\\secret.txt"}))
try:
    ModelGateway("replay", recorder=Recorder("_out/empty")).complete("extraction", "v1", {"a": 1})
except Exception as e:
    print(type(e).__name__, e)
EOF
```

Expected: the key and the path are replaced by `[REDACTED]`, then `RecordingMissingError missing recording: extraction/v1/<hash>`.

## 3. Rule Authoring framework (`rule-authoring-framework/`)

Automated tests cover the source adapters, extraction schema, approval, consistency check, compile, catalogs and recorded extractions.

```bash
uv run pytest rule-authoring-framework/tests -q
```

### 3.1 Source adapters (AIGF)

Needs the `ai-governance-framework` checkout next to this repo.

```bash
uv run python - <<'EOF'
from rule_authoring.sources_aigf import read
items, errors = read(["../ai-governance-framework/docs/_mitigations", "../ai-governance-framework/docs/_risks"])
print(len(items), "items,", len(errors), "errors")
print([i.id for i in items][:5])
EOF
```

### 3.2 Consistency check and compile

```bash
uv run python -m rule_authoring.consistency    # prints "consistent", exit 0
uv run python -m rule_authoring.compile        # controls v2 rules=15, risks v2 rules=7 (unchanged rules leave the bytes alone)
git diff --stat rule-authoring-framework/rulesets   # no diff: compile is deterministic
```

### 3.3 Only APPROVED rules are compiled, and approval

This works on a copy of the catalogs, so the real files are untouched.

```bash
rm -rf _out/cat _out/rs && cp -r rule-authoring-framework/catalogs _out/cat
sed -i '0,/status: APPROVED/s//status: DRAFT/' _out/cat/controls.catalog.yaml   # first control (AIGF-MI-024) -> DRAFT
uv run python -m rule_authoring.compile --catalogs _out/cat --out _out/rs      # skipped_unapproved=1, fewer controls rules
A="uv run python -m rule_authoring.approval"
$A approve AIGF-MI-024 --by bob --role rule_reviewer --rationale skip --catalog _out/cat/controls.catalog.yaml   # refused: must be IN_REVIEW first
$A submit  AIGF-MI-024 --by alice --role author --rationale ready --catalog _out/cat/controls.catalog.yaml
$A approve AIGF-MI-024 --by bob --role rule_reviewer --rationale checked --catalog _out/cat/controls.catalog.yaml
uv run python -m rule_authoring.compile --catalogs _out/cat --out _out/rs      # controls v2 rules=15 skipped_unapproved=0
cmp _out/rs/controls.spectral.yaml rule-authoring-framework/rulesets/controls.spectral.yaml && echo identical
```

### 3.4 Extraction from recordings (no Bedrock)

```bash
uv run pytest rule-authoring-framework/tests/test_seed_recordings.py -q
```

## 4. CALM App Generation framework (`calm-app-generation-framework/`)

Automated tests cover the pattern library, technology neutrality, related IDs, the Composer (determinism, conflicts, no added metadata) and template publishing.

```bash
uv run pytest calm-app-generation-framework/tests -q
```

### 4.1 Patterns validate with the CALM CLI

```bash
for f in calm-app-generation-framework/patterns/P*.json; do
  printf '%s ' "$(basename "$f")"; calm validate -p "$f" -f json 2>/dev/null | grep '"hasErrors"'
done
```

Expected: `"hasErrors": false` for every pattern file (11: P02, P03, P07, P08, P11 to P17).

### 4.2 Compose the RA03-LITE template

RA03-LITE is ra-version 2 (recomposed after P02 became v2). RA05-CYBER-REMEDIATION (P08 P11 P12 P14 P15 P16) is the second template.

```bash
uv run python -m calm_generation.composer      # RA03-LITE.json sha256=...
git diff --stat calm-app-generation-framework/templates   # no diff: composition is deterministic
calm validate -p calm-app-generation-framework/templates/RA03-LITE.json -f json 2>/dev/null | grep '"hasErrors"'
```

### 4.3 Attributes form and placeholder fill

```bash
uv run python scripts/build_forms.py           # rewrites the forms; expect no git diff
git diff --stat governance-execution-framework/forms
```

### 4.4 Generate and validate one variant by hand

```bash
calm generate -p calm-app-generation-framework/templates/RA03-LITE.json \
  --option-choices '{"opt-approval-path":"Direct to Payment API","opt-audit":["Audit service present"]}' \
  -o _out/v2-generated.json < /dev/null
grep -c '\[\[' _out/v2-generated.json          # placeholders left by calm generate
calm validate -p calm-app-generation-framework/templates/RA03-LITE.json \
  -a calm-app-generation-framework/fixtures/variants/invoice-lite-v4.json -f json 2>/dev/null | grep -E 'hasErrors|message'
```

Expected: V4 reports `must be <= 100000` at `/nodes/payment-agent/metadata/payment_limit`.

## 5. Governance Execution framework (`governance-execution-framework/`)

Automated tests cover the adapters, store, facts, Decider and acceptance policy, control and risk assessment, gates and decision, and the CALM Builder unit.

```bash
uv run pytest governance-execution-framework/tests -q --ignore=governance-execution-framework/tests/golden
```

### 5.1 Spectral rulesets on a stored App_Model

```bash
for lane in controls risks; do
  .tools/node_modules/.bin/spectral lint calm-app-generation-framework/fixtures/variants/invoice-lite-v2.json \
    -r rule-authoring-framework/rulesets/$lane.spectral.yaml -f json -o _out/v2-$lane.json
  echo "$lane: $(grep -o '"code": *"[^"]*"' _out/v2-$lane.json | sort -u | tr '\n' ' ')"
done
```

Expected for V2: controls `ctl-agent-least-privilege`, `ctl-payment-requires-human-approval`; risks `risk-payment-bypasses-approval`.

### 5.2 Assess one App_Model (instantiate and assess)

```bash
uv run python - <<'EOF'
import yaml
from pathlib import Path
from agip_shared.settings import Settings
from governance_execution.exec import factory
from governance_execution.units.calm_builder import instantiate, load_template

s = Settings(_env_file=None, decider_provider="fixture", model_provider="replay")
coord, ex = factory.build("normal", settings=s, data_dir=Path("_out/manual"), cli="real")   # cli="replay" for no tools
tpl, text = load_template("RA03-LITE")
form = yaml.safe_load(Path("governance-execution-framework/forms/v3.attributes.yaml").read_text(encoding="utf-8"))
r = instantiate(form, template=tpl, template_text=text, template_status="PUBLISHED", calm=coord.ctx.calm)
out = coord.run(r.app_model, executor=ex, template_id="RA03-LITE", source={"app_id": form["app"]["id"]})
print(r.status, out.status, out.decision, out.trace_id)
gap = coord.ctx.sink.get(out.trace_id, "control_gap", "result")
prof = coord.ctx.sink.get(out.trace_id, "risk_profile", "result")
print("gap", gap["gap_level"], "| risk", prof["profile_level"], [x["risk_id"] for x in prof["risks"]])
EOF
```

Expected for V3: `VALID COMPLETED RESTRICTED`, gap `minor`, risk `High`. Artifacts are in `_out/manual/artifacts/<trace>/`.

### 5.3 Modes

Use the same script with `factory.build("no-llm", ...)` (remediation becomes a deterministic list) or `factory.build("replay", ...)` (recordings only, fails naming a missing record).

## 6. End-to-end

### 6.1 Golden E2E tests (V1-V4, no-LLM, replay, most-favourable Decider)

```bash
uv run pytest governance-execution-framework/tests/golden -v                      # recorded tool outputs
AGIP_REAL_TOOLS=1 uv run pytest governance-execution-framework/tests/golden -v    # real calm and spectral
```

| Variant | CALM | Decision | Reason |
|---|---|---|---|
| V1 | VALID | APPROVED_WITH_CONDITIONS | no gaps or risks; design-only cap |
| V2 | VALID | REJECTED | gate G2, payment without human approval |
| V3 | VALID | RESTRICTED | minor gap (no audit) x High risk (autonomous payment agent) |
| V4 | INVALID | status BLOCKED, no decision | invalid CALM: payment limit above the pattern maximum |

### 6.2 Demo and dashboard

```bash
bash scripts/demo.sh               # recorded tool outputs
REAL_TOOLS=1 bash scripts/demo.sh  # real calm and spectral
```

The script prints the four decisions and opens http://127.0.0.1:8001. Check:

- [ ] Assessments list shows the decision, mode and Executor (`Direct_Adapter`, development-only).
- [ ] Report: decision, gates, matrix cell, CALM validation, control gaps (PASS = design-level evidence only), risk profile, 5x5 matrix, remediation, UNMAPPED fact `invoice-db.data_classification`, Decider panel.
- [ ] Flow page shows the two parallel Spectral lanes. V4 shows the blocked path.
- [ ] Architecture page colours nodes by worst finding (V2: payment agent red).
- [ ] Traceability explorer: from `decision`, follow V2 gate G2 -> AIGF-MI-024 -> rule code -> JSON path -> payment-agent -> pattern P13 -> AIGF mi-24, and back.
- [ ] Static export downloads a self-contained HTML file. Open it offline.
- [ ] Sidebar: Overview; Catalog (Controls Catalog, Risk Profile Catalog, CALM Patterns Catalog); Source Registry; Generate Rules; Architecture (Build Pattern, Build Reference Architecture, Generate CALM); Assessments. Overview shows six metrics (Controls, Risks, Patterns, Reference Architectures, Control Gaps Assessment, Risk Assessment).
- [ ] Variants, Versions and Catalog pages load. Draft items show the PENDING HUMAN REVIEW badge with an Approve button.
- [ ] Both labels appear on every page: "illustrative, not approved policy" and "design-level evidence only".

### 6.3 Dashboard workflows (manual)

Generate Rules, Build Pattern, Build Reference Architecture, Generate CALM, the Approve buttons and the cyber RA05 variants (expected: cyber-fixed APPROVED_WITH_CONDITIONS, cyber-blocked REJECTED) are tested by hand in `docs/functional_manual_testing.md` sections 9 to 15. These pages write into the repo catalogs, registry, patterns and templates; run `git status` and restore afterwards.

### 6.4 Dashboard API

Run this while the dashboard is up. Upload and instantiate need the real `calm` CLI.

```bash
B=http://127.0.0.1:8001
curl -s $B/api/attributes-form/RA03-LITE | head -20
curl -s -X POST --data-binary @governance-execution-framework/forms/v2.attributes.yaml $B/api/instantiate | head -c 400; echo
REF=$(curl -s -X POST --data-binary @calm-app-generation-framework/fixtures/variants/invoice-lite-v2.json $B/api/upload \
      | sed -E 's/.*"app_model_ref":"([^"]+)".*/\1/')
curl -s -X POST -H 'content-type: application/json' \
     -d "{\"app_model_ref\":\"$REF\",\"mode\":\"no-llm\",\"template_id\":\"RA03-LITE\"}" $B/api/assess; echo
curl -s -X POST $B/api/replay/<trace_id>; echo          # use a trace ID from the list page
# Also in the API docs (/api/docs): POST /catalogs/{kind}/{id}/approve and POST /api/assessments/{trace}/approve (MVP approve, no login)
head -c 1100000 /dev/zero | tr '\0' ' ' > _out/big.json
curl -s -o /dev/null -w '%{http_code}\n' -X POST --data-binary @_out/big.json $B/api/upload   # 413
```

Expected: upload V2 and assess gives `REJECTED`. Replay gives `"identical": true`. An upload over 1 MB gives `413`.

## 7. Refreshing recordings

Do this after changing catalogs, patterns, a template or forms (also after approving a catalog change in the dashboard, because the CLI recordings are keyed by ruleset bytes):

```bash
uv run python scripts/build_cyber.py                    # idempotent; only if the cyber pieces changed
uv run python -m rule_authoring.compile
uv run python -m calm_generation.composer
uv run python scripts/build_forms.py
rm -rf governance-execution-framework/fixtures/recordings/cli
uv run python scripts/seed_recordings.py --record-cli   # runs calm and spectral, records outputs, Decider and LLM seeds
uv run pytest
```

If the generated App_Models change, update `calm-app-generation-framework/fixtures/variants/invoice-lite-v*.json` and `expected.yaml`. The golden tests compare against them.
