"""py-pglite spike (task 1.4): TCP mode on port 5433, persistence across restart.

Run: uv run --no-project --with py-pglite --with "psycopg[binary]" python scripts/spike/pglite_spike.py
Writes JSON results to scripts/spike/pglite_spike_result.json

Findings encoded here:
  * py-pglite 0.5.3 runs `subprocess.run(["npm", ...])` without a shell, which fails on Windows
    (npm is npm.cmd). Workaround: run `npm install` ourselves in work_dir first.
  * The JS it generates uses `new PGlite({extensions})` = in-memory, so data is lost on restart.
    Workaround: pre-write our own pglite_manager.js (the manager only writes it if absent)
    that passes a dataDir.
"""
import importlib.metadata as md
import json
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

import psycopg
from py_pglite import PGliteConfig, PGliteManager

PORT = 5433
OUT = Path(__file__).with_name("pglite_spike_result.json")
res: dict = {"py_pglite": md.version("py-pglite"), "python": sys.version.split()[0], "steps": {}}
DSN = f"host=127.0.0.1 port={PORT} user=postgres password=postgres dbname=postgres sslmode=disable"

CUSTOM_JS = """
const { PGlite } = require('@electric-sql/pglite');
const { PGLiteSocketServer } = require('@electric-sql/pglite-socket');
async function main() {
  const db = new PGlite(process.env.PGLITE_DATA_DIR);
  await db.waitReady;
  const server = new PGLiteSocketServer({ db, host: '127.0.0.1', port: %d });
  await server.start();
  console.log('Server started on TCP 127.0.0.1:%d');
  const stop = async () => { try { await server.stop(); await db.close(); } catch (e) {} process.exit(0); };
  process.on('SIGINT', stop); process.on('SIGTERM', stop);
}
main().catch(e => { console.error(e); process.exit(1); });
""" % (PORT, PORT)


def prep(work: Path, persistent: bool):
    """Set up the PGlite work dir and npm packages; the persistent variant swaps in a custom manager script."""
    work.mkdir(parents=True, exist_ok=True)
    # create package.json via the manager's own logic, then npm install ourselves (Windows workaround)
    PGliteManager(PGliteConfig(use_tcp=True, tcp_port=PORT, work_dir=work))._setup_work_dir()
    if persistent:
        (work / "pglite_manager.js").write_text(CUSTOM_JS)
    if not (work / "node_modules").exists():
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        subprocess.run([npm, "install"], cwd=work, check=True, capture_output=True, timeout=300)


def run(work: Path, phase: str, first: bool, persistent: bool):
    """Start PGlite, run the phase's SQL and record timings in res; the first phase creates the table."""
    import os
    if persistent:
        os.environ["PGLITE_DATA_DIR"] = str(work / "pgdata")
    cfg = PGliteConfig(use_tcp=True, tcp_host="127.0.0.1", tcp_port=PORT, work_dir=work,
                       cleanup_on_exit=False, timeout=60)
    t0 = time.time()
    with PGliteManager(cfg):
        res["steps"][f"{phase}_start_s"] = round(time.time() - t0, 2)
        with psycopg.connect(DSN, autocommit=True) as c:
            res["steps"][f"{phase}_version"] = c.execute("select version()").fetchone()[0][:60]
            if first:
                c.execute("create table spike(id int primary key, v text)")
                c.execute("insert into spike values (1,'persist-me')")
                c.execute("create table spike_j(id int, doc jsonb)")
                c.execute("""insert into spike_j values (1, '{"a":[1,2]}')""")
            try:
                res["steps"][f"{phase}_rows"] = c.execute("select id, v from spike").fetchall()
            except Exception as e:  # noqa: BLE001
                res["steps"][f"{phase}_rows"] = f"ERR {type(e).__name__}"
            if first:
                res["steps"]["json_roundtrip"] = c.execute("select doc->'a'->>1 from spike_j").fetchone()[0]


def scenario(name: str, persistent: bool):
    """Run two phases against a temporary dir to test whether data persists across restarts; the outcome goes in res[name]."""
    base = Path(tempfile.mkdtemp(prefix="pglite_spike_"))
    work = base / "w"
    try:
        prep(work, persistent)
        res["steps"] = {}
        run(work, "first", True, persistent)
        run(work, "second", False, persistent)
        res[name] = dict(res["steps"])
        res[name]["persisted"] = res["steps"].get("second_rows") == [(1, "persist-me")]
    except Exception as e:  # noqa: BLE001
        res[name] = {"error": repr(e), "trace": traceback.format_exc()[-1200:], **res["steps"]}
    finally:
        shutil.rmtree(base, ignore_errors=True)


try:
    scenario("stock_inmemory", False)
    time.sleep(2)
    scenario("custom_datadir", True)
finally:
    res.pop("steps", None)
    OUT.write_text(json.dumps(res, indent=2, default=str))
