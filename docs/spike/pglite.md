# Spike 1.4: py-pglite (TCP mode, Windows, port 5433)

Requirements: 2.7, 2.10. Script: `scripts/spike/pglite_spike.py`. Raw results: `scripts/spike/pglite_spike_result.json`.
Run (Git Bash): `uv run --no-project --with py-pglite --with "psycopg[binary]" python scripts/spike/pglite_spike.py`

## Environment
- Windows, Python 3.12, Node (v22.17.0 at spike time; v24.11.0 installed now, not re-run), py-pglite 0.5.3, psycopg 3 (binary).
- Server reports PostgreSQL 17.4 (PGlite, WASM).

## Result: PASS with two required workarounds

| Check | Stock py-pglite | With workarounds |
|---|---|---|
| Start in TCP mode on 127.0.0.1:5433 | Fails on Windows (see 1) | OK |
| Connect with psycopg (`user=postgres password=postgres sslmode=disable`) | n/a | OK |
| DDL, insert, select, jsonb (`doc->'a'->>1`) | n/a | OK |
| Data survives stop and restart | No, in-memory (see 2) | Yes |

### 1. `npm install` fails on Windows
`PGliteManager._install_dependencies` calls `subprocess.run(["npm", "install"])` without a shell. On Windows `npm` is `npm.cmd`, so `CreateProcess` raises `FileNotFoundError: [WinError 2]`.
Workaround: before starting the manager, create the work dir, run `npm.cmd install` in it (use `shutil.which("npm.cmd")`), so `node_modules` exists and the manager skips its own install.

### 2. Generated server script is in-memory
The `pglite_manager.js` that py-pglite generates uses `new PGlite({extensions})` with no `dataDir`. After a restart the table is gone (`UndefinedTable`).
Workaround: the manager only writes `pglite_manager.js` if it does not already exist. Pre-write our own script that calls `new PGlite(process.env.PGLITE_DATA_DIR)` and starts `PGLiteSocketServer({db, host:'127.0.0.1', port:5433})`, with SIGINT/SIGTERM handlers. With this, the row inserted before restart was returned after restart.

### Timings
Stock in-memory start about 1.6 s. With a file-backed `dataDir`, first start (initdb) 13.2 s, restart 5.2 s. Allow a startup wait of at least 60 s (spike used `timeout=60`).

### Caveats
- Single connection: PGlite serves one connection at a time (single-user Postgres). The store must use one connection or serialise access (no pooling).
- Shutdown: `PGliteManager.stop()` terminates the node process. On Windows that is a hard kill, so the SIGTERM handler may not run. Persistence still held in the spike after `stop()`, but a crash mid-write is not proven safe. Mitigation: artifacts are immutable files with SHA-256 (task 2.4), the DB can be rebuilt from the YAML seed and artifact files.
- Port 5433 must be free; the second scenario waited 2 s after the first.

## Decision for task 2.4
Use py-pglite in TCP mode on 5433 with the pre-written file-backed `pglite_manager.js` and the pre-run `npm.cmd install`. Put the work dir and `pgdata` under `data/`.

## Contingency (Requirement 2.10)
Trigger: PGlite fails to start (Node missing, npm install fails, port in use) or data does not persist.
1. YAML seed + file export (primary fallback): load catalogs and rule metadata from YAML seed files at start; write each artifact and run record as JSON under `data/artifacts/<trace>/<kind>/<id>.json` with SHA-256; serve the UI/API from an in-memory repository rebuilt from those files.
2. SQLite (last resort): same `schema.sql` restricted to portable types (use TEXT for jsonb, no Postgres-only functions), file `data/agip.sqlite`, via stdlib `sqlite3`.
Store code should sit behind one repository interface so the backend is chosen by config (`store.backend: pglite | yaml | sqlite`).

## Configuration (.env)
- Expected interface: TCP on 5433 (local).
- .env keys: `PGLITE_HOST`, `PGLITE_PORT`, `PGLITE_DATA_DIR`, `DATA_DIR`.
- Contingency: YAML seed + file export, then SQLite (see above).
