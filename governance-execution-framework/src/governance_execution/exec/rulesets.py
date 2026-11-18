"""Ruleset file helpers for the execution path. Reads the compiled rulesets as plain files, so a governance
run never imports ``rule_authoring`` (the standalone CLI must work without the authoring package loaded)."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any, Optional

from agip_shared.hashing import sha256_hex

RULESET_DIR = Path(__file__).resolve().parents[4] / "rule-authoring-framework" / "rulesets"


def ruleset_info(path: str | Path) -> dict[str, Any]:
    """Version and SHA-256 of a ruleset file (same shape as ``rule_authoring.compile.ruleset_info``)."""
    p = Path(path)
    data = p.read_bytes()
    first = next((l for l in data.decode("utf-8").splitlines() if l.startswith("# version:")), "# version: ?")
    return {"file": p.name, "version": first.split(":", 1)[1].strip(), "sha256": sha256_hex(data)}


def extraction_prompt_version() -> Optional[str]:
    """PROMPT_VERSION of the rule extraction prompt, read from source text without importing the package."""
    try:
        spec = importlib.util.find_spec("rule_authoring")   # top-level lookup does not import the package
        if spec is None or not spec.submodule_search_locations:
            return None
        text = (Path(next(iter(spec.submodule_search_locations))) / "extraction.py").read_text(encoding="utf-8")
        m = re.search(r'^PROMPT_VERSION\s*=\s*"([^"]+)"', text, re.M)
        return m.group(1) if m else None
    except Exception:  # noqa: BLE001
        return None
