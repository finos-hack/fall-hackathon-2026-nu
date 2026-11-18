"""End-to-end run of the three frameworks on Fluxnova (task 27 demo slice).

    uv run python scripts/fluxnova_e2e.py                    # all three lifecycles, human tasks auto-approved via REST
    uv run python scripts/fluxnova_e2e.py --manual           # human tasks wait for Tasklist (http://localhost:8080)
    uv run python scripts/fluxnova_e2e.py --only calm        # one lifecycle: rules | calm | assess

Workflows (BPMN generated from the step lists below, deployed if changed, visible in Cockpit):
  knowledge_lifecycle    ingest -> extract (Strands+Bedrock) -> consistency -> [review] -> record -> compile
  architecture_lifecycle AI pattern drafts (Strands + CALM AI skills) -> [review] -> publish -> compose ->
                         [review] -> publish template -> instantiate V1-V4 (calm generate/validate)
  assessment_lifecycle   one instance per app: validate -> facts -> spectral x2 (parallel) -> gap/risk -> decide -> remediate

The engine holds process state, artifact IDs and paths only. Each run works in _out/fluxnova/<run-id>/ so the
repository catalogs, pattern library and registry are not changed. Exit code 0 only when every lifecycle completed
and the Fluxnova decisions match the Direct_Adapter decisions for the same inputs.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from agip_shared.gateway import ModelGateway, Recorder
from agip_shared.settings import get_settings
from calm_generation import workflow as calm_wf
from calm_generation.calm_cli import RealCalm
from calm_generation.draft_agent import PatternDraftAgent
from governance_execution.adapters.calm import CalmAdapter, default_runner
from governance_execution.exec import factory
from governance_execution.exec.bpmn import WfStep, Workflow
from governance_execution.exec.direct_adapter import DirectAdapter
from governance_execution.exec.fluxnova_client import FluxnovaClient
from governance_execution.exec.fluxnova_executor import FluxnovaExecutor
from governance_execution.exec.fluxnova_runner import run_workflow
from rule_authoring import workflow as rule_wf

ROOT = Path(__file__).resolve().parents[1]
FORMS = ROOT / "governance-execution-framework" / "forms"
EXPECTED = ROOT / "calm-app-generation-framework" / "fixtures" / "variants" / "expected.yaml"
RULE_RECORDINGS = ROOT / "rule-authoring-framework" / "fixtures" / "recordings" / "llm"
VARIANTS = ("v1", "v2", "v3", "v4")

KNOWLEDGE = Workflow("knowledge_lifecycle", "Knowledge Lifecycle (Rule Authoring)", (
    WfStep("ingest_sources", "Ingest AIGF + CCC sources"),
    WfStep("extract_rules", "Extract DRAFT rules (Strands + Bedrock)"),
    WfStep("check_consistency", "Catalog consistency check"),
    WfStep("review_rules", "Review extracted rules", kind="user", candidate_group="rule-reviewers"),
    WfStep("record_review", "Record review decision"),
    WfStep("compile_rulesets", "Compile Spectral rulesets"),
))
ARCHITECTURE = Workflow("architecture_lifecycle", "Architecture Lifecycle (CALM Generation)", (
    WfStep("draft_patterns", "AI-draft CALM patterns (Strands + CALM AI skills)"),
    WfStep("review_patterns", "Review pattern drafts", kind="user", candidate_group="architects"),
    WfStep("approve_patterns", "Approve and publish patterns"),
    WfStep("compose_template", "Compose RA03-LITE template"),
    WfStep("review_template", "Review composed template", kind="user", candidate_group="architects"),
    WfStep("publish_template", "Publish RA03-LITE"),
    WfStep("instantiate_apps", "Instantiate apps V1-V4 (calm generate + validate)"),
))
REVIEWERS = {"review_rules": ("rule-reviewer", "reviewer"), "review_patterns": ("architecture-review", "architect"),
             "review_template": ("architecture-review", "architect")}
CLIENT: FluxnovaClient | None = None      # set in main(); used to look up who completed a Tasklist task


def log(msg: str) -> None:
    """Print a timestamped progress line, flushed so it shows up immediately."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def on_step(rec: dict[str, Any]) -> None:
    """Step callback: log the step name, status and any error."""
    extra = f" ({rec['error']})" if rec.get("error") else ""
    log(f"  {rec['step']:<20} {rec['status']}{extra}")


