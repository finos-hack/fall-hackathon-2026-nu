"""Property 4: manifest and output hash round trip (task 20.2, 8.6). CALM adapter is stubbed."""
from dataclasses import dataclass, field
from pathlib import Path
import tempfile

import yaml
from hypothesis import given, settings, strategies as st

from agip_shared.hashing import canonical_json, sha256_hex
from calm_generation import attributes as at
from governance_execution.store.repository import MemoryRepository
from governance_execution.store.sink import ArtifactSink
from governance_execution.units.calm_builder import instantiate, load_template

FORMS = Path(__file__).resolve().parents[1] / "forms"
TPL, TEXT = load_template("RA03-LITE")


@dataclass
class Gen:
    status: str
    model: dict
    version: str
    error: str = None


@dataclass
class Val:
    status: str = "VALID"
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    version: str = "1.60.1"
    exit_code: int = 0
    error: str = None


class StubCalm:
    def __init__(self, version):
        self.version = version

    def generate(self, template, choices):
        nodes = []
        for d, _ in at.iter_node_defs(template):
            p = d["properties"]
            meta = {}
            for k, s in (p.get("metadata") or {}).get("properties", {}).items():
                if "const" in s:
                    meta[k] = s["const"]
                elif "enum" not in s:
                    meta[k] = at._placeholder(k, s)
            nodes.append({"unique-id": p["unique-id"]["const"], "node-type": p["node-type"]["const"],
                          "name": p["name"]["const"], "description": p["description"]["const"], "metadata": meta})
        return Gen("OK", {"nodes": nodes, "relationships": [], "$schema": template["$id"]}, self.version)

    def validate(self, arch, pattern=None):
        return Val(version=self.version)


def form(v):
    return yaml.safe_load((FORMS / f"{v}.attributes.yaml").read_text(encoding="utf-8"))


# Feature: governance-as-code-mvp, Property 4: Manifest and output hash round trip
@settings(max_examples=100, deadline=None)
@given(v=st.sampled_from(["v1", "v2", "v3", "v4"]),
       version=st.from_regex(r"[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,2}", fullmatch=True),
       limit=st.integers(min_value=1, max_value=100000))
def test_property_4_manifest_and_hash_round_trip(v, version, limit):
    f = form(v)
    f["values"]["PAYMENT_AGENT_PAYMENT_LIMIT"] = limit
    assert at.validate(f, TPL, TEXT) == []
    results = []
    for _ in range(2):
        with tempfile.TemporaryDirectory() as d:
            repo = MemoryRepository(Path(d))
            r = instantiate(f, template=TPL, template_text=TEXT, template_status="PUBLISHED",
                            calm=StubCalm(version), sink=ArtifactSink(repo, d), trace_id="t")
            assert r.status == "VALID"
            stored = ArtifactSink(repo, d).get("t", "app_model", f["app"]["id"])
            stored_manifest = ArtifactSink(repo, d).get("t", "generation_manifest", f["app"]["id"])
            assert sha256_hex(canonical_json(stored)) == stored_manifest["output_sha256"] == r.app_sha256
            assert r.manifest["calm_cli_version"] == version
            results.append((r.app_sha256, r.manifest))
    assert results[0] == results[1]
