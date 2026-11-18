"""Source ingestion CLI: ``python -m rule_authoring.ingest --source aigf|ccc``.

Reads a source checkout through its adapter, prints a summary and writes a
deterministic JSON artifact (sorted, no timestamps, paths relative to the
checkout) to ``rule-authoring-framework/catalogs/sources/<source>.json``.

Default checkout locations come from ``AIGF_PATH`` / ``CCC_PATH`` settings.
``--extract --provider replay|bedrock`` runs extraction through the ModelGateway and writes DRAFTs to
``catalogs/drafts/`` (see ``extract_sources``).
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from . import sources_aigf, sources_ccc
from .paths import FRAMEWORK_ROOT

SOURCES_DIR = FRAMEWORK_ROOT / "catalogs" / "sources"


def git_commit(root: Path) -> str:
    """HEAD commit of the checkout, or ``unknown`` when it is not a git checkout."""
    try:
        r = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True,
                           text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "unknown"


def _rel(path: str, root: Path) -> str:
    """Path relative to root in POSIX form, or the plain POSIX path if it is outside root."""
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _aigf_inputs(root: Path) -> list[Path]:
    """AIGF risk and mitigation directories under the checkout, or the root if they are missing."""
    dirs = [root / "docs" / "_risks", root / "docs" / "_mitigations"]
    found = [d for d in dirs if d.is_dir()]
    return found or [root]


def _ccc_inputs(root: Path) -> list[Path]:
    """MVP CCC catalog directories in the checkout, or the root if none exist."""
    base = root / "catalogs" if (root / "catalogs").is_dir() else root
    found = [base / c for c in sources_ccc.MVP_CATALOGS if (base / c).is_dir()]
    return found or [root]


def ingest(source: str, root: Path, ids: Sequence[str] | None = None) -> dict:
    """Run an adapter and return the artifact document (JSON-serialisable)."""
    root = Path(root)
    if source == "aigf":
        items, errors = sources_aigf.read(_aigf_inputs(root))
        if ids:
            items = [i for i in items if i.id in set(ids)]
    elif source == "ccc":
        items, errors = sources_ccc.read(_ccc_inputs(root), control_ids=ids or None)
    else:
        raise ValueError(f"unknown source: {source}")
    out_items = []
    for i in items:
        d = dataclasses.asdict(i)
        d["path"] = _rel(i.path, root)
        out_items.append(d)
    out_errors = sorted(({"path": _rel(e.path, root), "field": e.field, "message": e.message} for e in errors),
                        key=lambda e: (e["path"], e["field"], e["message"]))
    return {"source": source, "commit": git_commit(root), "items": out_items, "errors": out_errors}


def write_source_artifact(doc: dict, out: Path):
    """Write the ingest artifact under the hash rule (unchanged content is not rewritten; changed content is v+1)."""
    from agip_shared import versioned_write as vw
    text = json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ch = vw.hash_content(text)
    return vw.write(out, text, content_hash=ch, version=vw.version_for(out, ch))


def summarize(doc: dict) -> str:
    """One-line summary of an ingested source document (kind counts, error count, commit)."""
    kinds: dict[str, int] = {}
    for i in doc["items"]:
        kinds[i["kind"]] = kinds.get(i["kind"], 0) + 1
    parts = ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())) or "none"
    return (f"{doc['source']}: {len(doc['items'])} items ({parts}), {len(doc['errors'])} errors, "
            f"commit {doc['commit']}")


def _default_path(source: str) -> str:
    """Checkout path for the source from settings."""
    from agip_shared.settings import get_settings
    s = get_settings()
    return s.aigf_path if source == "aigf" else s.ccc_path


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: ingest AIGF or CCC sources and optionally extract draft rules. Returns the exit code."""
    ap = argparse.ArgumentParser(prog="python -m rule_authoring.ingest")
    ap.add_argument("--source", required=True, choices=["aigf", "ccc"])
    ap.add_argument("--path", help="checkout root (default: AIGF_PATH / CCC_PATH setting)")
    ap.add_argument("--ids", nargs="+", help="limit to these native IDs (AIGF: ri-1 mi-6; CCC: control IDs)")
    ap.add_argument("--out", help=f"artifact path (default: {SOURCES_DIR}/<source>.json)")
    ap.add_argument("--extract", action="store_true", help="extract DRAFT rules via the ModelGateway")
    ap.add_argument("--provider", choices=["replay", "bedrock"], default="replay", help="model provider for --extract")
    ap.add_argument("--temperature", type=float, default=0.1, help="sampling temperature for --provider bedrock")
    ap.add_argument("--scores", choices=["decider", "llm"], default="decider",
                    help="AIGF risk likelihood/impact from the Strands Decider (default) or from the LLM")
    ap.add_argument("--steering-retries", type=int, default=2,
                    help="max retries when Strands steering rejects a model answer (bedrock only; 0 disables retries)")
    ap.add_argument("--recordings", help="recordings dir (default: fixtures/recordings/llm)")
    ap.add_argument("--drafts", help="drafts dir (default: catalogs/drafts)")
    a = ap.parse_args(argv)

    root = Path(a.path or _default_path(a.source))
    if not root.is_dir():
        print(f"error: checkout not found: {root}", file=sys.stderr)
        return 2
    doc = ingest(a.source, root, a.ids)
    out = Path(a.out) if a.out else SOURCES_DIR / f"{a.source}.json"
    w = write_source_artifact(doc, out)

    print(summarize(doc))
    for e in doc["errors"]:
        print(f"  ERROR {e['path']} [{e['field']}]: {e['message']}", file=sys.stderr)
    print(f"{'unchanged' if w.action == 'unchanged' else 'wrote'} {out} (v{w.version})")
    bad = bool(doc["errors"])
    if a.extract:
        bad = _extract(a, doc, root) or bad
    return 1 if bad else 0


