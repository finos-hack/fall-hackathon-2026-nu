"""Requirement questions for a reference architecture template (``templates/<ra>.questions.yaml``).

Users answer specific business questions instead of filling raw template attributes. Each answer maps onto the
published template: ``set`` gives attribute values, ``options`` gives option choices; a ``number`` question fills one
attribute. The template file itself is never changed and is reused for every application.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

from .pattern_library import FRAMEWORK_ROOT


def load_questions(ra_id: str, directory: Optional[Path] = None) -> list[dict[str, Any]]:
    """Questions for a template; empty when the template has no questions file (the raw attribute form is used)."""
    f = Path(directory or FRAMEWORK_ROOT / "templates") / f"{ra_id}.questions.yaml"
    if not f.is_file():
        return []
    return list((yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("questions") or [])


def check_questions(questions: list[dict[str, Any]], form: dict[str, Any]) -> list[str]:
    """Problems with a questions file against the template's form (unknown attribute/option, value not allowed)."""
    attrs = {a["name"]: a for a in form.get("attributes") or []}
    opts = {o["unique_id"]: o for o in form.get("options") or []}
    errs = []
    for q in questions:
        if q.get("type") == "number":
            if q.get("attribute") not in attrs:
                errs.append(f"{q['id']}: unknown attribute {q.get('attribute')}")
            continue
        for key, ans in (q.get("answers") or {}).items():
            for name, v in (ans.get("set") or {}).items():
                a = attrs.get(name)
                if a is None:
                    errs.append(f"{q['id']}.{key}: unknown attribute {name}")
                elif a.get("type") == "enum" and v not in a["allowed"]:
                    errs.append(f"{q['id']}.{key}: {v!r} not allowed for {name}")
            for oid, sel in (ans.get("options") or {}).items():
                o = opts.get(oid)
                if o is None:
                    errs.append(f"{q['id']}.{key}: unknown option {oid}")
                    continue
                for s in sel if isinstance(sel, list) else [sel]:
                    if s not in o["choices"]:
                        errs.append(f"{q['id']}.{key}: {s!r} is not a choice of {oid}")
    return errs


def covered(questions: list[dict[str, Any]]) -> tuple[set, set]:
    """(attribute names, option ids) that the questions fill."""
    attrs, opts = set(), set()
    for q in questions:
        if q.get("type") == "number":
            attrs.add(q.get("attribute"))
        for ans in (q.get("answers") or {}).values():
            attrs |= set(ans.get("set") or {})
            opts |= set(ans.get("options") or {})
    return attrs, opts


def apply_answer(q: dict[str, Any], key: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """(attribute values, option selections) for one chosen answer of a choice question."""
    ans = (q.get("answers") or {})[key]
    return dict(ans.get("set") or {}), dict(ans.get("options") or {})


def summary(questions: list[dict[str, Any]], answers: dict[str, Any]) -> str:
    """Human-readable record of the answers ("question: answer" lines), stored as the application's requirements."""
    lines = []
    for q in questions:
        a = answers.get(q["id"])
        if a is None:
            continue
        if isinstance(a, dict):           # {"key": ..., "described": text}
            label = (q.get("answers") or {}).get(a.get("key"), {}).get("label") if a.get("key") else None
            text = f"{label} (from the description: {a['described']})" if label else f"described: {a.get('described')}"
        else:
            text = (q.get("answers") or {}).get(a, {}).get("label", a) if q.get("type") != "number" else str(a)
        lines.append(f"{q['label']} {text}")
    return "\n".join(lines)
