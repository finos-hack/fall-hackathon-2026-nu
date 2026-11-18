"""Rule Authoring unit: extract (DRAFT), approve, compile. Wraps ``rule_authoring`` code."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from agip_shared.gateway import ModelGateway
from rule_authoring import extraction as ex


def extract_and_store(repo: Any, gateway: ModelGateway, *, framework: str, native_id: str, title: str,
                      source_path: str, prompt: Optional[str] = None) -> ex.ExtractionResult:
    """Read the item's prose, extract via the gateway, store as DRAFT. Rejected output is not stored.

    A live re-extraction of an existing item is stored as a new DRAFT version, never
    replacing an APPROVED one (Req 4.6).
    """
    text = Path(source_path).read_text(encoding="utf-8")
    result = ex.extract(gateway, framework=framework, native_id=native_id, title=title,
                        prose=ex.body_of_markdown(text), source_path=source_path, prompt=prompt)
    if not result.ok or result.item is None:
        return result
    item = dict(result.item)
    existing = repo.get_catalog_item(item["id"])
    if existing is not None:
        if existing["body"].get("extraction_input_hash") == item["body"]["extraction_input_hash"] \
                and existing["status"] == "APPROVED":
            return ex.ExtractionResult(True, existing, result.record, None)  # same input already approved
        item["version"] = str(int(existing["version"]) + 1) if str(existing["version"]).isdigit() else "2"
    stored = repo.upsert_catalog_item(item)
    return ex.ExtractionResult(True, stored, result.record, None)
