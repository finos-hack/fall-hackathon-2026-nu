import json
from pathlib import Path
import shutil

import pytest
import yaml

from calm_generation import attributes as at, lifecycle as lc, pattern_library as pl
from calm_generation.calm_cli import Err, Gen, Val
from calm_generation import cli
from calm_generation.cli import TEMPLATES

TEXT = (TEMPLATES / "RA03-LITE.json").read_text(encoding="utf-8")
TPL = json.loads(TEXT)


class StubCalm:
    """Stands in for `calm generate/validate`: emits consts and placeholders, as calm 1.60.1 does."""

    def __init__(self, val=None):
        self.val = val or Val("VALID")

    def generate(self, template, choices):
        chosen = {c for v in choices.values() for c in (v if isinstance(v, list) else [v])}
        nodes = []
        for d, optional in at.iter_node_defs(template):
            p = d["properties"]
            if optional and "Audit service present" not in chosen:
                continue
            meta = {k: s["const"] if "const" in s else at._placeholder(k, s)
                    for k, s in (p.get("metadata") or {}).get("properties", {}).items() if "const" in s or "enum" not in s}
            nodes.append({"unique-id": p["unique-id"]["const"], "node-type": p["node-type"]["const"],
                          "name": p["name"]["const"], "description": p["description"]["const"], "metadata": meta})
        return Gen("OK", {"nodes": nodes, "relationships": []}, "stub")

    def validate(self, arch, pattern=None):
        return self.val


def completed_form():
    base = at.form_for(TPL, TEXT, "PUBLISHED")
    src = pl.FRAMEWORK_ROOT.parent / "governance-execution-framework" / "forms" / "v1.attributes.yaml"
    v1 = yaml.safe_load(src.read_text(encoding="utf-8"))
    base["app"], base["values"], base["options"] = v1["app"], v1["values"], v1["options"]
    return base


@pytest.fixture
def reg(tmp_path):
    p = tmp_path / "lifecycle.yaml"
    shutil.copy(lc.REGISTRY, p)
    return str(p)


def run(reg, *argv, calm=None):
    return cli.main(["--registry", reg, *argv], calm=calm)


def write_form(tmp_path, form, name="f.yaml"):
    f = tmp_path / name
    f.write_text(yaml.safe_dump(form, sort_keys=False), encoding="utf-8")
    return str(f)


def set_state(reg, key, state):
    r = lc.load(Path(reg))
    r["entries"][key]["state"] = state
    lc.save(r, Path(reg))


def test_patterns_and_versions_list(reg, capsys):
    assert run(reg, "patterns") == 0
    assert capsys.readouterr().out.count("PUBLISHED") == len(pl.load_patterns())
    assert run(reg, "versions") == 0
    assert "RA03-LITE" in capsys.readouterr().out


def test_review_needs_by_role_rationale_and_follows_table(reg, capsys):
    with pytest.raises(SystemExit):
        run(reg, "approve", "P02", "--by", "x")
    assert run(reg, "approve", "P02", "--by", "x", "--role", "r", "--rationale", "y") == 1  # PUBLISHED -> APPROVED
    assert "refused" in capsys.readouterr().err


def test_unpublished_template_has_no_form_or_instance(reg, tmp_path, capsys):
    f = write_form(tmp_path, completed_form())
    set_state(reg, "RA03-LITE", "APPROVED")
    assert run(reg, "form", "RA03-LITE") == 1
    assert run(reg, "instantiate", "--form", f, calm=StubCalm()) == 1
    assert "only PUBLISHED" in capsys.readouterr().err


def test_identical_inputs_give_identical_hash(reg, tmp_path, capsys):
    f = write_form(tmp_path, completed_form())
    hashes = []
    for _ in range(2):
        assert run(reg, "instantiate", "--form", f, calm=StubCalm()) == 0
        hashes.append(capsys.readouterr().out.split("sha256=")[-1].strip())
    assert hashes[0] == hashes[1] and len(hashes[0]) == 64


def test_missing_calm_is_a_clear_error(reg, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CALM_BIN", raising=False)
    monkeypatch.setenv("PATH", "")
    assert run(reg, "instantiate", "--form", write_form(tmp_path, completed_form())) == 1
    assert "calm" in capsys.readouterr().err


def test_validate_pattern_file(reg, capsys):
    assert run(reg, "validate", str(pl.PATTERN_DIR / "P02-api-gateway.json")) == 0
