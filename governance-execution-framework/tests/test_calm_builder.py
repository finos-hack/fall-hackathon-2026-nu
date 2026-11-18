import copy
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml

from calm_generation import attributes as at
from calm_generation.placeholders import fill
from governance_execution.store.repository import MemoryRepository
from governance_execution.store.sink import ArtifactSink
from governance_execution.units.calm_builder import instantiate, load_template

FORMS = Path(__file__).resolve().parents[1] / "forms"
TPL, TEXT = load_template("RA03-LITE")


def form(v="v1"):
    return yaml.safe_load((FORMS / f"{v}.attributes.yaml").read_text(encoding="utf-8"))


def generated(f):
    """What calm generate 1.60.1 emits for this template: consts, placeholders, enum properties omitted."""
    nodes = []
    chosen = set()
    for o in f["options"]:
        sel = o["selected"] if isinstance(o["selected"], list) else [o["selected"]]
        chosen |= {o["choices"][s] for s in sel}
    for d, optional in at.iter_node_defs(TPL):
        p = d["properties"]
        if optional and not ("Audit service present" in chosen):
            continue
        meta = {}
        for k, s in (p.get("metadata") or {}).get("properties", {}).items():
            if "const" in s:
                meta[k] = s["const"]
            elif "enum" not in s:
                meta[k] = at._placeholder(k, s)
        nodes.append({"unique-id": p["unique-id"]["const"], "node-type": p["node-type"]["const"],
                      "name": p["name"]["const"], "description": p["description"]["const"], "metadata": meta})
    return {"nodes": nodes, "relationships": [], "$schema": TPL["$id"]}


@dataclass
class Gen:
    status: str
    model: dict
    version: str = "1.60.1"
    error: str = None


@dataclass
class Err:
    code: str
    severity: str
    message: str
    path: str


@dataclass
class Val:
    status: str
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    version: str = "1.60.1"
    exit_code: int = 0
    error: str = None


class FakeCalm:
    def __init__(self, f, val=None):
        self.f, self.val, self.calls = f, val or Val("VALID"), []

    def generate(self, template, choices):
        self.calls.append(("generate", choices))
        return Gen("OK", generated(self.f))

    def validate(self, arch, pattern=None):
        self.calls.append(("validate",))
        return self.val


def run(f, **kw):
    return instantiate(f, template=TPL, template_text=TEXT, template_status=kw.pop("status", "PUBLISHED"),
                       calm=kw.pop("calm", None) or FakeCalm(f), **kw)


def test_form_file_matches_template():
    base = yaml.safe_load((FORMS / "ra03-lite.attributes.yaml").read_text(encoding="utf-8"))
    assert base == at.form_for(TPL, TEXT, "PUBLISHED")
    with pytest.raises(at.TemplateNotPublished):
        at.form_for(TPL, TEXT, "DRAFT")


@pytest.mark.parametrize("v", ["v1", "v2", "v3", "v4"])
def test_variant_forms_validate(v):
    assert at.validate(form(v), TPL, TEXT) == []


@pytest.mark.parametrize("mutate,field", [
    (lambda f: f["values"].pop("PAYMENT_AGENT_AUTONOMY"), "PAYMENT_AGENT_AUTONOMY"),
    (lambda f: f["values"].update(PAYMENT_AGENT_PRIVILEGE="root"), "PAYMENT_AGENT_PRIVILEGE"),
    (lambda f: f["values"].update(PAYMENT_AGENT_PAYMENT_LIMIT="lots"), "PAYMENT_AGENT_PAYMENT_LIMIT"),
    (lambda f: f["values"].update(PAYMENT_AGENT_PAYMENT_LIMIT=0), "PAYMENT_AGENT_PAYMENT_LIMIT"),
    (lambda f: f["values"].update(NOT_A_FIELD=1), "NOT_A_FIELD"),
    (lambda f: f["attributes"].pop(0), "INVOICE_INTELLIGENCE_AGENT_AUTONOMY"),
    (lambda f: f["options"][0].update(selected=None), "opt-approval-path"),
    (lambda f: f["options"][0].update(selected="sideways"), "opt-approval-path"),
    (lambda f: f["app"].update(id="Bad Id"), "app.id"),
])
def test_invalid_attributes_block_instantiation(mutate, field):
    f = form()
    mutate(f)
    errs = at.validate(f, TPL, TEXT)
    assert field in {e.field for e in errs}
    calm = FakeCalm(f)
    r = run(f, calm=calm)
    assert r.status == "BLOCKED_ATTRIBUTES" and calm.calls == [] and r.app_model is None


def test_draft_template_refused():
    calm = FakeCalm(form())
    assert run(form(), status="DRAFT", calm=calm).status == "REFUSED" and calm.calls == []


def test_fill_replaces_every_placeholder_and_records_paths():
    f = form("v1")
    r = fill(generated(f), f, TPL)
    assert r.model is not None and r.leftovers == []
    assert r.model["$schema"] == "https://calm.finos.org/release/1.2/meta/calm.json"
    pay = next(n for n in r.model["nodes"] if n["unique-id"] == "payment-agent")["metadata"]
    assert pay["payment_limit"] == 25000 and pay["autonomy"] == "supervised"
    assert any(x["placeholder"] == -1 and x["attribute"] == "PAYMENT_AGENT_PAYMENT_LIMIT" for x in r.fill_record)


def test_leftover_reported_with_path_and_no_model():
    f = form("v1")
    g = generated(f)
    g["nodes"][0]["metadata"]["extra"] = "[[ EXTRA ]]"
    f2 = copy.deepcopy(f)
    del f2["values"]["FOUNDATION_MODEL_MODEL_VERSION"]
    r = fill(g, f2, TPL)
    assert r.model is None
    paths = {l.json_path for l in r.leftovers}
    assert "$.nodes[0].metadata.extra" in paths and any(p.endswith("metadata.model_version") for p in paths)


def test_instantiate_valid_writes_artifacts_and_catalog(tmp_path):
    repo = MemoryRepository(tmp_path)
    r = run(form("v1"), sink=ArtifactSink(repo, tmp_path))
    assert r.status == "VALID" and set(r.artifact_ids) == {"app_model", "generation_manifest", "calm_validation"}
    m = r.manifest
    assert m["output_sha256"] == r.app_sha256 and m["template"]["id"] == "RA03-LITE"
    assert m["option_choices"]["opt-approval-path"] == "Payment via Human Approval Service"
    assert repo.get_catalog_item("invoice-lite-v1")["body"]["sha256"] == r.app_sha256
    assert run(form("v1")).app_sha256 == r.app_sha256  # deterministic


def test_invalid_gives_guidance_and_no_catalog_entry(tmp_path):
    f = form("v4")
    bad = Val("INVALID", [Err("json-schema", "error", "must be <= 100000", "/nodes/payment-agent/metadata/payment_limit")])
    repo = MemoryRepository(tmp_path)
    r = run(f, calm=FakeCalm(f, bad), sink=ArtifactSink(repo, tmp_path))
    assert r.status == "INVALID" and "PAYMENT_AGENT_PAYMENT_LIMIT" in r.guidance[0]
    assert repo.get_catalog_item("invoice-lite-v4") is None
