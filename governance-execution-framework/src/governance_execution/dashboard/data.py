"""Read model for the Dashboard: persisted artifacts only (Req 25.1)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from ..core import trace as trace_core
from ..store.artifacts import FileArtifactStore

COMPOSE_DIR = Path(__file__).resolve().parents[4] / "calm-app-generation-framework" / "templates"
_TRACE = re.compile(r"^[0-9a-f]{32}$")
RANK = {"critical": 4, "Critical": 4, "high": 3, "High": 3, "medium": 2, "Medium": 2, "low": 1, "Low": 1}


class ReportStore:
    """Read-only view over persisted assessment artifacts.

    Layout on disk: ``<data_dir>/<trace_id>/<kind>/<artifact_id>.json``, where
    ``trace_id`` is a 32-char hex id and ``kind`` is an artifact type such as
    ``decision`` or ``risk_profile``. The dashboard only reads through this
    class and never writes, so reports always reflect what was persisted.
    """

    def __init__(self, data_dir: str | Path):
        """Open the artifact store rooted at ``data_dir``."""
        self.files = FileArtifactStore(data_dir)

    def traces(self) -> list[str]:
        """Return the ids of all assessments, i.e. trace folders that contain a ``versions`` artifact."""
        root = self.files.root
        if not root.is_dir():
            return []
        return sorted(p.name for p in root.iterdir() if _TRACE.match(p.name) and (p / "versions").is_dir())

    def kinds(self, trace: str) -> dict[str, list[str]]:
        """Map each artifact kind stored for ``trace`` to its sorted artifact ids."""
        d = self.files.root / trace
        return {k.name: sorted(f.stem for f in k.glob("*.json")) for k in sorted(d.iterdir()) if k.is_dir()} if d.is_dir() else {}

    def get(self, trace: str, kind: str, aid: Optional[str] = None) -> Any:
        """Load one artifact. Without ``aid`` the first id of that kind is used; returns None if the kind is absent."""
        ids = self.kinds(trace).get(kind) or []
        if not ids:
            return None
        return self.files.get(trace, kind, aid or ids[0])

    def summary(self, trace: str) -> dict[str, Any]:
        """Build the one-row listing summary for an assessment from its ``versions`` artifact."""
        v = self.get(trace, "versions") or {}
        mtime = (self.files.root / trace / "versions").stat().st_mtime
        return {"trace_id": trace, "app_id": (v.get("source") or {}).get("app_id"), "decision": v.get("decision"),
                "status": v.get("assessment_status") or v.get("status"), "validation_status": v.get("validation_status"), "executor": v.get("executor"), "executor_note": v.get("executor_note"),
                "mode": v.get("mode"), "replay_of": (v.get("source") or {}).get("replay_of"),
                "time": datetime.fromtimestamp(mtime, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"), "_mtime": mtime}

    def assessments(self) -> list[dict[str, Any]]:
        """Return summaries of all assessments, newest first."""
        return sorted((self.summary(t) for t in self.traces()), key=lambda s: -s["_mtime"])

    def bundle(self, trace: str) -> dict[str, Any]:
        """Load every known artifact kind for ``trace`` into one dict (missing kinds map to None)."""
        kinds = ("app_model", "calm_validation", "facts", "decider_calls", "spectral_controls_parsed", "spectral_risks_parsed",
                 "control_gap", "risk_profile", "decision", "remediation", "versions", "trace", "unit_error")
        return {k: self.get(trace, k) for k in kinds}


def compose_spec(template_id: Optional[str]) -> dict[str, Any]:
    """Load the template's ``.compose.yaml`` (empty if absent) and attach its source patterns from the template JSON as ``_source_patterns``. Returns {} without a template id."""
    if not template_id:
        return {}
    f = COMPOSE_DIR / f"{template_id}.compose.yaml"
    spec = yaml.safe_load(f.read_text(encoding="utf-8")) if f.is_file() else {}
    tf = COMPOSE_DIR / f"{template_id}.json"
    if tf.is_file():
        spec["_source_patterns"] = json.loads(tf.read_text(encoding="utf-8"))["metadata"]["source-patterns"]
    return spec


def graph(b: dict[str, Any]) -> trace_core.Graph:
    """Build the trace graph for an assessment bundle, using its recorded template's compose spec."""
    return trace_core.build(b, compose_spec((b.get("versions") or {}).get("template_id")))


