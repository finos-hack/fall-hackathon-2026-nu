"""Compile catalogs into Spectral rulesets (Req 6).

Only APPROVED items are compiled. Output is deterministic: rules sorted by Rule_Code with core-function
rules first, fixed key order inside each rule, sorted ``functionOptions``. A rule that cannot be expressed
is reported by Rule_Code and never dropped silently.

CLI: ``python -m rule_authoring.compile [--catalogs DIR] [--out DIR] [--strict]``
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

from agip_shared import versioned_write as vw
from agip_shared.hashing import sha256_hex

from . import consistency, knowledge
from .paths import FRAMEWORK_ROOT

_VERSION_LINE = re.compile(r"^# version: .*\n", re.M)
_VERSION_NUM = re.compile(r"^# version: (\d+)", re.M)

CORE_FUNCTIONS = {"truthy", "falsy", "defined", "undefined", "pattern", "enumeration", "schema", "length",
                  "alphabetical", "casing", "xor"}
RULE_KEYS = ("description", "message", "severity", "given", "then")
SEVERITIES = {"error", "warn", "info", "hint"}
CATALOG_DIR = FRAMEWORK_ROOT / "catalogs"
RULESET_DIR = FRAMEWORK_ROOT / "rulesets"
CUSTOM_FUNCTIONS_FILE = "custom_functions.yaml"   # in rulesets/functions/: {name: {reason: "..."}}


@dataclass(frozen=True)
class Unexpressible:
    """An approved rule that cannot be compiled to Spectral, with the reason."""
    rule_code: str
    item_id: str
    reason: str

    def __str__(self) -> str:
        """One-line report form."""
        return f"UNEXPRESSIBLE {self.rule_code} ({self.item_id}): {self.reason}"


@dataclass(frozen=True)
class Compiled:
    """Result of compiling one catalog kind: ruleset text, its hash and version, included rule codes, and what was skipped or could not be expressed."""
    text: str
    sha256: str
    version: int
    rule_codes: tuple[str, ...]
    skipped_unapproved: tuple[str, ...]
    unexpressible: tuple[Unexpressible, ...]
    custom_functions: tuple[str, ...]
    non_executable: tuple[str, ...] = ()   # APPROVED but stored-only types: never compiled, reported in coverage


def _item_id(item: dict[str, Any]) -> str:
    """Catalog item id (control_id, risk_id or id), or '?' if none."""
    return str(next((item[k] for k in ("control_id", "risk_id", "id") if k in item), "?"))


def _then_list(rule: dict[str, Any]) -> list[dict[str, Any]]:
    """The rule's `then` clause as a list (single dict is wrapped; anything else gives [])."""
    t = rule.get("then")
    return t if isinstance(t, list) else [t] if isinstance(t, dict) else []


def _problem(rule: Any, custom: dict[str, Any]) -> Optional[str]:
    """Reason the rule cannot be emitted (missing body, bad JSONPath, bad severity, missing or unknown function), or None if it is valid."""
    if not isinstance(rule, dict):
        return "rule body missing"
    given = rule.get("given")
    if not isinstance(given, str) or not given.startswith("$"):
        return "given must be a JSONPath starting with $"
    if rule.get("severity") not in SEVERITIES:
        return f"severity must be one of {sorted(SEVERITIES)}"
    thens = _then_list(rule)
    if not thens:
        return "then is missing"
    for t in thens:
        fn = t.get("function")
        if fn not in CORE_FUNCTIONS and fn not in custom:
            return f"function '{fn}' is neither a Spectral core function nor a declared custom function"
    return None


def _uses_custom(rule: dict[str, Any]) -> bool:
    """True if any `then` step calls a function outside Spectral's core set."""
    return any(t.get("function") not in CORE_FUNCTIONS for t in _then_list(rule))


