import json

import pytest

from calm_generation import FIXTURE_VARIANTS_DIR

# Draft-repo examples only (hyphen node types); the Invoice-Lite variants use `ai:agent` and are covered by the golden tests.
FIXTURES = sorted(FIXTURE_VARIANTS_DIR.glob("customer-support-*.json"))


def test_fixture_variants_present():
    assert {p.stem for p in FIXTURES} >= {"customer-support-compliant", "customer-support-gap"}


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_fixture_has_agent_node(path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["nodes"]
    assert any(n.get("node-type") == "ai-agent" for n in doc["nodes"])
