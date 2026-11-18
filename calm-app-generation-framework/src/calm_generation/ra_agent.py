"""Generate a reference architecture from a description, reusing only published patterns.

The Strands agent proposes a compose spec (JSON); the CALM Composer, ``calm validate -p`` and the question checks
(``ra_builder.preview``) judge it, and their errors go back to the agent in the next round (at most ``max_rounds``,
driven in code: small models do not stop a tool loop on their own). The agent cannot add nodes or metadata: the
Composer only merges what the patterns declare. Requirement questions are then derived from the template by rules
(``questions_for``), so every free field is asked. The result is a proposal: it is saved as a DRAFT and published only
after a human approves it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from . import attributes as attrs
from . import lifecycle as lc
from . import pattern_library as pl
from . import ra_builder as rb

Complete = Callable[[str, dict[str, Any]], Any]     # (prompt, input) -> model output (dict or text)
EXAMPLE_RA = "RA03-LITE"

PROMPT = """You design a reference architecture (RA) template by composing existing CALM architecture patterns.
You may ONLY reuse the published patterns listed in INPUT.patterns. You cannot add nodes, node types or metadata fields.
Return ONE JSON object (the compose spec) and nothing else, with these keys:
  ra_id, title, description, patterns, components, relationships, options

Rules:
- patterns: the ids of the patterns you use.
- components: each {{"id", "from", "name", "description", "bind"?, "option"?}}. "from" lists pattern nodes as
  "<pattern id>/<node id>". Only nodes WITH fields (not ports) can be components. Listing the same node id from several
  patterns in one component merges them (an agent built from P12/agent and P14/agent has the fields of both).
  Component ids are lowercase-kebab-case and unique.
- bind: fixes a field for this RA, e.g. {{"decision_impact": "high"}}. Only fields that the component's pattern nodes
  declare; the value must be allowed by the field schema. Leave a field unbound when each application should choose it.
- relationships: either {{"id", "from": "<pattern id>/<relationship id>", "map": {{"<pattern source node>": "<component>",
  "<pattern destination node>": "<component>"}}}} to reuse a pattern relationship (ports are filled by mapping them to a
  component), or {{"id", "connects": ["<component>", "<component>"], "description"}} for plain wiring. Every component
  should be connected. Relationship ids are lowercase-kebab-case and unique.
- options (design choices each application makes): {{"id", "type": "oneOf"|"anyOf", "description",
  "choices": [{{"description", "nodes": [component ids], "relationships": [relationship ids]}}]}}. Components and
  relationships that belong to an option carry "option": "<option id>". oneOf choices must list the same number of
  nodes and the same number of relationships. At most one anyOf option. An anyOf choice may be empty (nodes: [],
  relationships: []) to mean "not present". Use options only where the description asks for a real alternative
  (for example: with or without a human approval step, with or without an audit service).
- Use names and descriptions in business terms. No product or cloud vendor names.

