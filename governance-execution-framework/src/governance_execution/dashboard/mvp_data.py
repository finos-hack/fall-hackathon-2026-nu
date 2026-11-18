"""Read model for the MVP dashboard pages (Req 24.5, 25.1-25.6): persisted records and framework files, read as data only."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from .data import ReportStore, compose_spec

ROOT = Path(__file__).resolve().parents[4]          # platform root (holds the four frameworks)
RA = ROOT / "rule-authoring-framework"
CG = ROOT / "calm-app-generation-framework"
GE = ROOT / "governance-execution-framework"
CATALOGS = RA / "catalogs"
RULESETS = RA / "rulesets"
CONFIG = GE / "config"
KINDS = ("sources", "risks", "controls", "assessment-requirements", "patterns", "ras", "rulesets",
         "governance-config", "scoring-profiles", "evaluators", "models-prompts")
OPEN_STATES = ("OPEN", "ASSIGNED", "CLAIMED", "CHANGES_REQUESTED")
CONFIG_KEYS = {"scoring_profile": "scoring_profile.yaml", "gap_rule": "gap_rule.yaml", "gates": "gates.yaml",
               "decision_matrix": "decision_matrix.yaml", "taxonomy": "taxonomy.yaml", "decider_policy": "decider_policy.yaml"}
_PROMPT = re.compile(r"^(?P<name>.+)\.(?P<ver>v\d+)\.md$")


def _yaml(p: Path) -> Any:
    """Parse a YAML file; an empty file gives {}."""
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _sha(p: Path) -> str:
    """SHA-256 hex digest of the file's bytes."""
    return hashlib.sha256(p.read_bytes()).hexdigest()


def item_id(it: dict) -> str:
    """Identifier of a catalog item, whichever key it uses (control_id, risk_id or id)."""
    return it.get("control_id") or it.get("risk_id") or it.get("id") or ""


def catalog_items(kind: str) -> list[dict]:
    """Items of the ``<kind>`` catalog YAML; empty if the file does not exist."""
    f = CATALOGS / f"{kind}.catalog.yaml"
    return (_yaml(f).get("items") or []) if f.is_file() else []


def catalog_version(kind: str) -> str:
    """Version string of the ``<kind>`` catalog, or '' if the file is missing."""
    f = CATALOGS / f"{kind}.catalog.yaml"
    return str(_yaml(f).get("version", "")) if f.is_file() else ""


def source_items() -> list[dict]:
    """All extraction source items from the source JSON files, tagged with ``_file`` and ``_key`` (``framework:id``)."""
    out = []
    for f in sorted((CATALOGS / "sources").glob("*.json")):
        for it in json.loads(f.read_text(encoding="utf-8")).get("items") or []:
            out.append({**it, "_file": f.name, "_key": f"{it.get('framework')}:{it.get('id')}"})
    return out


def lifecycle() -> dict[str, dict]:
    """Lifecycle entries (state and history) of patterns and RA templates, keyed by id."""
    f = CG / "registry" / "lifecycle.yaml"
    return (_yaml(f).get("entries") or {}) if f.is_file() else {}