def auto_reviewer(task: dict[str, Any], _vars: dict[str, Any]) -> dict[str, Any]:
    """Complete a human task automatically with an APPROVED outcome attributed to the configured reviewer for that task key (demo mode only)."""
    by, role = REVIEWERS.get(task["taskDefinitionKey"], ("reviewer", "reviewer"))
    log(f"  {task['taskDefinitionKey']:<20} user task completed via REST by {by} ({role})")
    return {f"{task['taskDefinitionKey']}_by": by, f"{task['taskDefinitionKey']}_role": role,
            f"{task['taskDefinitionKey']}_outcome": "APPROVED",
            f"{task['taskDefinitionKey']}_rationale": "automated demo review"}


def reviewer(vars_: dict[str, Any], task: str) -> tuple[str, str, str, bool]:
    """Read the human decision. A task completed in Tasklist without variables counts as APPROVED by the user who
    claimed and completed it (Tasklist assignee), or 'tasklist-user' if it was completed unclaimed."""
    by = vars_.get(f"{task}_by")
    if not by and CLIENT is not None and vars_.get("_instance_id"):
        by = CLIENT.human_task_completer(vars_["_instance_id"], task)
    return (by or "tasklist-user", vars_.get(f"{task}_role") or "reviewer",
            vars_.get(f"{task}_rationale") or "approved in Tasklist",
            (vars_.get(f"{task}_outcome") or "APPROVED") == "APPROVED")


def decider_up(url: str) -> bool:
    """True if the decider answers GET /health within 5 seconds."""
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/health", timeout=5):
            return True
    except Exception:
        return False


def run_rules(client: FluxnovaClient, run_dir: Path, a: argparse.Namespace, s: Any, human: dict[str, Any]) -> dict[str, Any]:
    """Drive the rule-authoring lifecycle through Fluxnova; each step runs the matching workflow function and returns its truncated JSON result as process variables."""
    ws = rule_wf.init_workspace(run_dir / "rules")
    from rule_authoring import extract_sources as es_mod, extraction as ex_mod, scoring
    if a.extract == "bedrock":
        from agip_shared.gateway.runtime_strands import StrandsRuntime
        rt = StrandsRuntime(profile=s.aws_profile, temperature=0.1,
                            steering=ex_mod.steering_check(es_mod.load_dimensions(), ex_mod.load_fields()))
        gw = ModelGateway("bedrock", s.bedrock_model_id, s.aws_region, Recorder(ws.root / "llm-records"), rt)
        scorer = scoring.from_settings(s, "http" if decider_up(s.decider_url) else "replay",
                                       Path(s.data_dir) / "llm-records" / "decider-scores")
    else:
        gw = ModelGateway("replay", recorder=Recorder(RULE_RECORDINGS))
        scorer = scoring.from_settings(s, "replay")
    ids = {"aigf": a.aigf_ids, "ccc": a.ccc_ids}
    out: dict[str, Any] = {}

    def keep(name):
        """Build the handler for one rule-authoring step."""
        def h(v):
            """Run the step, store its result in `out`, and return it (truncated to 3500 chars) as a process variable."""
            out[name] = {"ingest_sources": lambda: rule_wf.ingest_sources(ws),
                         "extract_rules": lambda: rule_wf.extract_rules(ws, gw, ids, strict=a.strict_extraction, scorer=scorer),
                         "check_consistency": lambda: rule_wf.check_consistency(ws),
                         "record_review": lambda: rule_wf.record_review(ws, *reviewer(v, "review_rules")[:2],
                                                                         "APPROVED" if reviewer(v, "review_rules")[3] else "REJECTED",
                                                                         reviewer(v, "review_rules")[2]),
                         "compile_rulesets": lambda: rule_wf.compile_rulesets(ws)}[name]()
            return {f"out_{name}": json.dumps(out[name], sort_keys=True)[:3500]}
        return h
    names = [st.name for st in KNOWLEDGE.steps if st.kind == "service"]
    r = run_workflow(client, KNOWLEDGE, {n: keep(n) for n in names}, {"run_id": run_dir.name, "workspace": str(ws.root)},
                     business_key=run_dir.name, on_step=on_step, **human)
    return {"instance": r.instance_id, "version": r.version, "status": r.status, "error": r.error, "outputs": out,
            "rulesets_dir": str(ws.rulesets)}


