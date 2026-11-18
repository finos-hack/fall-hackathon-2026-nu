"""User requirements (free text) -> option choices and attribute values, through the Strands Decider.

The published template (``p.json``) is reused for every application; only the option choices (``c.json``) and the
attribute values differ per application. Order:

1. Options the user left open are chosen from the requirements (``classify_attribute`` choice over the option's
   choices; for an anyOf option the Decider picks one choice, more must be ticked by the user).
2. Attributes implied by the chosen options (``templates/<ra>.consistency.yaml``) are set from the option, never asked.
3. Remaining empty enum attributes are inferred from the requirements plus the chosen design.

A Decider answer is used only when it passes the Decider policy (min confidence / top-2 margin); otherwise the item
is reported back so the user chooses it. Every inferred item keeps its provenance (model, confidence, input hash),
which flows into the generation manifest and the assessment's source record. The Decider never sets a decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Inference:
    values: dict[str, Any] = field(default_factory=dict)          # attribute name -> inferred value
    options: dict[str, Any] = field(default_factory=dict)         # option unique_id -> selected slug (list for anyOf)
    provenance: dict[str, Any] = field(default_factory=dict)      # attribute name / option id -> {source, ...}
    unresolved: list[str] = field(default_factory=list)           # messages for the user
    audits: list[dict[str, Any]] = field(default_factory=list)


def _ask(decider: Any, qid: str, question: str, choices: list[str], fields: dict[str, Any], trace_id: str,
         descriptions: Optional[dict[str, str]] = None):
    q = {"type": "choice", "id": qid, "choices": choices, "question": question}
    if descriptions:
        q["descriptions"] = descriptions
    res, audit = decider.classify("classify_attribute", q, fields, trace_id=trace_id)
    choice = (res.answer or {}).get("choice") if isinstance(res.answer, dict) else None
    ok = res.outcome == "ACCEPTED" and choice in choices
    conf = f", confidence {res.confidence:.2f}" if res.confidence is not None else ""
    return (choice if ok else None), res, audit, (res.error or f"{res.outcome}{conf}")


def _prov(res: Any, source: str = "decider") -> dict[str, Any]:
    return {"source": source, "model": res.model, "confidence": res.confidence, "input_hash": res.input_hash,
            "from": "requirements"}


def infer_values(form: dict[str, Any], requirements: str, decider: Any, trace_id: str = "",
                 rules: Optional[list[dict[str, Any]]] = None) -> Inference:
    """Fill open options and empty enum attributes of ``form`` from ``requirements``. Does not modify ``form``."""
    from calm_generation import attributes as attrs
    out = Inference()
    text = " ".join(str(requirements or "").split())
    can_ask = bool(text) and decider is not None

    # 1. options
    design = []
    for o in form.get("options") or []:
        sel = o.get("selected")
        if sel not in (None, "", []):
            design.append(f"{o['prompt']} {', '.join(o['choices'][s] for s in (sel if isinstance(sel, list) else [sel]))}")
            continue
        if not can_ask:
            out.unresolved.append(f"{o['unique_id']}: choose an option, or describe it in the requirements")
            continue
        slugs = list(o["choices"])
        pick, res, audit, why = _ask(decider, o["unique_id"], f"Based on the application requirements: {o['prompt']}",
                                     slugs, {"element_id": o["unique_id"], "attribute_name": "option",
                                             "description": text}, trace_id)
        out.audits.append(audit)
        if pick is None:
            out.unresolved.append(f"{o['unique_id']}: the Decider could not decide from the requirements ({why}); choose an option")
            continue
        out.options[o["unique_id"]] = pick if o["type"] == "oneOf" else [pick]
        out.provenance[o["unique_id"]] = _prov(res)
        design.append(f"{o['prompt']} {o['choices'][pick]}")

    # 2. attributes implied by the chosen options (same design decision, never asked twice)
    chosen = {**form, "options": [{**o, "selected": out.options.get(o["unique_id"], o.get("selected"))}
                                  for o in form.get("options") or []]}
    for name, v in attrs.implied_values(chosen, rules or []).items():
        out.values[name] = v
        out.provenance[name] = {"source": "option", "from": "chosen option"}

    # 3. remaining enum attributes
    values = {**(form.get("values") or {}), **out.values}
    context = text + (" Chosen design: " + "; ".join(design) + "." if design else "")
    for a in form.get("attributes") or []:
        name = a["name"]
        if a.get("type") != "enum" or values.get(name) not in (None, ""):
            continue
        if not can_ask:
            if a.get("required"):
                out.unresolved.append(f"{name}: choose a value, or describe it in the requirements")
            continue
        node, fld = a["target"]["node"], a["target"]["field"]
        pick, res, audit, why = _ask(decider, f"{node}.{fld}",
                                     f"Based on the application requirements, which value best describes the {fld} of {node}?",
                                     list(a["allowed"]), {"element_id": node, "attribute_name": fld, "description": context},
                                     trace_id)
        out.audits.append(audit)
        if pick is None:
            out.unresolved.append(f"{name}: the Decider could not decide from the requirements ({why}); choose a value")
            continue
        out.values[name] = pick
        out.provenance[name] = _prov(res)
    return out


def choose_template(templates: list[dict[str, Any]], requirements: str, decider: Any,
                    trace_id: str = "") -> tuple[Optional[str], dict[str, Any], Optional[str]]:
    """Pick the reference architecture template for the requirements among the PUBLISHED ones.

    Returns (template id, provenance, problem). One published template is used directly; with several the Decider
    chooses by title and description and must pass the Decider policy, otherwise ``problem`` asks the user to choose."""
    if not templates:
        return None, {}, "no PUBLISHED reference architecture template; approve one in the CALM Patterns Catalog"
    if len(templates) == 1:
        return templates[0]["id"], {"source": "only published template"}, None
    text = " ".join(str(requirements or "").split())
    if not text or decider is None:
        return None, {}, "choose a reference architecture template, or describe the application in the requirements"
    q = {"type": "choice", "id": "reference-architecture", "choices": [t["id"] for t in templates],
         "descriptions": {t["id"]: f"{t['title']}: {t['description']}" for t in templates},
         "question": "Which reference architecture fits the application described in the requirements?"}
    res, _ = decider.classify("classify_attribute", q, {"element_id": "application", "attribute_name": "reference_architecture",
                                                        "description": text}, trace_id=trace_id)
    choice = (res.answer or {}).get("choice") if isinstance(res.answer, dict) else None
    if res.outcome == "ACCEPTED" and choice in q["choices"]:
        return choice, _prov(res), None
    conf = f", confidence {res.confidence:.2f}" if res.confidence is not None else ""
    return None, {}, f"the Decider could not choose a template from the requirements ({res.error or res.outcome + conf}); choose one"


def answer_questions(questions: list[dict[str, Any]], chosen: dict[str, Any], described: dict[str, str], decider: Any,
                     trace_id: str = "") -> tuple[Inference, dict[str, Any]]:
    """Requirement-question answers -> attribute values and option choices of the template.

    ``chosen``: question id -> answer key (or the number for a number question). ``described``: question id -> the
    user's own description when no answer fits; the Decider then picks one of that question's answers (policy-gated).
    Returns the Inference and the answer record {question id: key | number | {"key", "described"}}."""
    from calm_generation import questions as qmod
    out, record = Inference(), {}
    for q in questions:
        qid = q["id"]
        if q.get("type") == "number":
            if chosen.get(qid) not in (None, ""):
                out.values[q["attribute"]] = chosen[qid]
                out.provenance[q["attribute"]] = {"source": "question", "question": qid}
                record[qid] = chosen[qid]
            continue
        key, text = chosen.get(qid) or None, " ".join(str(described.get(qid) or "").split())
        prov: dict[str, Any] = {"source": "question", "question": qid}
        if key is None and text and decider is not None:
            keys = list(q.get("answers") or {})
            pick, res, audit, why = _ask(decider, qid, f"Which answer fits this description? {q['label']}", keys,
                                         {"element_id": qid, "attribute_name": "requirement", "description": text}, trace_id,
                                         {k: v["label"] for k, v in (q.get("answers") or {}).items()})
            out.audits.append(audit)
            if pick is None:
                out.unresolved.append(f"{q['label']} the Decider could not map your description to an answer ({why}); choose one")
                record[qid] = {"key": None, "described": text}
                continue
            key, prov = pick, {**_prov(res), "question": qid, "described": text}
            record[qid] = {"key": key, "described": text}
        elif key is not None:
            record[qid] = key
        if key is None:
            continue
        vals, opts = qmod.apply_answer(q, key)
        for name, v in vals.items():
            out.values[name] = v
            out.provenance[name] = prov
        for oid, sel in opts.items():
            out.options[oid] = sel
            out.provenance[oid] = prov
    return out, record
