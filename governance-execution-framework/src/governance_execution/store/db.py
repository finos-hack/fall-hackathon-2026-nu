"""py-pglite in TCP mode (default 127.0.0.1:5433) with the workarounds from docs/spike/pglite.md.

1. ``npm install`` is run by us (``npm.cmd`` on Windows) because py-pglite calls ``npm`` without a shell.
2. We pre-write a file-backed ``pglite_manager.js`` (``new PGlite(PGLITE_DATA_DIR)``) so data persists.

``py_pglite`` and ``psycopg`` are imported lazily so the file artifact store works without them.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from agip_shared.settings import Settings

CUSTOM_JS = """
const { PGlite } = require('@electric-sql/pglite');
const { PGLiteSocketServer } = require('@electric-sql/pglite-socket');
async function main() {
  const db = new PGlite(process.env.PGLITE_DATA_DIR);
  await db.waitReady;
  const server = new PGLiteSocketServer({ db, host: '%(host)s', port: %(port)d });
  await server.start();
  console.log('Server started on TCP %(host)s:%(port)d');
  const stop = async () => { try { await server.stop(); await db.close(); } catch (e) {} process.exit(0); };
  process.on('SIGINT', stop); process.on('SIGTERM', stop);
}
main().catch(e => { console.error(e); process.exit(1); });
"""


class PGliteUnavailable(RuntimeError):
    """py-pglite could not be started or connected to (triggers the YAML/SQLite fallback)."""


def dsn(settings: Settings) -> str:
    """Build the libpq connection string for the local PGlite TCP server (fixed postgres credentials, no SSL)."""
    return (f"host={settings.pglite_host} port={settings.pglite_port} user=postgres "
            f"password=postgres dbname=postgres sslmode=disable")


class PGliteServer:
    """Lifecycle manager for a file-backed py-pglite TCP server; usable as a context manager. Raises PGliteUnavailable when it cannot run."""
    def __init__(self, settings: Settings, startup_timeout_s: float = 90):
        """Record settings and derive the work and data directories; nothing is started or created yet."""
        self.settings = settings
        self.timeout = startup_timeout_s
        self.data_dir = Path(settings.data_dir)
        self.work_dir = self.data_dir / "pglite_work"
        self.pgdata = Path(settings.pglite_data_dir)
        self._manager = None

    def prepare(self) -> None:
        """Check prerequisites (py-pglite, node, npm), write the custom manager script and run ``npm install`` once. Raises PGliteUnavailable on any failure."""
        try:
            from py_pglite import PGliteConfig, PGliteManager  # noqa: F401
        except ImportError as e:
            raise PGliteUnavailable(f"py-pglite not installed: {e}") from e
        if not shutil.which("node"):
            raise PGliteUnavailable("node not found on PATH")
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.pgdata.parent.mkdir(parents=True, exist_ok=True)
        cfg = self._config()
        from py_pglite import PGliteManager
        PGliteManager(cfg)._setup_work_dir()  # writes package.json
        (self.work_dir / "pglite_manager.js").write_text(
            CUSTOM_JS % {"host": self.settings.pglite_host, "port": self.settings.pglite_port})
        if not (self.work_dir / "node_modules").exists():
            npm = shutil.which("npm.cmd") or shutil.which("npm")
            if not npm:
                raise PGliteUnavailable("npm not found on PATH")
            try:
                subprocess.run([npm, "install"], cwd=self.work_dir, check=True,
                               capture_output=True, timeout=300)
            except (subprocess.SubprocessError, OSError) as e:
                raise PGliteUnavailable(f"npm install failed: {e}") from e

    def _config(self):
        """Build the py-pglite TCP configuration for this server (lazy import)."""
        from py_pglite import PGliteConfig
        return PGliteConfig(use_tcp=True, tcp_host=self.settings.pglite_host,
                            tcp_port=self.settings.pglite_port, work_dir=self.work_dir,
                            cleanup_on_exit=False, timeout=int(self.timeout))

    def start(self) -> None:
        """Prepare and launch the server. Sets ``PGLITE_DATA_DIR`` in this process's environment; raises PGliteUnavailable if start fails."""
        self.prepare()
        from py_pglite import PGliteManager
        os.environ["PGLITE_DATA_DIR"] = str(self.pgdata.resolve())
        mgr = PGliteManager(self._config())
        try:
            mgr.start()
        except Exception as e:  # noqa: BLE001 - any start failure means fall back
            raise PGliteUnavailable(f"py-pglite failed to start: {e}") from e
        self._manager = mgr

    def stop(self) -> None:
        """Stop the server if running; safe to call repeatedly."""
        if self._manager is not None:
            self._manager.stop()
            self._manager = None

    def __enter__(self) -> "PGliteServer":
        """Start the server and return it."""
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        """Stop the server; exceptions from the block propagate."""
        self.stop()
