import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml

from calm_generation import composer, pattern_library as pl

ROOT = Path(__file__).resolve().parents[1]
SPEC = composer.load_spec(ROOT / "templates" / "RA03-LITE.compose.yaml")
REQUIRED = {"P02", "P03", "P07", "P08", "P11", "P12", "P13", "P14", "P15", "P16"}   # P15/P16 added for cyber remediation


@dataclass
class V:
    status: str
    errors: list = field(default_factory=list)
    version: str = "1.60.1"


@dataclass
class E:
    code: str
    path: str
    message: str


class Validator:
    def __init__(self, status="VALID", errors=()):
        self.v = V(status, list(errors))

    def validate_pattern(self, p):
        return self.v


class Store:
    def __init__(self):
        self.items = {}

    def upsert_catalog_item(self, item):
        self.items[(item["kind"], item["id"])] = item
        return item


def test_library_has_seed_patterns_with_metadata():
    pats = pl.load_patterns()
    assert set(pats) >= REQUIRED
    for pid, p in pats.items():
        if pid not in REQUIRED:          # patterns added through Build Pattern are checked by the lifecycle tests
            continue
        md = p["metadata"]
        assert p["$schema"].endswith("/release/1.2/meta/calm.json")
        assert md["status"] == "APPROVED" and isinstance(md["version"], int) and md["version"] >= 1
        assert "related_controls" in md and "related_risks" in md


def test_pattern_related_ids_exist_in_catalogs():
    cats = ROOT.parent / "rule-authoring-framework" / "catalogs"
    ctl = {i["control_id"] for i in yaml.safe_load((cats / "controls.catalog.yaml").read_text(encoding="utf-8"))["items"]}
    rsk = {i["risk_id"] for i in yaml.safe_load((cats / "risks.catalog.yaml").read_text(encoding="utf-8"))["items"]}
    for pid, p in pl.load_patterns().items():
        assert set(p["metadata"]["related_controls"]) <= ctl, pid
        assert set(p["metadata"]["related_risks"]) <= rsk, pid


@pytest.mark.parametrize("word", ["aws", "azure", "gcp", "bedrock", "openai", "claude", "kafka", "postgres", "mysql",
                                  "oracle", "kong", "apigee", "stripe", "mongodb", "redis", "lambda", "kubernetes"])
def test_patterns_are_technology_neutral(word):
    for f in (ROOT / "patterns").glob("P*.json"):
        assert word not in f.read_text(encoding="utf-8").lower(), f"{f.name} names {word}"


def test_publish_requires_valid_and_approval(tmp_path):
    p = pl.load_patterns()["P02"]
    with pytest.raises(pl.PatternRejected) as e:
        pl.publish(p, Validator("INVALID", [E("json-schema", "/nodes/0", "bad")]), Store(), "alice", tmp_path)
    assert "json-schema at /nodes/0: bad" in str(e.value)
    with pytest.raises(pl.PatternRejected, match="approval"):
        pl.publish(p, Validator(), Store(), " ", tmp_path)
    s = Store()
    rec = pl.publish(p, Validator(), s, "alice", tmp_path)
    assert rec["status"] == "PUBLISHED" and rec["version"] == str(p["metadata"]["version"]) and (tmp_path / rec["body"]["file"]).is_file()
    assert pl.as_candidate(p)["metadata"]["status"] == "CANDIDATE"


def test_composed_template_is_committed_and_deterministic():
    a = composer.compose(pl.load_patterns(), SPEC)
    b = composer.compose(dict(reversed(list(pl.load_patterns().items()))), {**SPEC, "patterns": list(reversed(SPEC["patterns"]))})
    assert a.ok and a.text == b.text
    assert (ROOT / "templates" / "RA03-LITE.json").read_text(encoding="utf-8") == a.text


def test_ra03_lite_contents():
    t = composer.compose(pl.load_patterns(), SPEC).template
    md = t["metadata"]
    assert md["ra-id"] == "RA03-LITE" and md["ra-version"] == int(SPEC["version"]) and {p["id"] for p in md["source-patterns"]} == REQUIRED - {"P15", "P16"}
    nodes = {}
    for item in t["properties"]["nodes"]["prefixItems"]:
        for d in item.get("anyOf", [item]):
            nodes[d["properties"]["unique-id"]["const"]] = d["properties"]
    assert set(nodes) == {"api-gateway", "invoice-processing-service", "invoice-intelligence-agent", "payment-agent",
                          "foundation-model", "payment-tool", "payment-api", "human-approval-service", "audit-service", "invoice-db"}
    types = {k: v["node-type"]["const"] for k, v in nodes.items()}
    assert types["payment-agent"] == types["invoice-intelligence-agent"] == "ai:agent"
    assert types["foundation-model"] == "ai:llm" and types["payment-tool"] == "ai:tool"
    for agent in ("payment-agent", "invoice-intelligence-agent"):
        meta = nodes[agent]["metadata"]["properties"]
        assert {"permitted_tools", "autonomy", "privilege"} <= set(meta)


def test_no_metadata_beyond_patterns():
    pats = pl.load_patterns()
    declared = set()
    for p in pats.values():
        for d in p["properties"]["nodes"]["prefixItems"]:
            declared |= set(((d["properties"].get("metadata") or {}).get("properties") or {}))
    t = composer.compose(pats, SPEC).template
    for item in t["properties"]["nodes"]["prefixItems"]:
        for d in item.get("anyOf", [item]):
            assert set((d["properties"].get("metadata") or {}).get("properties") or {}) <= declared


def test_bind_of_undeclared_property_is_rejected():
    spec = copy.deepcopy(SPEC)
    spec["components"][0]["bind"] = {"firewall": "enabled"}
    r = composer.compose(pl.load_patterns(), spec)
    assert not r.ok and r.text is None and "not declared" in r.errors[0]


def test_conflict_names_both_patterns():
    pats = copy.deepcopy(pl.load_patterns())
    agent14 = pats["P14"]["properties"]["nodes"]["prefixItems"][0]
    agent14["properties"]["metadata"]["properties"]["privilege"] = {"enum": ["admin"]}
    r = composer.compose(pats, SPEC)
    assert not r.ok and r.text is None
    assert any(c.key == "metadata.privilege" and set(c.patterns) == {"P12", "P14"} for c in r.conflicts)


def test_publish_template():
    text = (ROOT / "templates" / "RA03-LITE.json").read_text(encoding="utf-8")
    s = Store()
    rec = pl.publish_template(text, Validator(), s)
    assert rec["status"] == "PUBLISHED" and s.items[("ra_template", "RA03-LITE")]
    with pytest.raises(pl.PatternRejected):
        pl.publish_template(text, Validator("ERROR"), s)