def run_calm(client: FluxnovaClient, run_dir: Path, a: argparse.Namespace, s: Any, human: dict[str, Any]) -> dict[str, Any]:
    """Drive the CALM generation lifecycle (draft, approve, compose, publish, instantiate) through Fluxnova."""
    ws = calm_wf.init_workspace(run_dir / "calm")
    calm_adapter = CalmAdapter(s.calm_bin, 120, default_runner)
    agent = None
    if a.draft == "ai":
        from agip_shared.gateway.runtime_strands import StrandsRuntime
        agent = PatternDraftAgent(StrandsRuntime(max_tokens=8192, profile=s.aws_profile), s.bedrock_model_id, s.aws_region,
                                  calm_adapter.validate_pattern, max_rounds=a.draft_rounds,
                                  cache_dir=Path(s.data_dir) / "llm-records" / "pattern-drafts")
    import shutil
    calm = RealCalm(shutil.which(s.calm_bin) or s.calm_bin)   # resolves calm.cmd on Windows
    out: dict[str, Any] = {}

    def step(name):
        """Build the handler for one CALM generation step."""
        def h(v):
            """Run the step, store its result in `out`, and return it (truncated to 3500 chars) as a process variable."""
            if name == "draft_patterns":
                res = calm_wf.draft_patterns(ws, agent)
            elif name == "approve_patterns":
                by, role, why, ok = reviewer(v, "review_patterns")
                res = calm_wf.approve_patterns(ws, by, role, why, ok)
            elif name == "compose_template":
                res = calm_wf.compose_template(ws)
            elif name == "publish_template":
                by, role, why, ok = reviewer(v, "review_template")
                res = calm_wf.publish_template(ws, by, role, why, ok)
            else:
                res = {}
                for vid, f in _attribute_files(a).items():
                    f2, meta = _with_requirements(f, ws, s)
                    res[vid] = {**calm_wf.instantiate_app(ws, f2, calm), **meta}
            out[name] = res
            return {f"out_{name}": json.dumps(res, sort_keys=True)[:3500]}
        return h
    names = [st.name for st in ARCHITECTURE.steps if st.kind == "service"]
    r = run_workflow(client, ARCHITECTURE, {n: step(n) for n in names}, {"run_id": run_dir.name, "workspace": str(ws.root)},
                     business_key=run_dir.name, on_step=on_step, **human)
    return {"instance": r.instance_id, "version": r.version, "status": r.status, "error": r.error, "outputs": out,
            "apps_dir": str(ws.apps)}


def _attribute_files(a: argparse.Namespace) -> dict[str, Path]:
    """User attribute files (--attributes) keyed by app label, else the fixed demo forms V1-V4."""
    if a.attributes:
        return {Path(f).name.split(".")[0]: Path(f) for f in a.attributes}
    return {vid: FORMS / f"{vid}.attributes.yaml" for vid in VARIANTS}


