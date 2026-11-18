"""Pattern and RA_Template lifecycle (Req 7, 8): registry file, shape validation, transition gate.

State lives in ``registry/lifecycle.yaml`` so pattern and template bytes (and therefore golden hashes) never change.
Transitions use the shared ``PATTERN_TRANSITIONS`` table. Every transition records reviewer, role, rationale and time.
Only APPROVED or PUBLISHED patterns that pass shape validation may be composed.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from agip_shared.contracts import PATTERN_TRANSITIONS, InvalidTransition, check_transition
from agip_shared.hashing import sha256_hex

from . import pattern_library as pl

FRAMEWORK_ROOT = pl.FRAMEWORK_ROOT
REGISTRY = FRAMEWORK_ROOT / "registry" / "lifecycle.yaml"
CATALOGS = FRAMEWORK_ROOT.parent / "rule-authoring-framework" / "catalogs"
CALM_SCHEMA = "https://calm.finos.org/release/1.2/meta/calm.json"
COMPOSABLE = {"APPROVED", "PUBLISHED"}
VENDOR_WORDS = ["aws", "azure", "gcp", "bedrock", "openai", "claude", "kafka", "postgres", "mysql", "oracle", "kong",
                "apigee", "stripe", "mongodb", "redis", "lambda", "kubernetes"]


class NotComposable(Exception):
    """Raised when a selected pattern is not APPROVED/PUBLISHED, has no file, or fails shape validation."""
    pass


class PatternInvalid(Exception):
    """Raised when a pattern fails static shape validation; ``errors`` holds the individual messages."""
    def __init__(self, pid: str, errors: list[str]):
        """Keep the error list and build a combined message."""
        self.errors = errors
        super().__init__(f"{pid} is invalid: " + "; ".join(errors))


def now() -> str:
    """Current UTC time as ``YYYY-MM-DDTHH:MM:SSZ``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path: Path = REGISTRY) -> dict[str, Any]:
    """Read the lifecycle registry YAML; an empty file gives ``{'entries': {}}``."""
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {"entries": {}}


