"""Facts: deterministic Taxonomy mapping of App_Model metadata, with provenance (Req 13).

For every node and every taxonomy attribute that applies to its node-type, one Fact is produced:
``MAPPED`` (raw value in the taxonomy), ``UNMAPPED`` (raw value present but not in the taxonomy; kept,
never guessed) or ``UNKNOWN`` (attribute absent). Per-agent facts cover permitted tools, autonomy and
privilege. Pure: same App_Model and taxonomy give the same FactSet.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agip_shared.contracts import Fact, FactSet
from agip_shared.hashing import canonical_json, sha256_hex

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
AGENT_FACTS = ("permitted_tools", "autonomy", "privilege")


def load_taxonomy(path: Path = CONFIG_DIR / "taxonomy.yaml") -> dict[str, Any]:
    """Load the taxonomy YAML (default ``config/taxonomy.yaml``)."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _map(raw: Any, spec: dict[str, Any]) -> tuple[str, Any]:
    """Map a raw value through a taxonomy attribute spec: ('MAPPED', value) on a case-insensitive hit or verbatim spec, else ('UNMAPPED', None)."""
    if spec.get("verbatim"):
        return "MAPPED", raw
    if isinstance(raw, str):
        values = {str(k).lower(): v for k, v in (spec.get("values") or {}).items()}
        hit = values.get(raw.strip().lower())
        if hit is not None:
            return "MAPPED", hit
    return "UNMAPPED", None


def extract(app_model: dict[str, Any], taxonomy: dict[str, Any]) -> FactSet:
    """Build the FactSet: one Fact per node and applicable taxonomy attribute, in sorted attribute order, with provenance hashes."""
    version = str(taxonomy.get("version", ""))
    facts: list[Fact] = []
    prov = {"app_model_sha256": sha256_hex(canonical_json(app_model)), "taxonomy_version": version}
    for i, node in enumerate(app_model.get("nodes") or []):
        nid, ntype = node.get("unique-id", f"#{i}"), node.get("node-type", "")
        meta = node.get("metadata") or {}
        for attr in sorted(taxonomy.get("attributes") or {}):
            spec = taxonomy["attributes"][attr]
            if ntype not in (spec.get("element_types") or []):
                continue
            path = f"$.nodes[{i}].metadata.{attr}"
            if attr not in meta:
                facts.append(Fact(id=f"{nid}.{attr}", element_id=nid, json_path=path, raw=None, normalized=None,
                                  taxonomy_version=version, mapping_status="UNKNOWN", attribute=attr,
                                  dimension=spec["dimension"], extraction_method="taxonomy_absent", provenance=prov))
                continue
            status, norm = _map(meta[attr], spec)
            facts.append(Fact(id=f"{nid}.{attr}", element_id=nid, json_path=path, raw=meta[attr],
                              normalized=None if norm is None else (norm if isinstance(norm, str) else canonical_json(norm)),
                              taxonomy_version=version, mapping_status=status, attribute=attr, dimension=spec["dimension"],
                              extraction_method="taxonomy_mapping", provenance=prov))
    return FactSet(facts=facts, taxonomy_version=version, app_model_sha256=sha256_hex(canonical_json(app_model)))


def agent_facts(facts: FactSet) -> dict[str, dict[str, Any]]:
    """Per-agent view: {agent id: {permitted_tools, autonomy, privilege}} (Req 13.5)."""
    out: dict[str, dict[str, Any]] = {}
    for f in facts.facts:
        if f.attribute in AGENT_FACTS:
            out.setdefault(f.element_id, {})[f.attribute] = f.raw
    return out


def unmapped(facts: FactSet) -> list[Fact]:
    """Facts whose raw value is present but not in the taxonomy."""
    return [f for f in facts.facts if f.mapping_status == "UNMAPPED"]
