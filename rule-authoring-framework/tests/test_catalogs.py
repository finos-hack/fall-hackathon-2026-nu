from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CATS = ROOT / "catalogs"
GOV_CONFIG = ROOT.parent / "governance-execution-framework" / "config"


def load(name):
    return yaml.safe_load((CATS / name).read_text(encoding="utf-8"))


def test_every_registry_control_defined_once():
    # The draft seed registry is retired; the catalog is the single source of truth.
    merged = [i["registry_id"] for i in load("controls.catalog.yaml")["items"] if i.get("registry_id")]
    assert merged, "catalog lost its registry-derived controls"
    assert len(merged) == len(set(merged))


def test_control_items_complete():
    cat = load("controls.catalog.yaml")
    assert cat["version"] and "illustrative" in cat["label"]
    ids = [i["control_id"] for i in cat["items"]]
    assert len(ids) == len(set(ids))
    for i in cat["items"]:
        assert i["source"]["framework"] and i["source"]["id"]
        for cfg in i["configurations"]:
            assert cfg["remediation"].strip()
            assert cfg["severity"] in {"critical", "high", "medium", "low"}
            assert isinstance(cfg["mandatory"], bool)
            assert cfg["rule_codes"] and set(cfg["rule_codes"]) <= set(i["spectral_rules"])


def test_risk_items_complete():
    for i in load("risks.catalog.yaml")["items"]:
        assert i["remediation"].strip() and i["source"]["id"].startswith("ri-")
        assert 1 <= i["likelihood"] <= 5 and 1 <= i["impact"] <= 5
        assert isinstance(i["mandatory_trigger"], bool) and i["dimension"]
        assert i["rule_codes"] and set(i["rule_codes"]) <= set(i["spectral_rules"])
        assert "severity" not in i  # computed from likelihood x impact, never stored


def test_rule_codes_globally_unique():
    codes = []
    for name in ("controls.catalog.yaml", "risks.catalog.yaml"):
        for i in load(name)["items"]:
            codes += list(i["spectral_rules"])
    assert len(codes) == len(set(codes))


def test_config_files_load_and_gate_targets_exist():
    cfg = {p.stem: yaml.safe_load(p.read_text(encoding="utf-8")) for p in GOV_CONFIG.glob("*.yaml")}
    assert {"scoring_profile", "gap_rule", "gates", "decision_matrix", "taxonomy"} <= set(cfg)
    ctrl_ids = {i["control_id"] for i in load("controls.catalog.yaml")["items"]}
    g2 = next(g for g in cfg["gates"]["order"] if g["id"] == "G2-PAYMENT-AUTH")
    assert set(g2["when"]["control_status"]) <= ctrl_ids
    # G1 (invalid CALM) is now assessment status BLOCKED, not a decision gate (task 23.7).
    assert [g["id"][:2] for g in cfg["gates"]["order"]] == ["G2", "G3"]
    m = cfg["scoring_profile"]["severity_matrix"]
    assert sorted(m) == [1, 2, 3, 4, 5] and all(len(r) == 5 for r in m.values())
    assert all(len(v) == 4 for v in cfg["decision_matrix"]["cells"].values())
    assert len(cfg["taxonomy"]["dimensions"]) == 7