def _ordered_rule(rule: dict[str, Any]) -> dict[str, Any]:
    """Copy of the rule limited to known keys in canonical order so output is stable; `then` steps keep only field/function/functionOptions."""
    out: dict[str, Any] = {}
    for k in RULE_KEYS:
        if k not in rule:
            continue
        if k == "then":
            thens = []
            for t in _then_list(rule):
                o = {kk: t[kk] for kk in ("field", "function", "functionOptions") if kk in t}
                thens.append(o)
            out[k] = thens[0] if len(thens) == 1 else thens
        else:
            out[k] = rule[k]
    return out


def load_custom_functions(functions_dir: Path = RULESET_DIR / "functions") -> dict[str, Any]:
    """Custom function definitions from the functions directory, or {} if the file is absent."""
    f = functions_dir / CUSTOM_FUNCTIONS_FILE
    return (yaml.safe_load(f.read_text(encoding="utf-8")) or {}) if f.is_file() else {}


def compile_catalog(catalog: dict[str, Any], name: str, custom: Optional[dict[str, Any]] = None,
                    ruleset_version: Optional[int] = None) -> Compiled:
    """``ruleset_version`` (header ``# version:``) defaults to the catalog version; compile_all bumps it by content hash."""
    custom = custom or {}
    version = int(catalog.get("version", 1))
    rules: dict[str, dict[str, Any]] = {}
    skipped: list[str] = []
    stored_only: list[str] = []
    bad: list[Unexpressible] = []
    for item in catalog.get("items") or []:
        iid = _item_id(item)
        if item.get("status") != "APPROVED":
            prev = item.get("previous_approved")   # a revision under review: the last approved version stays in force
            if not (isinstance(prev, dict) and prev.get("status") == "APPROVED"):
                skipped.append(iid)
                continue
            item = prev
        if not knowledge.is_executable(item):
            stored_only.append(iid)
            continue
        defined = item.get("spectral_rules") or {}
        referenced = list(item.get("rule_codes") or [])
        for cfg in item.get("configurations") or []:
            referenced += cfg.get("rule_codes") or []
        for code in sorted(set(referenced) | set(defined)):
            reason = "no spectral rule defined for this Rule_Code" if code not in defined else _problem(defined[code], custom)
            if reason:
                bad.append(Unexpressible(code, iid, reason))
            else:
                rules[code] = defined[code]
    ordered = sorted(rules, key=lambda c: (_uses_custom(rules[c]), c))   # core functions first
    used_custom = sorted({t["function"] for c in ordered for t in _then_list(rules[c]) if t["function"] not in CORE_FUNCTIONS})
    body: dict[str, Any] = {}
    if used_custom:
        body["functions"] = used_custom
        body["functionsDir"] = "./functions"
    body["rules"] = {c: _ordered_rule(rules[c]) for c in ordered}
    body_text = yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=1000)
    # The file SHA-256 lives in rulesets/MANIFEST.yaml, not in the header: recorded Spectral runs are keyed by ruleset bytes.
    header = [f"# {name} ruleset", f"# version: {ruleset_version or version}",
              f"# source catalog: {catalog.get('catalog', name)} v{version}",
              f"# rules: {len(ordered)} (APPROVED only)", "# generated by rule_authoring.compile; do not edit"]
    if used_custom:
        header += [f"# custom function {fn}: {custom[fn].get('reason', 'no reason recorded')}" for fn in used_custom]
    else:
        header.append("# custom functions: none (core functions only)")
    text = "\n".join(header) + "\n" + body_text
    return Compiled(text, sha256_hex(text), ruleset_version or version, tuple(ordered), tuple(skipped), tuple(bad),
                    tuple(used_custom), tuple(stored_only))


def ruleset_info(path: str | Path) -> dict[str, Any]:
    """Version and SHA-256 of a ruleset file, for the per-assessment versions record (Req 6.6)."""
    p = Path(path)
    data = p.read_bytes()
    first = next((l for l in data.decode("utf-8").splitlines() if l.startswith("# version:")), "# version: ?")
    return {"file": p.name, "version": first.split(":", 1)[1].strip(), "sha256": sha256_hex(data)}