Worked example (the {example} spec, as YAML):
{example_spec}
"""


@dataclass
class Generated:
    ok: bool = False
    rounds: int = 0
    compose_text: str = ""
    questions_text: str = ""
    preview: Optional[rb.Preview] = None
    log: list[dict[str, Any]] = field(default_factory=list)      # per round: errors returned to the agent
    error: Optional[str] = None


def pattern_summaries(patterns: dict[str, Any], registry: Path = lc.REGISTRY) -> list[dict[str, Any]]:
    """Compact view of the published patterns for the prompt: nodes (fields or port) and relationships."""
    entries = lc.load(registry).get("entries") or {}
    out = []
    for pid, p in sorted(patterns.items()):
        if (entries.get(pid) or {}).get("state") not in lc.COMPOSABLE:
            continue
        nodes, rels = [], []
        for n in ((p.get("properties") or {}).get("nodes") or {}).get("prefixItems") or []:
            pr = n.get("properties") or {}
            meta = ((pr.get("metadata") or {}).get("properties")) or {}
            node = {"id": pr["unique-id"]["const"], "type": pr["node-type"]["const"], "name": pr["name"]["const"]}
            node.update({"fields": meta} if meta else {"port": True})
            nodes.append(node)
        for r in ((p.get("properties") or {}).get("relationships") or {}).get("prefixItems") or []:
            pr = r.get("properties") or {}
            c = pr["relationship-type"]["const"]["connects"]
            rels.append({"id": pr["unique-id"]["const"], "from": c["source"]["node"], "to": c["destination"]["node"]})
        md = p.get("metadata") or {}
        out.append({"id": pid, "title": p.get("title"), "description": p.get("description"), "nodes": nodes,
                    "relationships": rels, "related_controls": md.get("related_controls") or [],
                    "related_risks": md.get("related_risks") or []})
    return out


def _as_spec(out: Any) -> Optional[dict[str, Any]]:
    if isinstance(out, dict):
        return out
    text = str(out or "")
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    body = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    try:
        v = json.loads(body)
        return v if isinstance(v, dict) else None
    except ValueError:
        return None


def _humanise(s: str) -> str:
    return re.sub(r"[_-]+", " ", s).strip()


def questions_for(template: dict[str, Any], form: dict[str, Any]) -> list[dict[str, Any]]:
    """One question per free field and per option of the template (rule-based, so every free field is asked)."""
    names = {d["properties"]["unique-id"]["const"]: d["properties"]["name"]["const"] for d, _ in attrs.iter_node_defs(template)}
    qs: list[dict[str, Any]] = []
    for o in form.get("options") or []:
        sel = (lambda s: s) if o["type"] == "oneOf" else (lambda s: [s])
        qs.append({"id": re.sub(r"[^a-z0-9]+", "_", o["unique_id"].lower()).strip("_"), "label": o["prompt"],
                   "answers": {slug: {"label": desc, "options": {o["unique_id"]: sel(slug)}} for slug, desc in o["choices"].items()}})
    for a in form.get("attributes") or []:
        node, fld = a["target"]["node"], a["target"]["field"]
        what = f"the {_humanise(fld)} of the {names.get(node, _humanise(node))}"
        qid = a["name"].lower()
        if a["type"] == "enum":
            qs.append({"id": qid, "label": f"What is {what}?",
                       "answers": {v: {"label": _humanise(str(v)).capitalize(), "set": {a["name"]: v}} for v in a["allowed"]}})
        elif a["type"] in ("number", "integer"):
            bounds = f" (minimum {a['min']})" if "min" in a else ""
            qs.append({"id": qid, "label": f"What is {what}?", "help": f"A number{bounds}.", "type": "number", "attribute": a["name"]})
        elif a["type"] == "boolean":
            qs.append({"id": qid, "label": f"Is {what} enabled?",
                       "answers": {"yes-value": {"label": "Yes", "set": {a["name"]: True}},
                                   "no-value": {"label": "No", "set": {a["name"]: False}}}})
        # free-text string fields stay in the Advanced section of Generate CALM
    return qs


def _option_hints(spec: dict[str, Any]) -> list[str]:
    """Concrete fix for unequal oneOf choices: the counts per choice and how the worked example balances them."""
    out = []
    for o in spec.get("options") or []:
        if not isinstance(o, dict) or o.get("type") != "oneOf":
            continue
        ch = [c for c in o.get("choices") or [] if isinstance(c, dict)]
        for k in ("nodes", "relationships"):
            counts = [len(c.get(k) or []) for c in ch]
            if len(set(counts)) > 1:
                desc = ", ".join(f"'{c.get('description')}' has {n}" for c, n in zip(ch, counts))
                out.append(f"option {o.get('id')}: every choice must list exactly {max(counts)} {k} ({desc}). Balance them: "
                           f"give the shorter choice another {k[:-1]} that carries option {o.get('id')} (the worked example "
                           f"adds r-payment-api-notifies-approval, a 'connects' relationship, for this), or remove one from "
                           f"the longer choice. Every {k[:-1]} named in a choice must carry \"option\": \"{o.get('id')}\".")
    return out


def generate(description: str, ra_id: str, complete: Complete, *, calm: Any = None, max_rounds: int = 4,
             pattern_ids: Optional[list[str]] = None, patterns_dir: Path = pl.PATTERN_DIR,
             registry: Path = lc.REGISTRY, templates_dir: Optional[Path] = None) -> Generated:
    """Draft -> compose/validate -> feedback loop; returns the compose spec and derived questions (nothing is saved)."""
    g = Generated()
    pats = pl.load_patterns(patterns_dir)
    summaries = [s for s in pattern_summaries(pats, registry) if not pattern_ids or s["id"] in pattern_ids]
    if not summaries:
        g.error = "no published pattern to compose from"
        return g
    ex_file = Path(templates_dir or pl.FRAMEWORK_ROOT / "templates") / f"{EXAMPLE_RA}.compose.yaml"
    prompt = PROMPT.format(example=EXAMPLE_RA, example_spec=ex_file.read_text(encoding="utf-8") if ex_file.is_file() else "{}")
    feedback: list[str] = []
    for rnd in range(1, max_rounds + 1):
        g.rounds = rnd
        inp = {"ra_id": ra_id, "description": description, "patterns": summaries, "round": rnd,
               "previous_problems": feedback}
        try:
            spec = _as_spec(complete(prompt, inp))
        except Exception as exc:  # noqa: BLE001 - model or network failure is reported, never raised to the page
            g.error = f"model unavailable: {type(exc).__name__}: {str(exc)[:200]}"
            return g
        if spec is None:
            feedback = ["the reply was not a JSON object; return only the compose spec as JSON"]
            g.log.append({"round": rnd, "errors": feedback})
            continue
        spec.update(ra_id=ra_id, version=1)
        spec.setdefault("description", description)
        compose_text = yaml.safe_dump({k: spec[k] for k in ("ra_id", "version", "title", "description", "patterns",
                                                            "components", "relationships", "options") if k in spec},
                                      sort_keys=False, allow_unicode=True, width=120)
        pv = rb.preview(compose_text, "", "", patterns_dir=patterns_dir, registry=registry, calm=calm)
        if pv.ok:
            qs = questions_for(pv.template, pv.form)
            questions_text = yaml.safe_dump({"questions": qs}, sort_keys=False, allow_unicode=True, width=120)
            pv = rb.preview(compose_text, questions_text, "", patterns_dir=patterns_dir, registry=registry, calm=calm)
            g.log.append({"round": rnd, "errors": pv.errors})
            g.ok, g.compose_text, g.questions_text, g.preview = pv.ok, compose_text, questions_text, pv
            return g
        feedback = pv.errors[:12] + _option_hints(spec)
        g.log.append({"round": rnd, "errors": pv.errors[:12]})
        g.compose_text, g.preview = compose_text, pv
        inp_prev = compose_text
        feedback.append("Your previous spec (fix it, keep what already works):\n" + inp_prev)
    g.error = f"no composable spec after {max_rounds} round(s); the last draft and its problems are shown for editing"
    return g
