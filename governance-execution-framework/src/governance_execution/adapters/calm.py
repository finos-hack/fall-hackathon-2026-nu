"""CALM_Adapter: the only component that invokes the official `calm` CLI.

Flags and output shapes follow docs/spike/1.1-calm.md (CLI 1.60.1):
  calm generate -p <pattern> --option-choices <file> -o <out>   (stdout empty, log on stderr)
  calm validate [-p <pattern>] -a <arch> -f json                (stdout JSON; stderr is logs only)
Validity is `hasErrors == false`, never the exit code. Missing CLI, timeout, or unparsable
output yields ERROR (never VALID). Arguments are lists (no shell), files live in a temp
directory, and a timeout is enforced. Public methods never raise.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

# runner(args, timeout_s, cwd) -> (returncode, stdout, stderr)
Runner = Callable[[List[str], float, str], Tuple[int, str, str]]

VALID = "VALID"
INVALID = "INVALID"
ERROR = "ERROR"


def default_runner(args: List[str], timeout_s: float, cwd: str) -> Tuple[int, str, str]:
    """Run a command with list args (no shell). May raise FileNotFoundError/TimeoutExpired."""
    exe = shutil.which(args[0]) or args[0]  # resolves .cmd shims on Windows
    p = subprocess.run(
        [exe, *args[1:]], capture_output=True, text=True, timeout=timeout_s, cwd=cwd, shell=False,
        stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace",
    )
    return p.returncode, p.stdout, p.stderr


@dataclass
class CalmFinding:
    """One validation finding (error or warning) from ``calm validate`` JSON output."""
    code: str
    severity: str
    message: str
    path: str


@dataclass
class CalmRecord:
    """Evidence of the last CLI call."""
    args: List[str] = field(default_factory=list)
    exit_code: Optional[int] = None
    duration_s: float = 0.0
    version: Optional[str] = None
    raw_stdout: str = ""
    raw_stderr: str = ""


@dataclass
class CalmValidation:
    """Outcome of a validate call: ``status`` is VALID, INVALID or ERROR (``error`` is set only for ERROR)."""
    status: str  # VALID | INVALID | ERROR
    errors: List[CalmFinding] = field(default_factory=list)
    warnings: List[CalmFinding] = field(default_factory=list)
    version: Optional[str] = None
    exit_code: Optional[int] = None
    duration_s: float = 0.0
    error: Optional[str] = None


@dataclass
class CalmGeneration:
    """Outcome of ``calm generate``: OK with the parsed ``model``, or ERROR with ``error`` set."""
    status: str  # OK | ERROR
    model: Optional[Dict[str, Any]] = None
    version: Optional[str] = None
    exit_code: Optional[int] = None
    duration_s: float = 0.0
    error: Optional[str] = None


def _dump(obj: Union[Dict[str, Any], str]) -> str:
    """Serialise a dict to JSON text; a string is assumed to be JSON already and passes through."""
    return obj if isinstance(obj, str) else json.dumps(obj)


class CalmAdapter:
    """Wrapper around the ``calm`` CLI. Public methods return result objects and never raise; ``last`` holds the latest call's evidence."""
    def __init__(
        self,
        calm_bin: str = "calm",
        timeout_s: float = 60,
        runner: Optional[Runner] = None,
    ) -> None:
        """``runner`` replaces the subprocess runner (used by tests and recordings)."""
        self.calm_bin = calm_bin
        self.timeout_s = timeout_s
        self._run = runner or default_runner
        self.last: Optional[CalmRecord] = None

    def _version(self, cwd: str) -> Optional[str]:
        """Return the CLI version string, or None if the call fails or prints nothing."""
        try:
            code, out, _ = self._run([self.calm_bin, "--version"], self.timeout_s, cwd)
            v = (out or "").strip()
            return v if code == 0 and v else None
        except Exception:
            return None

    def _exec(self, rec: CalmRecord, args: List[str], cwd: str) -> Optional[str]:
        """Run args, filling rec. Returns an error message, or None on completed run."""
        rec.args = args
        start = time.monotonic()
        try:
            code, out, err = self._run(args, self.timeout_s, cwd)
        except FileNotFoundError:
            return "calm executable not found"
        except subprocess.TimeoutExpired:
            rec.duration_s = time.monotonic() - start
            return f"calm timed out after {self.timeout_s}s"
        rec.duration_s = time.monotonic() - start
        rec.exit_code, rec.raw_stdout, rec.raw_stderr = code, out or "", err or ""
        return None

    # ---- generate -------------------------------------------------------------------
    def generate(
        self,
        pattern: Union[Dict[str, Any], str, Path],
        option_choices: Optional[Dict[str, Any]] = None,
    ) -> CalmGeneration:
        """Run ``calm generate`` for a pattern (dict, JSON text or path) and optional option choices. Returns ERROR on any failure."""
        rec = CalmRecord()
        self.last = rec
        try:
            with tempfile.TemporaryDirectory(prefix="agip-calm-") as tmp:
                t = Path(tmp)
                pat = self._materialize(pattern, t / "pattern.json")
                choices = t / "choices.json"
                choices.write_text(json.dumps(option_choices or {}), encoding="utf-8")
                out = t / "out.json"
                rec.version = self._version(tmp)
                args = [
                    self.calm_bin, "generate", "-p", str(pat),
                    "--option-choices", str(choices), "-o", str(out),
                ]
                msg = self._exec(rec, args, tmp)
                if msg:
                    return self._gen_err(rec, msg)
                if rec.exit_code != 0:
                    return self._gen_err(rec, f"calm generate failed (exit {rec.exit_code})")
                try:
                    model = json.loads(out.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    return self._gen_err(rec, "calm generate produced no parsable output")
                if not isinstance(model, dict):
                    return self._gen_err(rec, "calm generate output is not a JSON object")
                return CalmGeneration(
                    "OK", model, rec.version, rec.exit_code, rec.duration_s
                )
        except Exception as exc:  # never raise
            return self._gen_err(rec, f"calm adapter failure: {exc!r}")

    # ---- validate -------------------------------------------------------------------
    def validate(
        self,
        arch: Union[Dict[str, Any], str, Path],
        pattern: Optional[Union[Dict[str, Any], str, Path]] = None,
    ) -> CalmValidation:
        """Validate an architecture, optionally against a pattern. Validity comes from ``hasErrors`` in the JSON, not the exit code."""
        rec = CalmRecord()
        self.last = rec
        try:
            with tempfile.TemporaryDirectory(prefix="agip-calm-") as tmp:
                t = Path(tmp)
                arch_f = self._materialize(arch, t / "arch.json")
                args = [self.calm_bin, "validate"]
                if pattern is not None:
                    args += ["-p", str(self._materialize(pattern, t / "pattern.json"))]
                args += ["-a", str(arch_f), "-f", "json"]
                rec.version = self._version(tmp)
                msg = self._exec(rec, args, tmp)
                if msg:
                    return self._val_err(rec, msg)
                return self._parse(rec)
        except Exception as exc:  # never raise
            return self._val_err(rec, f"calm adapter failure: {exc!r}")

    def validate_pattern(self, pattern: Union[Dict[str, Any], str, Path]) -> CalmValidation:
        """``calm validate -p <pattern> -f json`` (pattern only, Req 7.7)."""
        rec = CalmRecord()
        self.last = rec
        try:
            with tempfile.TemporaryDirectory(prefix="agip-calm-") as tmp:
                pat = self._materialize(pattern, Path(tmp) / "pattern.json")
                rec.version = self._version(tmp)
                msg = self._exec(rec, [self.calm_bin, "validate", "-p", str(pat), "-f", "json"], tmp)
                return self._val_err(rec, msg) if msg else self._parse(rec)
        except Exception as exc:  # never raise
            return self._val_err(rec, f"calm adapter failure: {exc!r}")

    # ---- helpers --------------------------------------------------------------------
    @staticmethod
    def _materialize(obj: Union[Dict[str, Any], str, Path], dest: Path) -> Path:
        """Return a file path for ``obj``: an existing file path is used as is, anything else is written to ``dest``."""
        if isinstance(obj, Path) or (isinstance(obj, str) and len(obj) < 1024 and Path(obj).is_file()):
            return Path(obj)
        dest.write_text(_dump(obj), encoding="utf-8")  # type: ignore[arg-type]
        return dest

    def _parse(self, rec: CalmRecord) -> CalmValidation:
        """Turn the recorded stdout into a CalmValidation; ERROR if the JSON is missing, malformed or lacks a boolean ``hasErrors``."""
        try:
            data = json.loads(rec.raw_stdout)
        except (ValueError, TypeError):
            return self._val_err(rec, f"unparsable calm output (exit {rec.exit_code})")
        if not isinstance(data, dict) or not isinstance(data.get("hasErrors"), bool):
            return self._val_err(rec, "unexpected calm JSON shape (missing boolean hasErrors)")
        findings: List[Dict[str, Any]] = []
        for key in ("jsonSchemaValidationOutputs", "spectralSchemaValidationOutputs"):
            items = data.get(key) or []
            if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
                return self._val_err(rec, f"unexpected calm JSON shape ({key})")
            findings.extend(items)
        errors: List[CalmFinding] = []
        warnings: List[CalmFinding] = []
        for f in findings:
            item = CalmFinding(
                code=str(f.get("code", "")),
                severity=str(f.get("severity", "")),
                message=str(f.get("message", "")),
                path=str(f.get("path", "")),
            )
            (errors if item.severity == "error" else warnings).append(item)
        status = INVALID if data["hasErrors"] else VALID
        return CalmValidation(
            status, errors, warnings, rec.version, rec.exit_code, rec.duration_s
        )

    @staticmethod
    def _val_err(rec: CalmRecord, msg: str) -> CalmValidation:
        """Build an ERROR validation result carrying the evidence in ``rec``."""
        return CalmValidation(
            ERROR, version=rec.version, exit_code=rec.exit_code,
            duration_s=rec.duration_s, error=msg,
        )

    @staticmethod
    def _gen_err(rec: CalmRecord, msg: str) -> CalmGeneration:
        """Build an ERROR generation result carrying the evidence in ``rec``."""
        return CalmGeneration(
            "ERROR", version=rec.version, exit_code=rec.exit_code,
            duration_s=rec.duration_s, error=msg,
        )
