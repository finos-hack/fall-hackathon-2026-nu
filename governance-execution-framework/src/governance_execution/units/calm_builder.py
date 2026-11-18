"""CALM Builder unit: attributes -> ``calm generate`` -> Placeholder_Fill -> ``calm validate -p`` (Req 9-11).

No LLM. Writes the App_Model, Generation_Manifest and CALM validation as immutable artifacts and records the
App_Model in the CALM_Catalog. INVALID results carry correction guidance per error (Variant V4).
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from agip_shared.hashing import canonical_hash, canonical_json, sha256_hex

from ..store.sink import ArtifactSink

TEMPLATE_DIR = Path(__file__).resolve().parents[4] / "calm-app-generation-framework" / "templates"


@dataclass
class InstantiateResult:
    """Outcome of :func:`instantiate`: status, the generated model, manifest, validation, errors and artifact references."""
    status: str                      # VALID | INVALID | ERROR | BLOCKED_ATTRIBUTES | LEFTOVERS | REFUSED
    app_id: Optional[str] = None
    trace_id: Optional[str] = None
    app_model: Optional[dict[str, Any]] = None
    app_sha256: Optional[str] = None
    manifest: Optional[dict[str, Any]] = None
    validation: Optional[dict[str, Any]] = None
    errors: list[str] = field(default_factory=list)
    guidance: list[str] = field(default_factory=list)
    artifact_ids: dict[str, str] = field(default_factory=dict)


def validation_dict(v: Any) -> dict[str, Any]:
    """CALM result for artifacts. Duration is left out so identical runs give identical artifacts."""
    return {"status": v.status, "errors": [asdict(e) for e in v.errors], "warnings": [asdict(w) for w in v.warnings],
            "calm_cli_version": v.version, "exit_code": v.exit_code, "error": v.error}


def guidance_for(validation: Any, form: dict[str, Any]) -> list[str]:
    """Turn each CALM validation error into a correction hint, naming the form attribute mapped to the failing node field when one exists."""
    by_target = {(a["target"]["node"], a["target"]["field"]): a["name"] for a in form.get("attributes") or []}
    out = []
    for e in validation.errors:
        m = re.match(r"^/nodes/([^/]+)(?:/metadata/([^/]+))?", e.path or "")
        attr = by_target.get((m.group(1), m.group(2))) if m and m.group(2) else None
        where = f"attribute {attr}" if attr else f"the model at {e.path or '(root)'}"
        out.append(f"{e.path or '/'}: {e.message}. Correct {where} and instantiate again.")
    return out


def load_template(template_id: str, directory: Path = TEMPLATE_DIR) -> tuple[dict[str, Any], str]:
    """Read ``<template_id>.json`` from ``directory``; return the parsed template and its exact text (hashed for the manifest)."""
    text = (directory / f"{template_id}.json").read_text(encoding="utf-8")
    return json.loads(text), text


def instantiate(form: dict[str, Any], *, template: dict[str, Any], template_text: str, template_status: str,
                calm: Any, sink: Optional[ArtifactSink] = None, trace_id: Optional[str] = None) -> InstantiateResult:
    """Generate, fill and validate a CALM model from an attribute form.

    Returns an InstantiateResult and never raises for expected failures (REFUSED, BLOCKED_ATTRIBUTES, LEFTOVERS, ERROR, INVALID).
    With a ``sink`` it also writes the app_model, generation_manifest and calm_validation artifacts, and for a VALID model registers it in the catalog.
    """
    # Lazy: the standalone governance CLI validates CALM and never generates it, so it must not load calm_generation.
    from calm_generation import attributes as attrs
    from calm_generation.composer import COMPOSER_VERSION
    from calm_generation.placeholders import fill
    app_id = (form.get("app") or {}).get("id")
    res = InstantiateResult("ERROR", app_id=app_id, trace_id=trace_id)
    if template_status != "PUBLISHED":
        res.status, res.errors = "REFUSED", [f"template status is {template_status}; only PUBLISHED templates can be instantiated"]
        return res
    errs = attrs.validate(form, template, template_text)
    errs += attrs.consistency_errors(form, attrs.load_consistency(template["metadata"]["ra-id"], TEMPLATE_DIR))
    if errs:
        res.status, res.errors = "BLOCKED_ATTRIBUTES", [str(e) for e in errs]
        return res

    choices = attrs.option_choices(form)
    gen = calm.generate(template, choices)
    if gen.status != "OK":
        res.errors = [f"calm generate: {gen.error}"]
        return res
    filled = fill(gen.model, form, template)
    if filled.model is None:
        res.status, res.errors = "LEFTOVERS", [f"leftover placeholder {l}" for l in filled.leftovers]
        return res
    model = filled.model
    app_sha = sha256_hex(canonical_json(model))
    md = template["metadata"]
    manifest = {
        "template": {"id": md["ra-id"], "version": md["ra-version"], "sha256": sha256_hex(template_text)},
        "source_patterns": [{"id": p["id"], "version": p["version"]} for p in md.get("source-patterns", [])],
        "composer_version": md.get("composer-version", COMPOSER_VERSION),
        "attributes_sha256": attrs.attributes_hash(form),
        "option_choices": choices,
        "calm_cli_version": gen.version,
        "output_sha256": app_sha,
        "fill_record": filled.fill_record,
    }
    if isinstance(form.get("requirements"), dict):   # user requirements and the Decider-inferred values (provenance)
        manifest["requirements"] = form["requirements"]
        manifest["inputs"] = {"values": form.get("values") or {},
                              "options": {o["unique_id"]: o.get("selected") for o in form.get("options") or []}}
    v = calm.validate(model, template)
    res.app_model, res.app_sha256, res.manifest, res.validation = model, app_sha, manifest, validation_dict(v)
    res.status = v.status
    if v.status == "INVALID":
        res.errors = [f"{e.code} {e.path}: {e.message}" for e in v.errors]
        res.guidance = guidance_for(v, form)
    elif v.status == "ERROR":
        res.errors = [f"calm validate: {v.error}"]
    if sink is not None:
        trace = trace_id or f"gen-{app_id}-{app_sha[:12]}"
        res.trace_id = trace
        for kind, content in (("app_model", model), ("generation_manifest", manifest), ("calm_validation", res.validation)):
            res.artifact_ids[kind] = sink.put(trace, kind, app_id, content).id
        if v.status == "VALID":
            sink.repo.upsert_catalog_item({
                "id": app_id, "kind": "app_model", "version": app_sha[:12], "status": "VALID",
                "source_ids": [md["ra-id"]],
                "body": {"name": (form.get("app") or {}).get("name"), "trace_id": trace, "sha256": app_sha,
                         "template": manifest["template"], "manifest_sha256": canonical_hash(manifest)}})
    return res
