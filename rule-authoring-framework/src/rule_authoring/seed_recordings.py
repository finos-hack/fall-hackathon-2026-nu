"""Write recorded extraction outputs for the demo items (Req 4.6: the demo uses recorded approved outputs).

The recorded outputs are authored from the approved catalog entries, not produced by a live model; the
Extraction_Record carries model ``recorded-seed``. Live re-extraction via Bedrock produces a new DRAFT instead.

CLI: ``python -m rule_authoring.seed_recordings <aigf_docs_dir>``
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

import yaml

from agip_shared.contracts import Extraction_Record
from agip_shared.gateway import Recorder
from agip_shared.gateway.model_gateway import ModelGateway, sanitize

from . import extraction as ex
from .paths import FRAMEWORK_ROOT
from .sources_aigf import read as read_aigf

RECORDINGS = FRAMEWORK_ROOT / "fixtures" / "recordings" / "llm"
SEED_ITEMS = {"AIGF-MI-024": "control", "AIGF-RI-024": "risk"}
_IMPACT = {"critical": 5, "high": 4, "medium": 3, "low": 2}


def _catalog_entry(item_id: str) -> dict[str, Any]:
    """Catalog entry (control or risk) with this id; raises KeyError if absent."""
    for name in ("controls", "risks"):
        doc = yaml.safe_load((FRAMEWORK_ROOT / "catalogs" / f"{name}.catalog.yaml").read_text(encoding="utf-8"))
        for e in doc["items"]:
            if item_id in (e.get("control_id"), e.get("risk_id")):
                return e
    raise KeyError(item_id)


def output_for(entry: dict[str, Any]) -> dict[str, Any]:
    """Model output to record for a catalog entry, rebuilt from its approved rule so replay yields the same draft."""
    is_control = "control_id" in entry
    code = next(iter(entry["spectral_rules"]))
    rule = entry["spectral_rules"][code]
    then = {k: v for k, v in rule["then"].items()}
    if is_control:
        cfg = entry["configurations"][0]
        dim, lik, imp, rem = "Human Oversight", 3, _IMPACT[cfg["severity"]], cfg["remediation"]
    else:
        dim, lik, imp, rem = entry["dimension"], entry["likelihood"], entry["impact"], entry["remediation"]
    return {
        "kind": "control" if is_control else "risk",
        "triggers": [{"dimension": dim, "condition": rule["description"]}],
        "likelihood": {"score": lik, "criteria": "recorded seed value"},
        "impact": {"score": imp, "criteria": "recorded seed value"},
        "remediation": rem,
        "candidate_rule": {"rule_code": code, "description": rule["description"], "severity": rule["severity"],
                           "given": rule["given"], "then": then},
    }


class _Seed:
    """Runtime stub that returns one pre-authored output."""

    def __init__(self, out: dict[str, Any]):
        """Store the canned output as JSON text."""
        import json
        self.text = json.dumps(out)

    def complete(self, prompt: str, model: str, region: str) -> str:
        """Return the canned output regardless of the prompt."""
        return self.text


def record(aigf_docs: Path, root: Path = RECORDINGS) -> list[str]:
    """Record seed extraction outputs for the AIGF items in SEED_ITEMS; returns '<key>: <input_hash>' lines."""
    items, _ = read_aigf([aigf_docs / "_mitigations", aigf_docs / "_risks"])
    by_key = {ex.item_key(i.framework, i.id): i for i in items}
    written = []
    for key in sorted(SEED_ITEMS):
        src = by_key[key]
        prose = ex.body_of_markdown(Path(src.path).read_text(encoding="utf-8"))
        gw = ModelGateway("bedrock", "recorded-seed", "none", Recorder(root), _Seed(output_for(_catalog_entry(key))))
        rec = gw.complete(ex.PROMPT_ID, ex.PROMPT_VERSION,
                          {"framework": src.framework, "id": src.id, "title": src.title, "prose": prose},
                          prompt=ex.load_prompt(), item_id=key)
        written.append(f"{key}: {rec.input_hash}")
    return written


def _then_rule(code, desc, field, pattern):
    """Candidate rule that applies a pattern check to a field of database node metadata."""
    return {"rule_code": code, "description": desc, "severity": "error",
            "given": "$.nodes[?(@['node-type']=='database')].metadata",
            "then": {"field": field, "function": "pattern", "functionOptions": {"match": pattern}}}


# Hand-authored CCC outputs (prompt v2), as a model would return them. CN01 is inexpressible on purpose:
# the CALM vocabulary has no transport-encryption attribute.
CCC_SEEDS: dict[str, dict[str, Any]] = {
    "CCC.Core.CN02": {
        "kind": "control",
        "triggers": [{"dimension": "Data Exposure", "condition": "A database stores data without encryption at rest"}],
        "likelihood": {"score": 3, "criteria": "Storage is often left on defaults"},
        "impact": {"score": 4, "criteria": "Stored data is exposed if the medium is accessed"},
        "remediation": "Enable encryption at rest on every database node.",
        "candidate_rule": _then_rule("ctl-database-encrypted-at-rest", "Databases must have encryption at rest enabled",
                                     "encryption_at_rest", "^enabled$"),
        "inexpressible_reason": None,
    },
    "CCC.Core.TH01": {
        "kind": "risk",
        "triggers": [{"dimension": "Privilege & Capability",
                      "condition": "A database allows access without role-based access control"}],
        "likelihood": {"score": 3, "criteria": "Permission logic is easy to misconfigure"},
        "impact": {"score": 4, "criteria": "Unauthorized access can expose or alter data"},
        "remediation": "Enforce role-based access control on every database node.",
        "candidate_rule": _then_rule("risk-database-unauthorized-access", "Databases must use role-based access control",
                                     "access_control", "^rbac$"),
        "inexpressible_reason": None,
    },
    "CCC.Core.CN01": {
        "kind": "control",
        "triggers": [{"dimension": "Connectivity", "condition": "Traffic on an exposed port is not encrypted in transit"}],
        "likelihood": {"score": 3, "criteria": "Legacy listeners may accept plain traffic"},
        "impact": {"score": 4, "criteria": "Traffic can be read or altered in transit"},
        "remediation": "Require TLS 1.3 (or SSHv2) on every exposed port and redirect plain traffic.",
        "candidate_rule": None,
        "inexpressible_reason": "The CALM metadata vocabulary has no transport-encryption or TLS version attribute to check.",
    },
}


def record_ccc(ccc_root: Path, root: Path = RECORDINGS) -> list[str]:
    """Record seed extraction outputs for the CCC items in CCC_SEEDS; returns '<id>: <input_hash>' lines."""
    from .extract_sources import ccc_detail
    from .ingest import ingest
    doc = ingest("ccc", ccc_root)
    by_id = {i["id"]: i for i in doc["items"]}
    written = []
    for cid in sorted(CCC_SEEDS):
        it = by_id[cid]
        d = ccc_detail(ccc_root, it)
        inp = ex.ccc_input(native_id=cid, kind=it["kind"], title=it["title"], **d)
        gw = ModelGateway("bedrock", "recorded-seed", "none", Recorder(root), _Seed(CCC_SEEDS[cid]))
        rec = gw.complete(ex.PROMPT_ID, ex.CCC_PROMPT_VERSION, inp, prompt=ex.load_prompt(ex.prompt_path("v2")), item_id=cid)
        written.append(f"{cid}: {rec.input_hash}")
    return written


def main(argv: Optional[list[str]] = None) -> int:
    """CLI: record seed recordings. Returns 2 on bad usage."""
    args = argv if argv is not None else sys.argv[1:]
    if len(args) not in (1, 2):
        print("usage: python -m rule_authoring.seed_recordings <aigf docs dir> [<ccc checkout>]", file=sys.stderr)
        return 2
    for line in record(Path(args[0])):
        print(line)
    if len(args) == 2:
        for line in record_ccc(Path(args[1])):
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