def save(reg: dict[str, Any], path: Path = REGISTRY) -> None:
    """Write the registry (creating parent dirs) with sorted keys for stable diffs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(reg, sort_keys=True, allow_unicode=True), encoding="utf-8")


def _catalog_ids(catalogs: Path) -> tuple[set[str], set[str]]:
    """Return ``(control ids, risk ids)`` from the rule-authoring catalogs."""
    c = yaml.safe_load((catalogs / "controls.catalog.yaml").read_text(encoding="utf-8"))["items"]
    r = yaml.safe_load((catalogs / "risks.catalog.yaml").read_text(encoding="utf-8"))["items"]
    return {i["control_id"] for i in c}, {i["risk_id"] for i in r}


def validate_pattern_shape(pattern: dict[str, Any], entry: Optional[dict[str, Any]] = None,
                           catalogs: Path = CATALOGS) -> list[str]:
    """Static checks (no CLI): CALM 1.2 shape, relationship endpoints, catalog IDs, neutrality, source+version."""
    errs: list[str] = []
    if pattern.get("$schema") != CALM_SCHEMA:
        errs.append(f"$schema must be {CALM_SCHEMA}")
    props = pattern.get("properties") or {}
    nodes = (props.get("nodes") or {}).get("prefixItems")
    rels = (props.get("relationships") or {}).get("prefixItems")
    if not isinstance(nodes, list) or not isinstance(rels, list):
        return errs + ["properties.nodes and properties.relationships need prefixItems"]
    ids = {(n.get("properties") or {}).get("unique-id", {}).get("const") for n in nodes}
    for r in rels:
        rp = r.get("properties") or {}
        rid = (rp.get("unique-id") or {}).get("const", "?")
        c = ((rp.get("relationship-type") or {}).get("const") or {}).get("connects")
        for end in ("source", "destination"):
            n = ((c or {}).get(end) or {}).get("node")
            if c is not None and n not in ids:
                errs.append(f"relationship {rid} {end} references unknown node {n!r}")
    md = pattern.get("metadata") or {}
    if not md.get("pattern-id"):
        errs.append("metadata.pattern-id missing")
    if not isinstance(md.get("version"), int):
        errs.append("metadata.version must be an integer")
    controls, risks = _catalog_ids(catalogs)
    errs += [f"unknown control {c}" for c in md.get("related_controls", []) if c not in controls]
    errs += [f"unknown risk {c}" for c in md.get("related_risks", []) if c not in risks]
    text = json.dumps(pattern).lower()
    errs += [f"names technology {w!r}" for w in VENDOR_WORDS if re.search(rf"\b{w}\b", text)]
    if entry is not None and (not entry.get("source") or entry.get("version") != md.get("version")):
        errs.append("registry source and matching version are required")
    return errs


def entry_of(reg: dict[str, Any], key: str) -> dict[str, Any]:
    """Registry entry for ``key``. Raises KeyError with a readable message when absent."""
    try:
        return reg["entries"][key]
    except KeyError:
        raise KeyError(f"{key} is not in the lifecycle registry") from None


def state_of(key: str, path: Path = REGISTRY) -> str:
    """Current lifecycle state of ``key``."""
    return entry_of(load(path), key)["state"]


def transition(key: str, target: str, *, by: str, role: str, rationale: str, path: Path = REGISTRY,
               patterns: Optional[dict[str, Any]] = None, at: Optional[str] = None) -> dict[str, Any]:
    """Move a pattern or RA one step. Raises InvalidTransition, PatternInvalid or ValueError."""
    for name, v in (("by", by), ("role", role), ("rationale", rationale)):
        if not (v or "").strip():
            raise ValueError(f"{name} is required for a lifecycle transition")
    reg = load(path)
    e = entry_of(reg, key)
    check_transition(PATTERN_TRANSITIONS, e["state"], target)
    if e["kind"] == "pattern" and target in ("APPROVED", "PUBLISHED"):
        p = (patterns or pl.load_patterns())[key]
        errs = validate_pattern_shape(p, e)
        if errs:
            raise PatternInvalid(key, errs)
    # Pattern shape is re-validated only when a pattern becomes composable; other transitions are state changes only.
    e.setdefault("history", []).append({"from": e["state"], "to": target, "by": by.strip(), "role": role.strip(),
                                        "rationale": rationale.strip(), "at": at or now()})
    e["state"] = target
    save(reg, path)
    return e


def composable_patterns(spec: dict[str, Any], patterns: dict[str, Any], path: Path = REGISTRY) -> None:
    """Raise NotComposable unless every selected pattern is APPROVED/PUBLISHED and valid."""
    reg = load(path)
    problems = []
    for pid in spec["patterns"]:
        e = reg["entries"].get(pid)
        if e is None or e["state"] not in COMPOSABLE:
            problems.append(f"{pid} is {e['state'] if e else 'unregistered'}; only APPROVED or PUBLISHED patterns can be composed")
        elif pid not in patterns:
            problems.append(f"{pid} has no pattern file")
        else:
            problems += [f"{pid}: {m}" for m in validate_pattern_shape(patterns[pid], e)]
    if problems:
        raise NotComposable("; ".join(problems))


def record_composition(ra_id: str, version: int, template_text: str, template: dict[str, Any], *,
                       by: str, path: Path = REGISTRY) -> dict[str, Any]:
    """Create the RA entry as DRAFT, or confirm an identical composition. A changed hash needs a new ra-version."""
    reg = load(path)
    sha = sha256_hex(template_text)
    e = reg["entries"].get(ra_id)
    ver = {"version": version, "composed_sha256": sha, "source_patterns": template["metadata"]["source-patterns"]}
    if e is None:
        e = reg["entries"][ra_id] = {"kind": "ra", "state": "DRAFT", "source": "composer", **ver, "versions": [], "history": []}
        e["history"].append({"from": None, "to": "DRAFT", "by": by, "role": "composer", "rationale": "composed", "at": now()})
    elif e["composed_sha256"] != sha or e["version"] != version:
        if e["version"] == version:
            raise ValueError(f"{ra_id} v{version} already recorded with a different hash; bump the version")
        e.update(ver, state="DRAFT")
        e["history"].append({"from": None, "to": "DRAFT", "by": by, "role": "composer", "rationale": f"new version {version}", "at": now()})
    if not any(v["version"] == version for v in e["versions"]):
        e["versions"].append({"version": version, "composed_sha256": sha, "source_patterns": ver["source_patterns"]})
    save(reg, path)
    return e


# ---- shared HumanTask integration (task 24.4) -----------------------------------------------------------------
def published_templates(template_dir: Optional[Path] = None, path: Path = REGISTRY) -> list[dict[str, Any]]:
    """RA templates that can be instantiated (lifecycle PUBLISHED), with id, version, title and description."""
    import json
    tdir = Path(template_dir or pl.FRAMEWORK_ROOT / "templates")
    entries = load(path).get("entries") or {}
    out = []
    for f in sorted(tdir.glob("*.json")):
        t = json.loads(f.read_text(encoding="utf-8"))
        md = t.get("metadata") or {}
        rid = md.get("ra-id") or f.stem
        if (entries.get(rid) or {}).get("state") == "PUBLISHED":
            out.append({"id": rid, "version": md.get("ra-version"), "title": t.get("title") or rid,
                        "description": t.get("description") or ""})
    return out


# ---- shared HumanTask integration (task 24.4) -----------------------------------------------------------------
def request_approval(store: Any, key: str, requested_by: str, path: Path = REGISTRY) -> Any:
    """Create a PATTERN_APPROVAL / RA_APPROVAL task for a registry entry that is IN_REVIEW."""
    from agip_shared.contracts import HumanTask
    kind = entry_of(load(path), key)["kind"]
    ttype = "PATTERN_APPROVAL" if kind == "pattern" else "RA_APPROVAL"
    return store.create(HumanTask(
        task_id=f"{ttype.lower().replace('_', '-')}-{key}", framework="calm_generation", task_type=ttype,
        subject_refs=[f"lifecycle:{key}"], role=store.roles[ttype][0], context={"key": key, "created_by": requested_by}))


def apply_approval(store: Any, task_id: str, path: Path = REGISTRY, patterns: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """COMPLETED -> APPROVED, REJECTED -> REJECTED, recorded with the human reviewer, role and rationale."""
    task = store.get(task_id)
    done = [o for o in store.outcomes(task_id) if o.resulting_state in ("COMPLETED", "REJECTED")]
    if not done:
        raise ValueError(f"{task_id}: not decided yet ({task.status})")
    o = done[-1]
    return transition(task.context["key"], "APPROVED" if o.resulting_state == "COMPLETED" else "REJECTED",
                      by=o.actor, role=o.role, rationale=o.rationale, path=path, patterns=patterns)