def _with_requirements(f: Path, ws: Any, s: Any) -> tuple[Path, dict[str, Any]]:
    """If the attributes file has free-text ``requirements``, let the Decider fill its empty enum attributes (same
    policy as the dashboard). Returns the completed file in the workspace and the inputs for the assessment record."""
    given = yaml.safe_load(f.read_text(encoding="utf-8"))
    text = str(given.get("requirements") or "").strip()
    if not text:
        return f, {}
    from calm_generation import attributes as attrs
    from governance_execution.adapters.decider import DeciderGateway
    from governance_execution.units.requirements import infer_values
    tpl_text = next(ws.templates.glob("*.json")).read_text(encoding="utf-8")
    form = attrs.form_for(json.loads(tpl_text), tpl_text, "PUBLISHED")
    form["values"] = dict(given.get("values") or {})
    picked = {o["unique_id"]: o.get("selected") for o in given.get("options") or []}
    for o in form["options"]:
        o["selected"] = picked.get(o["unique_id"])
    policy = yaml.safe_load((ROOT / "governance-execution-framework" / "config" / "decider_policy.yaml").read_text(encoding="utf-8"))
    provider = "http" if decider_up(s.decider_url) else "fixture"
    inf = infer_values(form, text, DeciderGateway.from_settings(s.model_copy(update={"decider_provider": provider}), policy),
                       rules=attrs.load_consistency(form["template"]["id"]))
    if inf.unresolved:
        raise ValueError(f"{f.name}: " + "; ".join(inf.unresolved))
    given["values"] = {**form["values"], **inf.values}
    given["options"] = [{**o, "selected": inf.options.get(o["unique_id"], o.get("selected"))} for o in form["options"]]
    out = ws.root / "forms" / f.name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(given, sort_keys=False), encoding="utf-8")
    opts = {o["unique_id"]: o.get("selected") for o in given.get("options") or []}
    return out, {"requirements": text, "inputs": {"values": given["values"], "options": opts, "inferred": inf.provenance}}