def worst_by_element(b: dict[str, Any]) -> dict[str, int]:
    """Map each CALM element id to the highest severity rank (1-4) among failed controls, risk findings and CALM validation errors that point at it. CALM errors always rank 4."""
    app = b.get("app_model") or {}
    out: dict[str, int] = {}

    def bump(path: str, rank: int) -> None:
        """Raise the element's rank to ``rank`` if the finding path resolves to an element."""
        eid = trace_core.element_of(path, app)
        if eid:
            out[eid] = max(out.get(eid, 0), rank)

    for c in (b.get("control_gap") or {}).get("controls") or []:
        if c["status"] == "FAIL":
            for f in c.get("findings") or []:
                bump(f["path"], RANK.get(c.get("gap_contribution") or "", 1))
    for r in (b.get("risk_profile") or {}).get("risks") or []:
        for f in r.get("findings") or []:
            bump(f["path"], RANK.get(r["severity"], 1))
    for e in (b.get("calm_validation") or {}).get("errors") or []:
        m = re.match(r"^/nodes/([^/]+)", e.get("path") or "")
        if m:
            out[m.group(1)] = 4
    return out


def _mid(s: str) -> str:
    """Make a string safe to use as a Mermaid node id."""
    return re.sub(r"[^A-Za-z0-9_]", "_", s)


def architecture_mermaid(b: dict[str, Any]) -> str:
    """Render the CALM model as a Mermaid flowchart with nodes coloured by their worst finding."""
    app = b.get("app_model") or {}
    worst = worst_by_element(b)
    lines = ["flowchart LR"]
    for n in app.get("nodes") or []:
        uid = n.get("unique-id", "?")
        label = f"{n.get('name', uid)}<br/>{n.get('node-type', '')}".replace('"', "'")
        cls = {4: "crit", 3: "high", 2: "med", 1: "low"}.get(worst.get(uid, 0), "ok")
        lines.append(f'  {_mid(uid)}["{label}"]:::{cls}')
    for r in app.get("relationships") or []:
        c = (r.get("relationship-type") or {}).get("connects")
        if c:
            lines.append(f"  {_mid(c['source']['node'])} --> {_mid(c['destination']['node'])}")
    lines += ["  classDef ok fill:#d9f2d9,stroke:#2e7d32", "  classDef low fill:#fff8c4,stroke:#9e9d24",
              "  classDef med fill:#ffe0b2,stroke:#ef6c00", "  classDef high fill:#ffccbc,stroke:#d84315",
              "  classDef crit fill:#ef9a9a,stroke:#b71c1c"]
    return "\n".join(lines)


def flow_mermaid(b: dict[str, Any], executor: str) -> str:
    """Render the assessment pipeline as a Mermaid flowchart with each step coloured by its recorded status; the blocked variant skips straight from CALM validation to the decision."""
    steps = [s for s in ((b.get("trace") or {}).get("steps") or [])]
    status = {s["step"]: s["status"] for s in steps}

    def n(name: str, label: str) -> str:
        """Mermaid node definition for a pipeline step, labelled with its status ('not run' if absent)."""
        st = status.get(name)
        cls = "ok" if st == "OK" else "err" if st == "ERROR" else "skip"
        return f'{name}["{label}<br/>{st or "not run"}"]:::{cls}'

    lines = ["flowchart LR", f'  start(("{executor}"))',
             "  start --> " + n("validate_calm", "validate CALM")]
    if "extract_facts" in status:
        lines += ["  validate_calm --> " + n("extract_facts", "facts + Decider"),
                  "  extract_facts --> " + n("spectral_controls", "Spectral controls"),
                  "  extract_facts --> " + n("spectral_risks", "Spectral risks"),
                  "  spectral_controls --> " + n("control_gap", "control gap"),
                  "  spectral_risks --> " + n("risk_profile", "risk profile"),
                  "  control_gap --> " + n("decide", "gates + matrix"), "  risk_profile --> decide"]
    else:
        lines.append("  validate_calm -->|blocked| " + n("decide", "gates + matrix"))
    lines += ["  decide --> " + n("remediate", "remediation"),
              "  classDef ok fill:#d9f2d9,stroke:#2e7d32", "  classDef err fill:#ef9a9a,stroke:#b71c1c",
              "  classDef skip fill:#eeeeee,stroke:#9e9e9e"]
    return "\n".join(lines)


def risk_matrix(b: dict[str, Any], scoring: dict[str, Any]) -> list[list[dict[str, Any]]]:
    """Rows likelihood 5..1, columns impact 1..5; each cell: severity label and risks placed there."""
    placed: dict[tuple[int, int], list[str]] = {}
    for r in (b.get("risk_profile") or {}).get("risks") or []:
        placed.setdefault((r["likelihood"], r["impact"]), []).append(r["risk_id"])
    return [[{"l": l, "i": i, "severity": scoring["severity_matrix"][l][i - 1], "risks": placed.get((l, i), [])}
             for i in range(1, 6)] for l in range(5, 0, -1)]
