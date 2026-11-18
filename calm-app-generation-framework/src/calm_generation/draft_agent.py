"""AI pattern drafting: a Strands agent drafts one CALM 1.2 pattern from its SPECS.md row, guided by the CALM AI
assistant prompts (``architecture-as-code/calm-ai``, the files that ``ai-assistants/kiro.json`` installs as skills).

The repair loop (draft -> validate -> feedback, at most ``max_rounds``) is driven in code. Its output is never trusted:
the draft must pass the static checks, ``calm validate -p`` (injected validator) and a contract check against the
specification (same nodes, relationships, metadata schemas, control and risk IDs), and it enters the library as a
``CANDIDATE``. Publishing still needs a human approver (``pattern_library`` / ``lifecycle``). Strands is reached only
through ``agip_shared.gateway.runtime_strands``.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from agip_shared import versioned_write as vw
from agip_shared.hashing import canonical_json

from . import lifecycle as lc
from . import pattern_library as pl

REPO_ROOT = pl.FRAMEWORK_ROOT.parent
CALM_AI_DIR = REPO_ROOT.parent / "architecture-as-code" / "calm-ai"
PROMPT = pl.FRAMEWORK_ROOT / "prompts" / "pattern-draft.v1.md"
SPECS = pl.PATTERN_DIR / "SPECS.md"
CATALOG_HEADER = REPO_ROOT / "rule-authoring-framework" / "catalogs" / "controls.catalog.yaml"
SKILLS = ("pattern-creation", "node-creation", "relationship-creation", "metadata-creation")   # subset of kiro.json skills

Validator = Callable[[dict[str, Any]], Any]      # calm validate -p: object with .status and .errors


def load_skills(calm_ai: Path = CALM_AI_DIR, wanted: tuple[str, ...] = SKILLS) -> str:
    """CALM AI prompts named in ai-assistants/kiro.json (skillPrompts), limited to those a pattern draft needs."""
    listed = json.loads((calm_ai / "ai-assistants" / "kiro.json").read_text(encoding="utf-8"))["skillPrompts"]
    parts = []
    for rel in listed:
        name = Path(rel).stem
        if name in wanted:
            parts.append(f"## CALM AI skill: {name}\n\n" + (calm_ai / "tools" / f"{name}.md").read_text(encoding="utf-8"))
    return "\n\n".join(parts)


def spec_rows(specs: Path = SPECS) -> tuple[str, dict[str, str]]:
    """Parse SPECS.md; return ``(table header row, {pattern id: raw table row})``."""
    lines = specs.read_text(encoding="utf-8").splitlines()
    header = next(l for l in lines if l.startswith("| ID") or l.startswith("| Pattern"))
    return header, {re.match(r"\|\s*(P\d+)", l).group(1): l for l in lines if re.match(r"\|\s*P\d+\s*\|", l)}


def vocabulary(path: Path = CATALOG_HEADER) -> str:
    """Extract the CALM metadata vocabulary comment block from the controls catalog header (stops at the first non-comment line or the merge-decisions section)."""
    out, on = [], False
    for l in path.read_text(encoding="utf-8").splitlines():
        if "CALM metadata vocabulary" in l:
            on = True
        elif on and not l.startswith("#"):
            break
        elif on and "Merge decisions" in l:
            break
        if on:
            out.append(l.lstrip("# ").rstrip())
    return "\n".join(out)


def _norm(o: Any) -> Any:
    """Normalise JSON for comparison: sorted dict keys and sorted lists of scalars; lists containing containers keep their order."""
    if isinstance(o, dict):
        return {k: _norm(v) for k, v in sorted(o.items())}
    if isinstance(o, list):
        items = [_norm(x) for x in o]
        return sorted(items, key=canonical_json) if all(not isinstance(x, (dict, list)) for x in items) else items
    return o


def _const(n: dict[str, Any], key: str) -> Any:
    """The ``properties.<key>.const`` value of a node/relationship definition, or None."""
    return ((n.get("properties") or {}).get(key) or {}).get("const")


def contract_errors(draft: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    """Differences from the specification pattern, ignoring descriptions and key order."""
    errs: list[str] = []

    def items(p: dict[str, Any], k: str) -> list[dict[str, Any]]:
        """``prefixItems`` of ``properties.<k>`` in a pattern, or an empty list."""
        return ((p.get("properties") or {}).get(k) or {}).get("prefixItems") or []
    dn, sn = items(draft, "nodes"), items(spec, "nodes")
    if [_const(n, "unique-id") for n in dn] != [_const(n, "unique-id") for n in sn]:
        errs.append(f"nodes must be exactly, in order: {[_const(n, 'unique-id') for n in sn]}")
    for d, s in zip(dn, sn):
        sid = _const(s, "unique-id")
        for f in ("node-type", "name"):
            if _const(d, f) != _const(s, f):
                errs.append(f"node {sid}: {f} must be const {_const(s, f)!r}")
        if _norm((d.get("properties") or {}).get("metadata")) != _norm((s.get("properties") or {}).get("metadata")):
            errs.append(f"node {sid}: metadata schema must be exactly "
                        f"{json.dumps((s.get('properties') or {}).get('metadata'), sort_keys=True)} (null means: no metadata key)")
    dr, sr = items(draft, "relationships"), items(spec, "relationships")
    if [_norm((r.get("properties") or {}).get("relationship-type")) for r in dr] != \
            [_norm((r.get("properties") or {}).get("relationship-type")) for r in sr] or \
            [_const(r, "unique-id") for r in dr] != [_const(r, "unique-id") for r in sr]:
        errs.append("relationships must be exactly: " + json.dumps(
            [{"unique-id": _const(r, "unique-id"), "relationship-type": (r.get("properties") or {}).get("relationship-type")} for r in sr], sort_keys=True))
    dm, sm = draft.get("metadata") or {}, spec.get("metadata") or {}
    if not isinstance(draft.get("description"), str) or not draft.get("description"):
        errs.append("top-level description must be a non-empty string")
    for kind, d_items, s_items in (("node", dn, sn), ("relationship", dr, sr)):
        for d, s in zip(d_items, s_items):
            uid = _const(s, "unique-id")
            if not isinstance(_const(d, "description"), str):
                errs.append(f"{kind} {uid}: properties.description must be {{\"const\": \"<text>\"}}")
            if d.get("$ref") != s.get("$ref"):
                errs.append(f"{kind} {uid}: $ref must be {s.get('$ref')}")
            missing = [k for k in s.get("required", []) if k not in (d.get("required") or [])]
            if missing:
                errs.append(f"{kind} {uid}: required must include {missing}")
    for f in ("pattern-id", "version"):
        if dm.get(f) != sm.get(f):
            errs.append(f"metadata.{f} must be {sm.get(f)!r}")
    for f in ("related_controls", "related_risks"):
        if sorted(dm.get(f, [])) != sorted(sm.get(f, [])):
            errs.append(f"metadata.{f} must be {sm.get(f)}")
    return errs


@dataclass
class DraftResult:
    """Outcome of drafting one pattern. ``source`` is AI, or CANONICAL_FALLBACK when ``pattern`` is the specification pattern after failed repair."""
    pattern_id: str
    source: str                        # AI | CANONICAL_FALLBACK
    pattern: dict[str, Any]
    rounds: int = 0
    errors: list[str] = field(default_factory=list)
    model: str = ""
    reused: bool = False               # answered from the inputs-hash cache, no model call

    @property
    def text(self) -> str:
        """Pattern as deterministic JSON text."""
        return pl.dumps(self.pattern)


def _parse_json(text: str) -> Optional[dict[str, Any]]:
    """Extract a JSON object from a model reply (fenced block or outermost braces); None if it does not parse to an object."""
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, re.S)
    t = m.group(1) if m else t[t.find("{"): t.rfind("}") + 1]
    try:
        v = json.loads(t)
        return v if isinstance(v, dict) else None
    except ValueError:
        return None


class PatternDraftAgent:
    """Drafts patterns with a Strands agent and a code-driven validate/repair loop; see the module docstring."""
    def __init__(self, runtime: Any, model: str, region: str, validator: Validator, *, calm_ai: Path = CALM_AI_DIR,
                 max_rounds: int = 3, library: Optional[dict[str, Any]] = None, cache_dir: Optional[Path] = None):
        """Load the system prompt (draft prompt plus CALM AI skills), spec rows and vocabulary. ``library`` supplies worked examples; ``cache_dir`` enables the inputs-hash cache."""
        self.runtime, self.model, self.region, self.validator, self.max_rounds = runtime, model, region, validator, max_rounds
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.system = PROMPT.read_text(encoding="utf-8") + "\n\n# Reference material\n\n" + load_skills(calm_ai)
        self.header, self.rows = spec_rows()
        self.vocab = vocabulary()
        self.library = library if library is not None else pl.load_patterns()

    def _example(self, pid: str) -> str:
        """One published pattern other than ``pid``, with its spec row, as a worked example of the pattern shape."""
        ex = next((k for k in sorted(self.rows) if k != pid and k in self.library), None)
        if ex is None:
            return ""
        return (f"Worked example (a different pattern, {ex}): specification row\n{self.header}\n{self.rows[ex]}\n"
                f"becomes this CALM 1.2 pattern:\n{pl.dumps(self.library[ex])}\n\n")

    def check(self, draft: dict[str, Any], spec: dict[str, Any], entry: Optional[dict[str, Any]] = None) -> list[str]:
        """All problems with a draft: static shape, contract differences from the specification, and ``calm validate -p`` findings."""
        errs = lc.validate_pattern_shape(draft, entry)
        errs += contract_errors(draft, spec)
        v = self.validator(draft)
        # Validator results are duck-typed: a missing status counts as valid, a missing errors list falls back to a single error.
        if getattr(v, "status", "VALID") != "VALID":
            errs += [f"calm validate -p: {getattr(e, 'message', e)}" for e in (getattr(v, "errors", None) or [getattr(v, "error", "invalid")])]
        return errs

    def inputs_hash(self, pid: str, spec: dict[str, Any]) -> str:
        """Everything that produces the draft: prompt, system prompt (skills), spec, model and runtime parameters."""
        return vw.hash_inputs(pid=pid, prompt=self._base(pid), system=self.system, spec=spec, model=self.model,
                              runtime=getattr(self.runtime, "fingerprint", ""), max_rounds=self.max_rounds)

    def _base(self, pid: str) -> str:
        """The round-1 prompt: spec row, vocabulary, a worked example and the output instructions."""
        return (f"INPUT\n\nSpecification row ({pid}):\n{self.header}\n{self.rows[pid]}\n\nMetadata vocabulary:\n{self.vocab}\n\n"
                + self._example(pid) +
                f"Draft pattern {pid} as one CALM 1.2 pattern JSON object. Set metadata.status to \"CANDIDATE\", pattern-id "
                f"\"{pid}\", version 1. Reply with the JSON only.")

    def draft(self, pid: str, spec: dict[str, Any]) -> DraftResult:
        """Draft pattern ``pid``. ``spec`` is the specification pattern, used only to check the draft.

        A validated AI draft is cached by its inputs hash (``cache_dir``): same inputs, no model call (hash rule).
        The repair loop is driven here, not by the model: each round is one Strands agent call (CALM AI skills as the
        system prompt), then the validator runs, and its findings go into the next round. Small models do not stop a
        tool loop on their own, so the round limit is enforced in code."""
        h = self.inputs_hash(pid, spec)
        cached = self.cache_dir / f"{h}.json" if self.cache_dir else None
        if cached is not None and cached.is_file():
            return DraftResult(pid, "AI", json.loads(cached.read_text(encoding="utf-8")), 0, [], self.model, reused=True)
        res = self._draft(pid, spec)
        if cached is not None and res.source == "AI":
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(res.text, encoding="utf-8")
        return res

    def _draft(self, pid: str, spec: dict[str, Any]) -> DraftResult:
        """Run up to ``max_rounds`` agent calls, feeding validator findings back each round. Agent errors or exhausted rounds yield the canonical pattern as CANONICAL_FALLBACK."""
        base = self._base(pid)
        prompt, last, errs = base, None, ["not drafted"]
        for rnd in range(1, self.max_rounds + 1):
            try:
                out = self.runtime.run_agent(prompt, self.model, self.region, system_prompt=self.system, tools=[])
            except Exception as e:     # model or network failure: reported, the caller falls back to the canonical pattern
                return DraftResult(pid, "CANONICAL_FALLBACK", spec, rnd, [f"agent error: {e}"], self.model)
            cand = _parse_json(out)
            try:
                errs = self.check(cand, spec) if cand else ["reply was not a JSON object"]
            except Exception as e:      # malformed model output must become feedback, never crash the workflow step
                errs = [f"draft has the wrong structure ({type(e).__name__}: {e}); follow the worked example exactly"]
            if not errs:
                return DraftResult(pid, "AI", pl.as_candidate(cand), rnd, [], self.model)
            last = cand or last
            prompt = (base + "\n\nYour previous draft:\n" + (json.dumps(cand, sort_keys=True) if cand else out[:4000]) +
                      "\n\nThe validator reported these problems. Fix all of them and reply with the corrected JSON only:\n- " +
                      "\n- ".join(errs[:15]))
        return DraftResult(pid, "CANONICAL_FALLBACK", spec, self.max_rounds, errs, self.model)
