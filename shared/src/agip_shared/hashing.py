"""Canonical JSON and SHA-256 hashing helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(obj: Any) -> str:
    """Serialize with sorted keys and no whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(data: bytes | str) -> str:
    """Hex SHA-256 of bytes, or of a string encoded as UTF-8."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def canonical_hash(obj: Any) -> str:
    """SHA-256 of the canonical JSON form of obj, so equal data hashes equally regardless of key order."""
    return sha256_hex(canonical_json(obj))


def input_hash(model: str, state: Any, questions: Any) -> str:
    """SHA-256 of canonical JSON of model name, state, and questions."""
    return canonical_hash({"model": model, "state": state, "questions": questions})
