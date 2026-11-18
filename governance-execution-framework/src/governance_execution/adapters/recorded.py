"""Record and replay CLI runs (calm, spectral) so golden tests run without the tools (Req 26.9).

A runner has the adapter signature ``runner(args, timeout_s, cwd) -> (rc, stdout, stderr)``. The key is the
SHA-256 of the sub-command and the *contents* of every file argument (temp paths differ per run). For
``calm generate`` the ``-o`` output file content is recorded and re-written on replay.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from agip_shared.hashing import canonical_hash

Runner = Callable[[List[str], float, str], Tuple[int, str, str]]


class RecordingMissing(LookupError):
    """Raised by ReplayRunner when no recording exists for the requested CLI call."""
    pass


def _key(args: List[str]) -> tuple[str, Optional[Path]]:
    """Return (recording key, ``-o`` output path). File arguments are hashed by content so temp paths do not change the key; ``-o`` and its value are excluded."""
    tool = Path(args[0]).name.lower().split(".")[0]
    parts: list[str] = [tool]
    out: Optional[Path] = None
    skip_next = False
    for i, a in enumerate(args[1:], start=1):
        if skip_next:
            skip_next = False
            continue
        if a == "-o" and i + 1 < len(args):
            out = Path(args[i + 1])
            skip_next = True
            continue
        p = Path(a)
        parts.append("file:" + canonical_hash(p.read_text(encoding="utf-8")) if len(a) < 1024 and p.is_file() else a)
    return canonical_hash(parts), out


class RecordingRunner:
    """Runner wrapper that executes the real command and saves its result under ``root`` as ``<key>.json``."""
    def __init__(self, inner: Runner, root: str | Path):
        """``inner`` is the runner that actually executes the command."""
        self.inner, self.root = inner, Path(root)

    def __call__(self, args: List[str], timeout_s: float, cwd: str) -> Tuple[int, str, str]:
        """Run the command via ``inner`` and record rc, stdout, stderr (tail 2000 chars) and any ``-o`` file content."""
        key, out = _key(args)
        rc, so, se = self.inner(args, timeout_s, cwd)
        rec = {"args0": Path(args[0]).name, "sub": args[1] if len(args) > 1 else "", "rc": rc, "stdout": so, "stderr": se[-2000:],
               "output": out.read_text(encoding="utf-8") if out and out.is_file() else None}
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / f"{key}.json").write_text(json.dumps(rec, indent=1, sort_keys=True), encoding="utf-8")
        return rc, so, se


class ReplayRunner:
    """Runner that answers from recordings in ``root`` without running any tool."""
    def __init__(self, root: str | Path):
        """``root`` is the directory holding the recorded ``<key>.json`` files."""
        self.root = Path(root)

    def __call__(self, args: List[str], timeout_s: float, cwd: str) -> Tuple[int, str, str]:
        """Return the recorded (rc, stdout, stderr), re-writing the recorded ``-o`` file if any. Raises RecordingMissing if absent."""
        key, out = _key(args)
        f = self.root / f"{key}.json"
        if not f.is_file():
            raise RecordingMissing(f"no CLI recording {f.name} for {' '.join(Path(a).name for a in args[:2])}")
        rec = json.loads(f.read_text(encoding="utf-8"))
        if out is not None and rec.get("output") is not None:
            out.write_text(rec["output"], encoding="utf-8")
        return rec["rc"], rec["stdout"], rec["stderr"]
