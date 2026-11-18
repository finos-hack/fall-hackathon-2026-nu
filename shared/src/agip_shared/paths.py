"""Safe path resolution within a data directory."""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath


class PathEscapeError(ValueError):
    """Raised when a path would resolve outside the data directory."""


def resolve_within(data_dir: str | Path, p: str | Path) -> Path:
    """Resolve ``p`` under ``data_dir``; reject absolute paths, ``..``, and symlink escapes."""
    raw = str(p)
    if not raw or "\x00" in raw:
        raise PathEscapeError("invalid path")
    win, posix = PureWindowsPath(raw), PurePosixPath(raw)
    if win.is_absolute() or posix.is_absolute() or win.drive or win.root or raw.startswith(("/", "\\")):
        raise PathEscapeError(f"absolute path not allowed: {raw}")
    if ".." in win.parts or ".." in posix.parts:
        raise PathEscapeError(f"'..' not allowed: {raw}")
    base = Path(data_dir).resolve()
    target = (base / raw).resolve()  # follows symlinks
    if not target.is_relative_to(base):
        raise PathEscapeError(f"path escapes data dir: {raw}")
    return target