def _scorer(a):
    """Decider scorer for AIGF risk likelihood/impact: live with --provider bedrock, recordings with replay; none with --scores llm."""
    if a.scores == "llm" or a.source != "aigf":
        return None
    from agip_shared.settings import get_settings

    from . import scoring
    rec = Path(a.recordings).parent / "decider-scores" if a.recordings else scoring.RECORDINGS
    return scoring.from_settings(get_settings(), "http" if a.provider == "bedrock" else "replay", rec)


def _extract(a, doc: dict, root: Path) -> bool:
    """Run draft rule extraction for the ingested document with a replay or Bedrock gateway."""
    from agip_shared.gateway import ModelGateway, Recorder
    from agip_shared.settings import get_settings

    from . import extract_sources as es
    rec = Recorder(a.recordings or FRAMEWORK_ROOT / "fixtures" / "recordings" / "llm")
    if a.provider == "replay":
        gw = ModelGateway("replay", recorder=rec)
    else:
        from agip_shared.gateway.runtime_strands import StrandsRuntime

        from . import extraction as ex
        s = get_settings()
        check = ex.steering_check(es.load_dimensions(), ex.load_fields() if a.source == "aigf" else None)
        rt = StrandsRuntime(profile=s.aws_profile, temperature=a.temperature, steering=check,
                            steering_retries=a.steering_retries)
        gw = ModelGateway("bedrock", s.bedrock_model_id, s.aws_region, rec, rt)
    summary = es.extract_items(doc, root, gw, drafts_dir=Path(a.drafts) if a.drafts else es.DRAFTS_DIR,
                               dimensions=es.load_dimensions(), ids=a.ids, scorer=_scorer(a))
    print("\n".join(summary.lines()))
    if gw.reused:
        print(f"  reused {gw.reused} recorded model answer(s): same input, prompt, model and parameters")
    return bool(summary.errors)


if __name__ == "__main__":
    raise SystemExit(main())