def _set_catalog_version(path: Path, version: int) -> None:
    """Set the catalog's top-level ``version:`` in place (keeps the comment header and layout)."""
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(r"(?m)^version:\s*\d+\s*$", f"version: {version}", text, count=1)
    path.write_text(new if n else f"version: {version}\n{text}", encoding="utf-8")


def compile_all(catalog_dir: Path = CATALOG_DIR, out_dir: Path = RULESET_DIR) -> dict[str, Compiled]:
    """Check consistency, compile both catalogs, write rulesets. Raises ValueError on consistency errors.

    Hash rule: unchanged rules leave the ruleset bytes as they are; changed rules raise the catalog's top-level
    version (written in place), which is the ruleset version."""
    paths = [catalog_dir / "controls.catalog.yaml", catalog_dir / "risks.catalog.yaml"]
    docs = consistency.load_catalogs(paths)
    errors = consistency.check(docs)
    if errors:
        raise ValueError("catalogs are inconsistent: " + "; ".join(str(e) for e in errors))
    custom = load_custom_functions(out_dir / "functions")
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Compiled] = {}
    for p in paths:
        kind = p.name.split(".")[0]
        c = compile_catalog(docs[p.name], kind, custom)
        out = out_dir / f"{kind}.spectral.yaml"
        ch = vw.hash_content(_VERSION_LINE.sub("", c.text))      # content without the ruleset's own version
        prev = out.read_text(encoding="utf-8") if out.is_file() else None
        if prev is not None and vw.hash_content(_VERSION_LINE.sub("", prev)) != ch:
            m = _VERSION_NUM.search(prev)
            prev_v = int(m.group(1)) if m else 0
            if c.version <= prev_v:                              # rules changed: catalog (and ruleset) version + 1
                new_v = prev_v + 1
                _set_catalog_version(p, new_v)
                docs[p.name]["version"] = new_v
                c = compile_catalog(docs[p.name], kind, custom)
        vw.write(out, c.text, content_hash=ch, version=c.version)   # unchanged rules: same bytes, no rewrite
        result[kind] = c
    manifest = {"generated_by": "rule_authoring.compile",
                "rulesets": {f"{k}.spectral.yaml": {"version": c.version, "sha256": c.sha256, "rules": len(c.rule_codes)}
                             for k, c in sorted(result.items())}}
    mtext = yaml.safe_dump(manifest, sort_keys=True)
    mpath, mh = out_dir / "MANIFEST.yaml", vw.hash_content(mtext)
    vw.write(mpath, mtext, content_hash=mh, version=vw.version_for(mpath, mh))
    return result


def main(argv: Optional[list[str]] = None) -> int:
    """CLI: compile approved catalog rules to Spectral rulesets. Returns 1 on a ValueError, or with --strict when any rule is inexpressible."""
    ap = argparse.ArgumentParser(prog="rule_authoring.compile")
    ap.add_argument("--catalogs", type=Path, default=CATALOG_DIR)
    ap.add_argument("--out", type=Path, default=RULESET_DIR)
    ap.add_argument("--strict", action="store_true", help="exit 1 when any rule is inexpressible")
    args = ap.parse_args(argv)
    try:
        result = compile_all(args.catalogs, args.out)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    bad = 0
    for kind, c in sorted(result.items()):
        print(f"{kind}.spectral.yaml v{c.version} sha256={c.sha256[:12]} rules={len(c.rule_codes)} "
              f"skipped_unapproved={len(c.skipped_unapproved)}")
        for u in c.unexpressible:
            print(u, file=sys.stderr)
            bad += 1
    return 1 if (bad and args.strict) else 0


if __name__ == "__main__":
    raise SystemExit(main())