def patterns() -> list[dict]:
    """Summaries of the CALM pattern files (``P*.json``)."""
    out = []
    for f in sorted((CG / "patterns").glob("P*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        m = d.get("metadata") or {}
        out.append({"id": m.get("pattern-id"), "title": d.get("title"), "version": str(m.get("version", "")), "status": m.get("status"),
                    "related_controls": m.get("related_controls") or [], "related_risks": m.get("related_risks") or [], "file": f.name})
    return out


def ras() -> list[dict]:
    """Summaries of the RA template files, including the patterns each is composed from."""
    out = []
    for f in sorted((CG / "templates").glob("*.json")):
        m = (json.loads(f.read_text(encoding="utf-8")).get("metadata") or {})
        out.append({"id": m.get("ra-id") or f.stem, "version": str(m.get("ra-version", "")), "status": m.get("status"),
                    "patterns": m.get("source-patterns") or [], "file": f.name})
    return out


def rulesets() -> list[dict]:
    """Compiled rulesets listed in MANIFEST.yaml with version, hash and the rule codes found in each file."""
    f = RULESETS / "MANIFEST.yaml"
    man = (_yaml(f).get("rulesets") or {}) if f.is_file() else {}
    out = []
    for name, m in man.items():
        p = RULESETS / name
        rr = (_yaml(p).get("rules") if p.is_file() else None)
        codes = sorted(rr.keys()) if isinstance(rr, dict) else []
        out.append({"id": name, "version": str(m.get("version", "")), "sha256": m.get("sha256"), "rules": m.get("rules"), "codes": codes})
    return out


def config_files() -> list[dict]:
    """Governance config YAML files with their version, label and SHA-256."""
    return [{"id": f.stem, "file": f.name, "version": str(_yaml(f).get("version", "")), "label": _yaml(f).get("label"), "sha256": _sha(f)}
            for f in sorted(CONFIG.glob("*.yaml"))]


def prompts() -> list[dict]:
    """Prompt files of the three frameworks, parsed from ``<name>.<vN>.md`` file names, with SHA-256."""
    out = []
    for d, fw in ((RA / "prompts", "rule-authoring"), (CG / "prompts", "calm-generation"), (GE / "prompts", "governance-execution")):
        for f in sorted(d.glob("*.md")):
            m = _PROMPT.match(f.name)
            out.append({"id": f.stem, "name": m["name"] if m else f.stem, "version": m["ver"] if m else "", "framework": fw, "sha256": _sha(f), "file": f.name})
    return out


def artifact_kind_present(store: ReportStore, kind_names: tuple[str, ...]) -> list[tuple[str, str, str]]:
    """List (trace, kind, artifact id) for every stored artifact whose kind is in ``kind_names``."""
    out = []
    for t in store.traces():
        for k, ids in store.kinds(t).items():
            if k in kind_names:
                out += [(t, k, i) for i in ids]
    return out


# ---------------------------------------------------------------- assessment reference tokens (25.6, 25.5)
def tokens_of(store: ReportStore, trace: str) -> dict[str, str]:
    """token -> version recorded by the assessment (what it was run against)."""
    v = store.get(trace, "versions") or {}
    cg = store.get(trace, "control_gap") or {}
    rp = store.get(trace, "risk_profile") or {}
    cat = v.get("catalogs") or {}
    t: dict[str, str] = {}
    for c in cg.get("controls") or []:
        t[f"control:{c['control_id']}"] = str(cat.get("controls", ""))
        for k in c.get("rule_codes") or []:
            t[f"rule:{k}"] = ""
        s = c.get("source") or {}
        if s:
            t[f"source:{s.get('framework')}:{s.get('id')}"] = ""
    for r in rp.get("risks") or []:
        t[f"risk:{r['risk_id']}"] = str(cat.get("risks", ""))
        for k in r.get("triggered_by") or []:
            t[f"rule:{k}"] = ""
        s = r.get("source") or {}
        if s:
            t[f"source:{s.get('framework')}:{s.get('id')}"] = ""
    for name, r in (v.get("rulesets") or {}).items():
        t[f"ruleset:{r.get('file')}"] = str(r.get("version", ""))
        t[f"rulesetsha:{r.get('sha256')}"] = ""
    for k in CONFIG_KEYS:
        if k in v:
            t[f"config:{k}"] = str(v[k])
    for k, ver in (v.get("evaluators") or {}).items():
        t[f"evaluator:{k}"] = str(ver)
    for k, ver in (v.get("prompts") or {}).items():
        t[f"prompt:{k}"] = str(ver)
    tid = v.get("template_id")
    if tid:
        t[f"ra:{tid}"] = ""
        for p in compose_spec(tid).get("_source_patterns") or []:
            t[f"pattern:{p.get('id')}"] = str(p.get("version", ""))
    return t


def used_by(store: ReportStore, token: str, current: str = "", extra: tuple[str, ...] = ()) -> list[dict]:
    """List the assessments that referenced ``token`` (or any of ``extra``). ``stale`` is True when the version they recorded differs from ``current``."""
    out = []
    want = (token,) + extra
    for s in store.assessments():
        tk = tokens_of(store, s["trace_id"])
        hit = [w for w in want if w in tk]
        if hit:
            rec = tk[hit[0]]
            stale = bool(current and rec and rec != current)
            out.append({"trace": s["trace_id"], "app": s["app_id"], "decision": s["decision"], "recorded": rec, "stale": stale})
    return out


# ---------------------------------------------------------------- registry
def _rel(label: str, href: Optional[str], text: str) -> dict:
    """Build a relationship link entry for a registry row; ``href`` may be None for plain text."""
    return {"label": label, "href": href, "text": text}


def registry_rows(kind: str, store: ReportStore) -> list[dict]:
    """Each row: id, title, status, version, provenance, relationships[], token, current, raw."""
    rows: list[dict] = []
    life = lifecycle()
    pats = patterns()
    if kind == "sources":
        for s in source_items():
            rel = [_rel("lineage", f"/lineage/source/{s['_key']}", "source lineage")]
            rel += [_rel("mitigates", None, x) for x in (s.get("relations") or {}).get("mitigates") or []]
            rows.append({"id": s["_key"], "title": s.get("title"), "status": s.get("kind"), "version": "", "provenance": f"{s['_file']} {s.get('path','')}",
                         "relationships": rel, "token": f"source:{s['_key']}", "current": "", "raw": s})
    elif kind in ("controls", "risks"):
        cur = catalog_version(kind)
        for it in catalog_items(kind):
            iid = item_id(it)
            src = it.get("source") or {}
            rel = []
            if src:
                key = f"{src.get('framework')}:{src.get('id')}"
                rel.append(_rel("source", f"/registry/sources/{key}", key))
                rel.append(_rel("lineage", f"/lineage/source/{key}", "source lineage"))
            rel += [_rel("rule", f"/registry/rulesets/{'controls' if kind == 'controls' else 'risks'}.spectral.yaml", c) for c in _codes(it)]
            fld = "related_controls" if kind == "controls" else "related_risks"
            rel += [_rel("pattern", f"/registry/patterns/{p['id']}", p["id"]) for p in pats if iid in p[fld]]
            rows.append({"id": iid, "title": it.get("title"), "status": it.get("status"), "version": str(it.get("version", "")),
                         "provenance": f"approved by {it.get('approved_by')} at {it.get('approved_at')}; source {src.get('framework','')} {src.get('id','')}",
                         "relationships": rel, "token": f"{kind[:-1]}:{iid}", "current": cur, "raw": it})
    elif kind == "assessment-requirements":
        present = artifact_kind_present(store, ("evidence", "assessment_requirements", "evidence_requirements"))
        for t, k, a in present:
            rows.append({"id": f"{t}:{k}:{a}", "title": "evidence artifact", "status": "", "version": "", "provenance": f"artifact {t}/{k}/{a}",
                         "relationships": [_rel("artifact", f"/artifacts/{t}/{k}/{a}", "JSON"), _rel("assessment", f"/assessments/{t}", t[:12])],
                         "token": "", "current": "", "raw": store.get(t, k, a)})
        if not present:
            for it in catalog_items("controls"):
                for c in it.get("configurations") or []:
                    rows.append({"id": c["id"], "title": f"{item_id(it)}: {c.get('remediation','')}", "status": "mandatory" if c.get("mandatory") else "optional",
                                 "version": str(it.get("version", "")), "provenance": "catalog configuration (no evidence artifacts persisted)",
                                 "relationships": [_rel("control", f"/registry/controls/{item_id(it)}", item_id(it))] +
                                                  [_rel("rule", None, x) for x in c.get("rule_codes") or []],
                                 "token": f"control:{item_id(it)}", "current": catalog_version("controls"), "raw": {**c, "severity_label": "illustrative, not approved policy"}})
    elif kind == "patterns":
        for p in pats:
            e = life.get(p["id"]) or {}
            rel = [_rel("control", f"/registry/controls/{c}", c) for c in p["related_controls"]] + [_rel("risk", f"/registry/risks/{c}", c) for c in p["related_risks"]]
            rel += [_rel("used in RA", f"/registry/ras/{r['id']}", r["id"]) for r in ras() if any(sp.get("id") == p["id"] for sp in r["patterns"])]
            rows.append({"id": p["id"], "title": p["title"], "status": e.get("state") or p["status"], "version": p["version"],
                         "provenance": f"{e.get('source','')} sha256 {str(e.get('sha256',''))[:12]}", "relationships": rel,
                         "token": f"pattern:{p['id']}", "current": p["version"], "raw": {**p, "lifecycle": e}})
    elif kind == "ras":
        for r in ras():
            e = life.get(r["id"]) or {}
            rows.append({"id": r["id"], "title": r["file"], "status": e.get("state") or r["status"], "version": r["version"],
                         "provenance": f"{e.get('source','')}", "relationships": [_rel("pattern", f"/registry/patterns/{p['id']}", f"{p['id']} v{p.get('version')}") for p in r["patterns"]],
                         "token": f"ra:{r['id']}", "current": "", "raw": {**r, "lifecycle": e}})
    elif kind == "rulesets":
        for r in rulesets():
            kk = "controls" if r["id"].startswith("controls") else "risks"
            rel = [_rel("rule", None, c) for c in r["codes"]]
            rel += [_rel(kk[:-1], f"/registry/{kk}/{item_id(i)}", item_id(i)) for i in catalog_items(kk) if set(_codes(i)) & set(r["codes"])]
            rows.append({"id": r["id"], "title": f"{r['rules']} rules", "status": "compiled", "version": r["version"], "provenance": f"MANIFEST sha256 {str(r['sha256'])[:12]} (generated by rule_authoring.compile)",
                         "relationships": rel, "token": f"ruleset:{r['id']}", "current": r["version"], "raw": r})
    elif kind in ("governance-config", "scoring-profiles"):
        for c in config_files():
            if (kind == "scoring-profiles") != (c["id"] == "scoring_profile"):
                continue
            rows.append({"id": c["id"], "title": c["file"], "status": "active", "version": c["version"], "provenance": f"sha256 {c['sha256'][:12]}; label {c['label'] or ''}",
                         "relationships": [], "token": f"config:{c['id']}", "current": c["version"],
                         "raw": {**_yaml(CONFIG / c["file"]), "sha256": c["sha256"]} if kind == "scoring-profiles" else c})
    elif kind == "evaluators":
        seen: dict[str, set] = {}
        for s in store.assessments():
            for k, ver in ((store.get(s["trace_id"], "versions") or {}).get("evaluators") or {}).items():
                seen.setdefault(f"{k}:{ver}", set()).add(s["trace_id"])
        for key, traces in sorted(seen.items()):
            k, ver = key.split(":", 1)
            rows.append({"id": key, "title": f"{k} CLI", "status": "recorded", "version": ver, "provenance": f"recorded in versions artifacts of {len(traces)} assessment(s)",
                         "relationships": [_rel("assessment", f"/assessments/{t}", t[:12]) for t in sorted(traces)], "token": f"evaluator:{k}", "current": ver,
                         "raw": {"evaluator": k, "version": ver, "assessments": sorted(traces)}})
    elif kind == "models-prompts":
        for p in prompts():
            rows.append({"id": p["id"], "title": f"{p['framework']} prompt", "status": "file", "version": p["version"], "provenance": f"sha256 {p['sha256'][:12]}",
                         "relationships": [], "token": f"prompt:{p['name']}", "current": p["version"], "raw": p})
        seen2: set[tuple] = set()
        for s in store.assessments():
            v = store.get(s["trace_id"], "versions") or {}
            for lab in ("model", "decider"):
                m = v.get(lab) or {}
                key = (lab, m.get("provider"), m.get("model"))
                if m and key not in seen2:
                    seen2.add(key)
                    rows.append({"id": f"{lab}:{m.get('provider')}:{m.get('model') or '-'}", "title": f"{lab} record", "status": "recorded", "version": str(m.get("model") or ""),
                                 "provenance": f"first seen in assessment {s['trace_id'][:12]}", "relationships": [_rel("assessment", f"/assessments/{s['trace_id']}", s["trace_id"][:12])],
                                 "token": "", "current": "", "raw": m})
    return rows


def _codes(it: dict) -> list[str]:
    """Sorted unique rule codes of a catalog item, from the item itself and its configurations."""
    codes = list(it.get("rule_codes") or [])
    for c in it.get("configurations") or []:
        codes += c.get("rule_codes") or []
    return sorted(set(codes))


# ---------------------------------------------------------------- lineage (25.5)
def lineage_source(store: ReportStore, sid: str) -> Optional[dict]:
    """Trace one source forward: the controls and risks citing it, the patterns and RA templates that cover them, and the assessments that used them. Returns None if the source is unknown; ``sid`` may be ``framework:id`` or the bare id."""
    srcs = {s["_key"]: s for s in source_items()}
    key = sid if sid in srcs else next((k for k in srcs if k.split(":", 1)[1] == sid), None)
    if key is None:
        return None
    fw, raw_id = key.split(":", 1)
    items = []
    for kind in ("controls", "risks"):
        for it in catalog_items(kind):
            s = it.get("source") or {}
            if s.get("framework") == fw and s.get("id") == raw_id:
                items.append({"kind": kind[:-1], "id": item_id(it), "title": it.get("title"), "rules": _codes(it)})
    pats = patterns()
    pat_rows = [{"id": p["id"], "via": [i["id"] for i in items if i["id"] in p["related_controls"] + p["related_risks"]]} for p in pats]
    pat_rows = [p for p in pat_rows if p["via"]]
    ra_rows = [{"id": r["id"], "patterns": [p["id"] for p in pat_rows if any(sp.get("id") == p["id"] for sp in r["patterns"])]} for r in ras()]
    ra_rows = [r for r in ra_rows if r["patterns"]]
    assessed = []
    for s in store.assessments():
        tk = tokens_of(store, s["trace_id"])
        hit = [i["id"] for i in items if f"{i['kind']}:{i['id']}" in tk]
        if hit:
            assessed.append({"trace": s["trace_id"], "app": s["app_id"], "decision": s["decision"], "via": hit})
    return {"key": key, "source": srcs[key], "items": items, "patterns": pat_rows, "ras": ra_rows, "assessments": assessed}


# ---------------------------------------------------------------- overview (25.1)
def _tasks(data_dir) -> list:
    """List all human tasks stored under ``data_dir`` (imported lazily)."""
    from agip_shared.humantasks import HumanTaskStore
    return HumanTaskStore(data_dir).list()


def framework_health() -> list[dict]:
    """Check that key files of each framework exist and parse; reports per-file OK or ERROR."""
    checks = {
        "rule-authoring": [CATALOGS / "controls.catalog.yaml", CATALOGS / "risks.catalog.yaml", RULESETS / "MANIFEST.yaml", CATALOGS / "sources" / "aigf.json"],
        "calm-generation": [CG / "registry" / "lifecycle.yaml", CG / "templates" / "RA03-LITE.json", CG / "patterns" / "P02-api-gateway.json"],
        "governance-execution": [CONFIG / "scoring_profile.yaml", CONFIG / "gates.yaml", CONFIG / "decision_matrix.yaml", CONFIG / "taxonomy.yaml"],
    }
    out = []
    for fw, files in checks.items():
        res = []
        for f in files:
            try:
                (json.loads(f.read_text(encoding="utf-8")) if f.suffix == ".json" else yaml.safe_load(f.read_text(encoding="utf-8")))
                res.append((f.name, "OK"))
            except Exception as exc:  # noqa: BLE001 - health display only
                res.append((f.name, f"ERROR {type(exc).__name__}"))
        out.append({"framework": fw, "files": res, "ok": all(s == "OK" for _, s in res)})
    return out


def recent_changes(data_dir: Path, limit: int = 10) -> list[dict]:
    """Most recently written artifact files, newest first, up to ``limit``."""
    root = Path(data_dir) / "artifacts"
    files = [p for p in root.glob("*/*/*.json")] if root.is_dir() else []
    files.sort(key=lambda p: -p.stat().st_mtime)
    return [{"trace": p.parts[-3], "kind": p.parts[-2], "id": p.stem,
             "time": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")} for p in files[:limit]]


def active_versions() -> dict[str, Any]:
    """Current versions of catalogs, rulesets, patterns and RA templates."""
    return {"catalogs": {k: catalog_version(k) for k in ("controls", "risks")},
            "rulesets": {r["id"]: r["version"] for r in rulesets()},
            "patterns": {p["id"]: p["version"] for p in patterns()},
            "ras": {r["id"]: r["version"] for r in ras()}}


def overview(store: ReportStore, data_dir: Path) -> dict[str, Any]:
    """Aggregate the figures for the overview page: assessment counts by decision and status, failed runs, waiting human tasks, critical risks, framework health, recent changes and active versions."""
    rows = store.assessments()
    by_dec: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for r in rows:
        by_dec[r["decision"] or "none"] = by_dec.get(r["decision"] or "none", 0) + 1
        by_status[r["status"] or "unknown"] = by_status.get(r["status"] or "unknown", 0) + 1
    crit = 0
    for r in rows:
        rp = store.get(r["trace_id"], "risk_profile") or {}
        crit += sum(1 for x in rp.get("risks") or [] if str(x.get("severity")).lower() == "critical")
    waiting = [t for t in _tasks(data_dir) if t.status in OPEN_STATES]
    return {"total": len(rows), "by_decision": by_dec, "by_status": by_status,
            "failed": [r for r in rows if r["status"] in ("BLOCKED", "FAILED", "ERROR")], "waiting": len(waiting), "critical_risks": crit,
            "health": framework_health(), "recent": recent_changes(data_dir), "versions": active_versions()}


# ---------------------------------------------------------------- workbenches (25.2)
WORKBENCH = {
    "rule-authoring": {"title": "Rule-authoring workbench", "commands": [
        ("python -m rule_authoring.ingest --source aigf|ccc [--extract]", "ingest framework sources and optionally extract draft rules"),
        ("python -m rule_authoring.approval <submit|approve|reject|...> <id> --by ...", "move catalog items through the approval lifecycle"),
        ("python -m rule_authoring.compile [--strict]", "compile approved catalogs into Spectral rulesets and MANIFEST"),
        ("python -m rule_authoring.coverage", "report source-to-rule coverage")]},
    "calm-generation": {"title": "CALM generation workbench", "commands": [
        ("calm_generation patterns | versions", "list patterns and versions"),
        ("calm_generation compose", "compose an RA template from approved patterns"),
        ("calm_generation form | instantiate", "produce an attributes form and instantiate a CALM model"),
        ("calm_generation validate", "validate a CALM model")]},
    "governance": {"title": "Governance execution workbench", "commands": [
        ("python -m governance_execution assess <calm file> [--mode normal|no-llm|replay]", "assess a CALM model"),
        ("python -m governance_execution replay <trace>", "replay a stored assessment from recordings"),
        ("python -m governance_execution show <trace>", "show a stored assessment")]},
}


def workbench_history(name: str, store: ReportStore) -> list[dict]:
    """Change history for a workbench, newest first: catalog approvals (rule-authoring), lifecycle transitions (calm-generation), or assessment runs (anything else)."""
    out: list[dict] = []
    if name == "rule-authoring":
        for kind in ("controls", "risks"):
            for it in catalog_items(kind):
                for h in it.get("history") or []:
                    out.append({"at": str(h.get("at")), "what": f"{item_id(it)} {h.get('from')} -> {h.get('to')}", "by": h.get("by"), "href": f"/registry/{kind}/{item_id(it)}"})
    elif name == "calm-generation":
        for pid, e in lifecycle().items():
            for h in e.get("history") or []:
                out.append({"at": str(h.get("at")), "what": f"{pid} {h.get('from')} -> {h.get('to')}", "by": h.get("by"),
                            "href": f"/registry/{'ras' if e.get('kind') == 'ra' else 'patterns'}/{pid}"})
    else:
        for s in store.assessments():
            out.append({"at": s["time"], "what": f"{s['app_id'] or s['trace_id'][:12]}: {s['decision'] or 'none'} ({s['status']})", "by": s["executor"], "href": f"/assessments/{s['trace_id']}"})
    return sorted(out, key=lambda x: x["at"], reverse=True)


# ---------------------------------------------------------------- execution timeline (25.4)
def execution(store: ReportStore, trace: str, tasks: list) -> dict[str, Any]:
    """Collect the execution timeline of one assessment: run record, versions, steps, Decider outcome counts and the human tasks tied to the trace."""
    rec = store.get(trace, "assessment_record") or {}
    v = store.get(trace, "versions") or {}
    tr = (store.get(trace, "trace") or {}).get("steps") or []
    calls = store.get(trace, "decider_calls") or []
    outcomes: dict[str, int] = {}
    for c in calls:
        outcomes[c.get("outcome") or "?"] = outcomes.get(c.get("outcome") or "?", 0) + 1
    started, finished = rec.get("started"), rec.get("finished")
    return {"record": rec, "versions": v, "steps": tr, "started": started, "finished": finished, "decider_outcomes": outcomes,
            "calm_sha": v.get("app_model_sha256"), "stage_outputs": v.get("stage_outputs") or {}, "error": rec.get("error"),
            "tasks": [t for t in tasks if t.trace_id == trace or t.context.get("trace_id") == trace]}
