"""End-to-end journey (Req 7-11): inspect, compose, conflict, review, form, instantiate, reject, V4, reproduce."""
import sys
from pathlib import Path

import pytest
import yaml

from calm_generation import lifecycle as lc
from calm_generation.calm_cli import Err, Val

sys.path.insert(0, str(Path(__file__).parent))
from test_cli import StubCalm, completed_form, reg, run, set_state, write_form  # noqa: F401

pytestmark = pytest.mark.acceptance

TEMPLATES = lc.FRAMEWORK_ROOT / "templates"


def hash_of(capsys):
    return capsys.readouterr().out.split("sha256=")[-1].split()[0]


def test_journey(tmp_path, reg, capsys):
    assert run(reg, "patterns") == 0 and "P12" in capsys.readouterr().out
    assert run(reg, "versions") == 0 and "RA03-LITE" in capsys.readouterr().out

    out = tmp_path / "RA03-LITE.json"
    assert run(reg, "compose", "--out", str(out)) == 0
    assert out.read_text(encoding="utf-8") == (TEMPLATES / "RA03-LITE.json").read_text(encoding="utf-8")
    capsys.readouterr()

    spec = yaml.safe_load((TEMPLATES / "RA03-LITE.compose.yaml").read_text(encoding="utf-8"))
    spec["components"][1]["bind"] = {"role": "not-the-api-role", "exposure": "nowhere"}
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(spec), encoding="utf-8")
    assert run(reg, "compose", str(bad), "--out", str(tmp_path / "bad.json")) == 1
    assert not (tmp_path / "bad.json").exists()
    capsys.readouterr()

    set_state(reg, "RA03-LITE", "DRAFT")
    assert run(reg, "form", "RA03-LITE") == 1
    for step in ("submit", "approve", "publish"):
        assert run(reg, step, "RA03-LITE", "--by", "dana", "--role", "architect", "--rationale", "reviewed") == 0
    assert run(reg, "publish", "RA03-LITE", "--by", "d", "--role", "r", "--rationale", "again") == 1
    capsys.readouterr()

    assert run(reg, "form", "RA03-LITE", "--out", str(tmp_path / "blank.yaml")) == 0
    form = completed_form()
    ok = write_form(tmp_path, form)
    assert run(reg, "instantiate", "--form", ok, "--out", str(tmp_path / "a.json"), calm=StubCalm()) == 0
    h1 = hash_of(capsys)

    form["values"]["PAYMENT_AGENT_PRIVILEGE"] = "root"
    assert run(reg, "instantiate", "--form", write_form(tmp_path, form, "bad.yaml"), calm=StubCalm()) == 1
    assert "PAYMENT_AGENT_PRIVILEGE" in capsys.readouterr().err

    inv = StubCalm(Val("INVALID", [Err("json-schema", "/nodes/payment-agent/metadata/payment_limit", "bad")]))
    assert run(reg, "instantiate", "--form", ok, calm=inv) == 1
    assert "payment_limit" in capsys.readouterr().err

    assert run(reg, "instantiate", "--form", ok, "--out", str(tmp_path / "b.json"), calm=StubCalm()) == 0
    assert hash_of(capsys) == h1
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()
