# Spike 1.2: Spectral CLI

Reqs: 2.5, 2.10. Scripts: `spectral_spike.sh`, `spectral_spike2.sh` (run from platform root in Git Bash; they install Spectral into a temp dir).

## Version
- `@stoplight/spectral-cli` **6.17.1** (installed via `npm i`, Node v22.17.0). Pin this version.
- Invoke as `npx spectral lint <file> -r <ruleset> -f json`.

## Input
`calm-app-generation-framework/fixtures/variants/customer-support-gap.json` (CALM JSON, top-level `nodes`, 109 lines). Rulesets are YAML with JSONPath `given`.

## Output (`-f json`)
A JSON array of results. An empty array `[]` means no findings. Example (error-severity rule, `given: "$"`, `field: nonexistent`):

```json
[{"code":"e","path":[],"message":"\"nonexistent\" property must be truthy","severity":0,
  "range":{"start":{"line":0,"character":0},"end":{"line":108,"character":47}},
  "source":"c:/.../c.json"}]
```

Result fields: `code` (rule id), `path` (array of keys/indexes into the document; indexes are strings, e.g. `["nodes","0","name"]`), `message`, `severity`, `range` (0-based line/character start/end), `source` (absolute file path, forward slashes on Windows). `severity` is numeric: **0=error, 1=warn, 2=info, 3=hint**.

A warn rule on `$.nodes[?(@['node-type']=='actor')]` produced `code:"node-type-actor-warn"`, `path:["nodes","0","name"]`, `severity:1`.

## Exit codes
| Case | Exit |
|---|---|
| No findings | 0 |
| Only warn findings (default) | 0 |
| Warn findings with `--fail-severity=warn` | 1 |
| At least one error-severity finding | 1 |
| Ruleset file not found | 2 (stderr: `Error running Spectral!` + ENOENT) |
| Input file not found | 2 (stderr: `No files found to lint...`) |

So exit 1 means findings at or above the fail severity (default `error`), and exit 2 means a tool or usage failure. Treat 0/1 as a valid run and anything else as an error.

## Gotchas
- With `-f json` and no `-o`, Spectral can append a plain-text line to **stdout** after the JSON (observed `No results with a severity of 'error' found!` after `[]`). That breaks `json.loads` on stdout. Use `-o <file>` (verified: `-o r.json` writes clean JSON, stdout and stderr stay empty), or parse from the first `[` to the matching `]`.
- Errors go to stderr as text, not JSON.
- Result `source` is an absolute path, so normalise it if comparing to relative paths.
- Windows note: running through `npx` under Git Bash printed garbage from npm banners on the terminal (cosmetic only). Calling `./node_modules/.bin/spectral` directly avoids it.

## Recommendation
Run `spectral lint <file> -r <ruleset> -f json -o <tmp.json>`, accept exit codes 0 and 1, treat 2 as failure, and read results from the output file. Map `severity` 0/1/2/3 to error/warn/info/hint.

## Flag and fallback
- `-F` is the short form of `--fail-severity` (`error` default; `warn`, `info`, `hint` also accepted). `-F warn` makes warn findings exit 1.
- Spectral was not on PATH (`spectral: command not found`). Fallback verified: `npx --yes @stoplight/spectral-cli --version` prints `6.17.1`. Prefer a pinned local install (`npm i @stoplight/spectral-cli@6.17.1`) and call `node_modules/.bin/spectral`.

## Configuration and contingency
- Expected interface: `spectral lint -r <ruleset> -f json`; parse results from JSON, never from the exit code.
- .env keys: `SPECTRAL_BIN`, `TOOL_TIMEOUT_S`.
- Contingency: adapter returns ERROR (never VALID) when the tool is missing, times out, or output is unparseable.
- Task 3.14 smoke test must re-check the real output shape.
