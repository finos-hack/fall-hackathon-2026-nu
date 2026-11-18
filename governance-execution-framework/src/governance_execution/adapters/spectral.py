"""Spectral_Adapter: runs `spectral lint -r <ruleset> -f json` and parses the JSON.

Results come from the JSON output, never from the exit code. Missing tool,
timeout, or unparsable output yields status ERROR (never a pass); lint never raises.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from agip_shared.contracts import SpectralResult, SpectralRun

# runner(args, timeout_s, cwd) -> (returncode, stdout, stderr)
Runner = Callable[[List[str], float, str], Tuple[int, str, str]]


def default_runner(args: List[str], timeout_s: float, cwd: str) -> Tuple[int, str, str]:
    """Run a command with list args (no shell). May raise FileNotFoundError/TimeoutExpired."""
    exe = shutil.which(args[0]) or args[0]  # resolves .cmd shims on Windows
    p = subprocess.run(
        [exe, *args[1:]], capture_output=True, text=True, timeout=timeout_s, cwd=cwd, shell=False,
        stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace",
    )
    return p.returncode, p.stdout, p.stderr


@dataclass
class SpectralRecord:
    """Raw + parsed evidence of the last lint call."""

    args: List[str]
    exit_code: Optional[int] = None
    duration_s: float = 0.0
    version: Optional[str] = None
    raw_stdout: str = ""
    raw_stderr: str = ""
    parsed: Optional[List[Dict[str, Any]]] = None


class SpectralAdapter:
    """Wrapper around ``spectral lint``. ``lint`` never raises; ``last`` holds the latest call's evidence."""
    def __init__(
        self,
        spectral_bin: str = "spectral",
        timeout_s: float = 60,
        runner: Optional[Runner] = None,
    ) -> None:
        """``runner`` replaces the subprocess runner (used by tests and recordings)."""
        self.spectral_bin = spectral_bin
        self.timeout_s = timeout_s
        self._run = runner or default_runner
        self.last: Optional[SpectralRecord] = None

    def _version(self, cwd: str) -> Optional[str]:
        """Return the Spectral version string, or None if the call fails or prints nothing."""
        try:
            code, out, _ = self._run([self.spectral_bin, "--version"], self.timeout_s, cwd)
            v = (out or "").strip()
            return v if code == 0 and v else None
        except Exception:
            return None

    def lint(self, app: Union[Dict[str, Any], str, Path], ruleset: Union[str, Path]) -> SpectralRun:
        """Lint ``app`` (dict, JSON text or file path) with ``ruleset``. Returns status ERROR, never a pass, if the tool is missing, times out or prints unparsable output."""
        rec = SpectralRecord(args=[])
        self.last = rec
        try:
            with tempfile.TemporaryDirectory(prefix="agip-spectral-") as tmp:
                if isinstance(app, (str, Path)) and Path(app).is_file():
                    target = Path(app)
                else:
                    target = Path(tmp) / "app.json"
                    target.write_text(
                        app if isinstance(app, str) else json.dumps(app), encoding="utf-8"
                    )
                rec.version = self._version(tmp)
                rec.args = [
                    self.spectral_bin, "lint", "-r", str(ruleset), "-f", "json", str(target),
                ]
                start = time.monotonic()
                try:
                    code, out, err = self._run(rec.args, self.timeout_s, tmp)
                except FileNotFoundError:
                    return self._error(rec, "spectral executable not found")
                except subprocess.TimeoutExpired:
                    rec.duration_s = time.monotonic() - start
                    return self._error(rec, f"spectral timed out after {self.timeout_s}s")
                rec.duration_s = time.monotonic() - start
                rec.exit_code, rec.raw_stdout, rec.raw_stderr = code, out or "", err or ""
                return self._parse(rec)
        except Exception as exc:  # never raise
            return self._error(rec, f"spectral adapter failure: {exc!r}")

    def _parse(self, rec: SpectralRecord) -> SpectralRun:
        """Parse the JSON findings from ``rec.raw_stdout`` into a SpectralRun; the exit code is ignored."""
        try:
            # Spectral can append a plain-text line after the JSON on stdout (spike 1.2): decode the first value only.
            text = rec.raw_stdout or ""
            start = text.find("[")
            if start < 0:
                raise ValueError("no JSON array")
            data, _ = json.JSONDecoder().raw_decode(text[start:])
        except (ValueError, TypeError):
            return self._error(rec, f"unparsable spectral output (exit {rec.exit_code})")
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            return self._error(rec, "unexpected spectral JSON shape (expected list of objects)")
        rec.parsed = data
        results = []
        for r in data:
            path = r.get("path", [])
            results.append(
                SpectralResult(
                    code=str(r.get("code", "")),
                    message=str(r.get("message", "")),
                    path=list(path) if isinstance(path, list) else [path],
                    severity=r.get("severity") if isinstance(r.get("severity"), int) else None,
                )
            )
        return SpectralRun(status="OK", results=results, version=rec.version)

    @staticmethod
    def _error(rec: SpectralRecord, msg: str) -> SpectralRun:
        """Build an ERROR run with no results, keeping the tool version from ``rec``."""
        return SpectralRun(status="ERROR", results=[], version=rec.version, error=msg)