def run_assess(client: FluxnovaClient, run_dir: Path, a: argparse.Namespace, s: Any, apps: dict[str, Path],
               rulesets_dir: Path | None, template_dir: Path | None = None,
               meta: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Assess each app with both the Fluxnova and the direct executors so their results can be compared. With decider 'auto', uses the HTTP decider if reachable, else the fixture."""
    provider = a.decider
    if provider == "auto":
        provider = "http" if decider_up(s.decider_url) else "fixture"
        log(f"  Decider {'reachable' if provider == 'http' else 'unreachable'} at {s.decider_url}: using {provider}")
    mode = "normal" if a.extract == "bedrock" or a.draft == "ai" else "replay"
    st = s.model_copy(update={"decider_provider": provider, **({"model_provider": "replay"} if mode == "replay" else {})})
    res: dict[str, Any] = {"decider": provider, "apps": {}}
    for vid, path in apps.items():
        app = json.loads(path.read_text(encoding="utf-8"))
        row: dict[str, Any] = {}
        for label, ex in (("fluxnova", FluxnovaExecutor(client)), ("direct", DirectAdapter())):
            coord, _ = factory.build(mode, settings=st, data_dir=Path(a.data_dir) if a.data_dir else None, cli="real",
                                     decider_provider=provider)
            if rulesets_dir:
                coord.ctx.rulesets = {lane: rulesets_dir / f"{lane}.spectral.yaml" for lane in ("controls", "risks")}
            if template_dir:
                coord.ctx.config = {**coord.ctx.config, "template_dir": str(template_dir)}
            out = coord.run(app, executor=ex, template_id="RA03-LITE", source={"app_id": path.stem, "file": path.name,
                                                                                "executor": label, **(meta or {}).get(vid, {})})
            row[label] = {"trace_id": out.trace_id, "status": out.status, "validation": out.validation_status,
                          "decision": out.decision, "error": out.error,
                          "instance": ex.runs[-1].instance_id if label == "fluxnova" and ex.runs else None}
            if label == "fluxnova":
                log(f"  {vid}: {out.status} / {out.validation_status} / {out.decision}  trace {out.trace_id}  instance {row[label]['instance']}")
        f, d = row["fluxnova"], row["direct"]
        row["parity"] = all(f[k] == d[k] for k in ("status", "validation", "decision"))
        res["apps"][vid] = row
    return res


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: run the selected lifecycles (rules, calm, assess) end to end. Returns the exit code."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=("rules", "calm", "assess"), action="append")
    ap.add_argument("--manual", action="store_true", help="wait for human tasks in Tasklist instead of auto-completing")
    ap.add_argument("--draft", choices=("ai", "canonical"), default="ai", help="pattern drafts: Strands agent or canonical copy")
    ap.add_argument("--draft-rounds", type=int, default=4)
    ap.add_argument("--attributes", nargs="+", metavar="FILE",
                    help="attribute files to instantiate (optional free-text 'requirements:'); default: demo forms V1-V4")
    ap.add_argument("--extract", choices=("bedrock", "replay"), default="bedrock", help="rule extraction model provider")
    ap.add_argument("--aigf-ids", nargs="*", default=["mi-24", "mi-17", "ri-24"], help="AIGF items to extract (empty: none)")
    ap.add_argument("--ccc-ids", nargs="*", default=[], help="CCC items to extract")
    ap.add_argument("--strict-extraction", action="store_true", help="fail the lifecycle when the model output is rejected")
    ap.add_argument("--decider", choices=("auto", "http", "fixture"), default="auto")
    ap.add_argument("--data-dir", default=None, help="assessment store (default: DATA_DIR, the dashboard's store)")
    ap.add_argument("--run-id", default=None)
    a = ap.parse_args(argv)
    only = set(a.only or ("rules", "calm", "assess"))

    s = get_settings()
    client = FluxnovaClient(s.fluxnova_url, timeout_s=30)
    global CLIENT
    CLIENT = client
    if not client.available():
        log(f"Fluxnova not reachable at {s.fluxnova_url}")
        return 2
    run_id = a.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = ROOT / "_out" / "fluxnova" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    human = {"user_handler": None if a.manual else auto_reviewer, "wait_for_humans": a.manual,
             "timeout_s": 3600 if a.manual else 900}
    log(f"Fluxnova {client.health()} at {s.fluxnova_url}; run {run_id}; workspace {run_dir}")
    report: dict[str, Any] = {"run_id": run_id, "engine": client.health(), "started": datetime.now(timezone.utc).isoformat()}
    t0 = time.time()
    ok = True

    rulesets_dir = None
    if "rules" in only:
        log("Knowledge Lifecycle (Rule Authoring)")
        report["rules"] = r = run_rules(client, run_dir, a, s, human)
        ok &= r["status"] == "COMPLETED"
        rulesets_dir = Path(r["rulesets_dir"]) if r["status"] == "COMPLETED" else None
    apps = {vid: ROOT / "calm-app-generation-framework" / "fixtures" / "variants" / f"invoice-lite-{vid}.json" for vid in VARIANTS}
    template_dir = None
    meta: dict[str, dict[str, Any]] = {}
    if "calm" in only and ok:
        log(f"Architecture Lifecycle (CALM Generation, drafts: {a.draft})")
        report["calm"] = c = run_calm(client, run_dir, a, s, human)
        ok &= c["status"] == "COMPLETED"
        if c["status"] == "COMPLETED":
            apps = {vid: Path(v["path"]) for vid, v in c["outputs"]["instantiate_apps"].items()}
            meta = {vid: {k: v[k] for k in ("requirements", "inputs") if k in v} for vid, v in c["outputs"]["instantiate_apps"].items()}
            template_dir = Path(c["outputs"]["compose_template"]["path"]).parent
    if "assess" in only and ok:
        log("Assessment Lifecycle (Governance Execution), Fluxnova vs Direct_Adapter")
        report["assess"] = g = run_assess(client, run_dir, a, s, apps, rulesets_dir, template_dir, meta)
        exp = yaml.safe_load(EXPECTED.read_text(encoding="utf-8")) if EXPECTED.exists() else {}
        g["expected"] = exp
        ok &= all(v["parity"] for v in g["apps"].values())

    report["seconds"] = round(time.time() - t0)
    report["ok"] = bool(ok)
    (run_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    log(f"{'OK' if ok else 'FAILED'} in {report['seconds']}s; report {run_dir / 'report.json'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
