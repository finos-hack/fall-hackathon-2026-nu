"""Minimal subprocess wrapper for the ``calm`` CLI, used only by the standalone ``calm_generation`` CLI."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


class CalmUnavailable(Exception):
    """Raised when the ``calm`` executable cannot be located."""
    pass


@dataclass
class Gen:
    """Result of ``calm generate``: ``status`` is OK (``model`` set) or ERROR (``error`` set)."""
    status: str
    model: Optional[dict[str, Any]] = None
    version: Optional[str] = None
    error: Optional[str] = None


@dataclass
class Val:
    """Result of ``calm validate``: ``status`` is VALID, INVALID or ERROR; ``errors`` are :class:`Err` items."""
    status: str
    errors: list[Any] = field(default_factory=list)
    warnings: list[Any] = field(default_factory=list)
    version: Optional[str] = None
    exit_code: int = 0
    error: Optional[str] = None


@dataclass
class Err:
    """One error-severity finding from ``calm validate`` output."""
    code: str
    path: str
    message: str


def find_calm() -> str:
    """Locate the CLI via ``CALM_BIN`` or ``PATH``. Raises CalmUnavailable when neither is set."""
    exe = os.environ.get("CALM_BIN") or shutil.which("calm")
    if not exe:
        raise CalmUnavailable("the 'calm' CLI was not found; install @finos/calm-cli or set CALM_BIN")
    return exe


def _run(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    """Run the CLI in ``cwd`` capturing UTF-8 output, with a 120 s timeout (raises ``subprocess.TimeoutExpired``)."""
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=120)


class RealCalm:
    """Thin adapter over the real ``calm`` CLI exposing ``generate`` and ``validate`` with in-memory dict inputs."""
    def __init__(self, exe: Optional[str] = None):
        """Use ``exe`` if given, otherwise discover it with :func:`find_calm` (may raise CalmUnavailable)."""
        self.exe = exe or find_calm()

    def generate(self, template: dict[str, Any], choices: dict[str, Any]) -> Gen:
        """Run ``calm generate`` on ``template`` with the option ``choices`` in a temp dir; ERROR result on non-zero exit or unreadable output."""
        with tempfile.TemporaryDirectory(prefix="calm-gen-") as tmp:
            t = Path(tmp)
            # Fixed file names in a throw-away dir: the CLI is run with that dir as cwd and relative paths.
            (t / "p.json").write_text(json.dumps(template), encoding="utf-8")
            (t / "c.json").write_text(json.dumps(choices), encoding="utf-8")
            r = _run([self.exe, "generate", "-p", "p.json", "--option-choices", "c.json", "-o", "out.json"], tmp)
            if r.returncode != 0:
                return Gen("ERROR", error=f"calm generate failed (exit {r.returncode}): {(r.stderr or '').strip()[-300:]}")
            try:
                return Gen("OK", json.loads((t / "out.json").read_text(encoding="utf-8")))
            except (OSError, ValueError):
                return Gen("ERROR", error="calm generate produced no parsable output")

    def validate(self, arch: dict[str, Any], pattern: Optional[dict[str, Any]] = None) -> Val:
        """Run ``calm validate`` on ``arch`` (against ``pattern`` when given) and collect error-severity findings from JSON and Spectral outputs."""
        with tempfile.TemporaryDirectory(prefix="calm-val-") as tmp:
            t = Path(tmp)
            (t / "a.json").write_text(json.dumps(arch), encoding="utf-8")
            args = [self.exe, "validate"]
            if pattern is not None:
                (t / "p.json").write_text(json.dumps(pattern), encoding="utf-8")
                args += ["-p", "p.json"]
            args += ["-a", "a.json", "-f", "json"]
            r = _run(args, tmp)
            try:
                doc = json.loads(r.stdout)
            except ValueError:
                return Val("ERROR", exit_code=r.returncode, error=(r.stderr or r.stdout or "no output").strip()[-300:])
            found = [i for k in ("jsonSchemaValidationOutputs", "spectralSchemaValidationOutputs")
                     for i in doc.get(k, []) or []]
            errors = [Err(str(i.get("code", "")), str(i.get("path", "")), str(i.get("message", "")))
                      for i in found if i.get("severity") in (0, "error")]
            return Val("INVALID" if errors or r.returncode != 0 else "VALID", errors, exit_code=r.returncode)
