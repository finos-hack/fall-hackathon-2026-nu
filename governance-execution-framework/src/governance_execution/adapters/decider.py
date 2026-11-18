"""Decider gateway: ``POST /v1/systemone`` (Req 14.1-14.3, 14.9, 15).

* Called only for UNMAPPED attributes with no deterministic check (``select_for_decider``).
* ``state`` comes from a fixed field list, max 4000 chars, truncated in a documented order, scrubbed of
  secrets and paths; full CALM JSON is never sent.
* Results are cached by Input_Hash; every call (including cache hits) yields an audit record.
* Providers: ``http`` and ``fixture`` (keyed by Input_Hash; ``fixture_missing`` when absent).
* ``classify`` never raises. Unavailable/HTTP error/timeout -> outcome ERROR, recorded UNKNOWN, no default.
* Option B: an ACCEPTED answer becomes an AcceptedClassification (fact -> INFERRED, normalized set, raw kept).
  The Decider never sets likelihood, impact, severity, control status, gates or the decision.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from agip_shared.contracts import AcceptedClassification, DeciderResult, Fact
from agip_shared.gateway import sanitize
from agip_shared.hashing import input_hash

from ..core import acceptance

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "recordings" / "decider"
HttpPost = Callable[[str, dict[str, Any], float], dict[str, Any]]


def default_post(url: str, body: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    """POST the platform request to the Strands Decider and return the answer in platform shape.

    The platform shape (``questions`` as a list of {type, id, question, choices}, ``answers`` as a list) is what the
    gateway, its fixtures and the input hash use; the server schema is {questions: {name: {type, instructions,
    criteria}}} with ``answers`` keyed by name. Raises urllib errors on failure; the caller handles them."""
    qs = list(body.get("questions") or [])
    wire: dict[str, Any] = {"state": body.get("state", ""), "images": body.get("images") or [],
                            "questions": {(q.get("id") or f"q{i}"): _server_question(q) for i, q in enumerate(qs)}}
    if body.get("model"):
        wire["model"] = body["model"]
    req = urllib.request.Request(url, data=json.dumps(wire).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 - URL from config
        out = json.loads(resp.read().decode("utf-8"))
    if isinstance(out, dict) and isinstance(out.get("answers"), dict):
        out = {**out, "answers": [{**(out["answers"].get(q.get("id") or f"q{i}") or {}), "id": q.get("id")}
                                  for i, q in enumerate(qs)]}
    return out


def build_state(fields: dict[str, Any], policy: dict[str, Any]) -> str:
    """Render ``fields`` as ``name: value`` lines in policy order, scrubbed by ``sanitize`` and cut to ``state_max_chars``. Fields in ``truncation_order`` are shortened first."""
    order = policy.get("state_fields") or []
    limit = int(policy.get("state_max_chars", 4000))
    vals = {k: sanitize("" if fields.get(k) is None else str(fields.get(k))) for k in order}

    def render() -> str:
        """Join the non-empty fields into the state text."""
        return "\n".join(f"{k}: {vals[k]}" for k in order if vals[k] != "")

    text = render()
    for k in policy.get("truncation_order") or []:
        if len(text) <= limit:
            break
        over = len(text) - limit
        vals[k] = vals[k][: max(0, len(vals[k]) - over)]
        text = render()
    return text[:limit]


def select_for_decider(facts: list[Fact], checked_fields: set[str]) -> list[Fact]:
    """UNMAPPED facts whose attribute no deterministic (Spectral) rule checks (Req 14.1)."""
    return [f for f in facts if f.mapping_status == "UNMAPPED" and f.attribute not in checked_fields]


class DeciderGateway:
    """Client for the Decider service. Caches results by Input_Hash and returns an audit record for every call."""
    def __init__(self, policy: dict[str, Any], provider: str = "fixture", base_url: str = "", model: str = "",
                 timeout_s: float = 10, fixtures_dir: Path = FIXTURES, post: Optional[HttpPost] = None):
        """Raises ValueError for a provider other than ``http`` or ``fixture``. ``post`` replaces the HTTP call (tests)."""
        if provider not in ("http", "fixture"):
            raise ValueError(f"unknown decider provider: {provider}")
        self.policy, self.provider, self.base_url, self.model = policy, provider, base_url.rstrip("/"), model
        self.timeout_s, self.fixtures_dir, self._post = timeout_s, Path(fixtures_dir), post or default_post
        self.cache: dict[str, tuple[DeciderResult, Any]] = {}

    @classmethod
    def from_settings(cls, settings: Any, policy: dict[str, Any], **kw: Any) -> "DeciderGateway":
        """Build a gateway from the ``decider_*`` fields of ``settings``."""
        return cls(policy, settings.decider_provider, settings.decider_url, settings.decider_model,
                   settings.decider_timeout_s, **kw)

    def question(self, task_name: str, fact: Fact, choices: list[str]) -> dict[str, Any]:
        """Build the question payload for ``fact`` per the task type in policy; ``choices`` are included only for ``choice`` tasks."""
        t = self.policy["tasks"][task_name]
        q: dict[str, Any] = {"type": t["type"], "id": f"{fact.element_id}.{fact.attribute}",
                             "question": f"Which value best describes {fact.attribute}?"}
        if t["type"] == "choice":
            q["choices"] = choices
        return q

    def classify(self, task_name: str, question: dict[str, Any], fields: dict[str, Any],
                 trace_id: str = "") -> tuple[DeciderResult, dict[str, Any]]:
        """Ask the Decider one question; returns (result, audit record). Never raises: a missing fixture or any call failure gives outcome ERROR with no answer."""
        task = self.policy["tasks"][task_name]
        state = build_state(fields, self.policy)
        h = input_hash(self.model, state, [question])
        audit = {"trace_id": trace_id, "task": task_name, "model": self.model, "state": state, "question": question,
                 "input_hash": h, "created": datetime.now(timezone.utc).isoformat()}
        if h in self.cache:
            res, ans = self.cache[h]
            res = res.model_copy(update={"cache_hit": True, "latency_ms": 0})
            return res, {**audit, "answer": ans, "confidence": res.confidence, "latency_ms": 0,
                         "outcome": res.outcome, "cache_hit": True, "error": res.error}
        start = time.monotonic()
        try:
            resp = self._call(h, state, question)
            latency = int((time.monotonic() - start) * 1000)
            answers = resp.get("answers") if isinstance(resp, dict) else None
            ans = answers[0] if isinstance(answers, list) and answers else None
            outcome = acceptance.evaluate(task, ans)
            conf = acceptance._num(ans.get("confidence")) if isinstance(ans, dict) and task["type"] != "noul" else None
            res = DeciderResult(input_hash=h, outcome=outcome, answer=ans, confidence=conf,
                                model=(resp or {}).get("model", self.model), latency_ms=latency)
        except _FixtureMissing:
            ans = None
            res = DeciderResult(input_hash=h, outcome="ERROR", model=self.model, error="fixture_missing", latency_ms=0)
        except Exception as exc:  # noqa: BLE001 - never raises (Req 15.4)
            ans = None
            res = DeciderResult(input_hash=h, outcome="ERROR", model=self.model,
                                latency_ms=int((time.monotonic() - start) * 1000),
                                error=f"unavailable: {type(exc).__name__}: {str(exc)[:200]}")
        self.cache[h] = (res, ans)
        return res, {**audit, "answer": ans, "confidence": res.confidence, "latency_ms": res.latency_ms,
                     "outcome": res.outcome, "cache_hit": False, "error": res.error}

    def _call(self, h: str, state: str, question: dict[str, Any]) -> dict[str, Any]:
        """Fetch the raw response: the fixture file named by the Input_Hash, or an HTTP POST to ``/v1/systemone``. Raises _FixtureMissing if no fixture."""
        if self.provider == "fixture":
            f = self.fixtures_dir / f"{h}.json"
            if not f.is_file():
                raise _FixtureMissing(h)
            return json.loads(f.read_text(encoding="utf-8"))
        body = {"state": state, "questions": [question], "model": self.model, "images": []}
        return self._post(f"{self.base_url}/v1/systemone", body, self.timeout_s)


def _server_question(q: dict[str, Any]) -> dict[str, Any]:
    """Platform question {type, id, question, choices} -> Strands Decider schema {type, instructions, criteria}."""
    out: dict[str, Any] = {"type": q["type"], "instructions": q.get("question") or q.get("instructions") or ""}
    if q["type"] == "choice":
        desc = q.get("descriptions") or {}
        out["criteria"] = {c: desc.get(c) or c for c in q.get("choices") or []}
    elif q.get("criteria") is not None:
        out["criteria"] = q["criteria"]
    return out


class _FixtureMissing(LookupError):
    """No fixture recorded for an Input_Hash; reported as ``fixture_missing``."""
    pass


def classify_unmapped(gateway: DeciderGateway, facts: list[Fact], taxonomy: dict[str, Any], checked_fields: set[str],
                      descriptions: dict[str, str], trace_id: str = "") -> tuple[list[Fact], list[dict[str, Any]]]:
    """Ask the Decider about each eligible UNMAPPED fact. Returns updated facts and audit records."""
    out, audits = [], []
    eligible = {id(f) for f in select_for_decider(facts, checked_fields)}
    for f in facts:
        if id(f) not in eligible:
            out.append(f)
            continue
        choices = sorted(set(((taxonomy.get("attributes") or {}).get(f.attribute) or {}).get("values", {}).values()))
        q = gateway.question("classify_attribute", f, choices)
        fields = {"element_id": f.element_id, "element_type": descriptions.get(f.element_id + "#type", ""),
                  "attribute_name": f.attribute, "raw_value": f.raw, "description": descriptions.get(f.element_id, "")}
        res, audit = gateway.classify("classify_attribute", q, fields, trace_id)
        audits.append(audit)
        task = gateway.policy["tasks"]["classify_attribute"]
        raw_outcome = acceptance.finalize(task, res.answer, choices) if res.outcome in ("ACCEPTED", "HUMAN_REVIEW", "ABSTAIN") else res.outcome
        if raw_outcome == "ACCEPTED" and isinstance(res.answer, dict) and isinstance(res.answer.get("choice"), str):
            label = res.answer["choice"]
            cls = AcceptedClassification(
                fact_id=f"{f.element_id}.{f.attribute}", original_raw=f.raw, normalized=label, question_type=task["type"],
                model=res.model or gateway.model, model_version=None, input_hash=res.input_hash, answer=res.answer,
                confidence=res.confidence, margin=acceptance.top2_margin(res.answer.get("probabilities")),
                policy_version=str(gateway.policy.get("version", "")),
                provenance={"trace_id": trace_id, "task": "classify_attribute", "json_path": f.json_path,
                            "element_id": f.element_id, "attribute": f.attribute, "taxonomy_version": f.taxonomy_version,
                            "cache_hit": res.cache_hit})
            audit["classification"] = json.loads(cls.model_dump_json())
            out.append(f.model_copy(update={"decider_label": label, "decider_outcome": "ACCEPTED",
                                            "mapping_status": "INFERRED", "normalized": label,
                                            "extraction_method": "decider_classification",
                                            "classification_ref": cls.fact_id}))
            continue
        outcome = "HUMAN_REVIEW" if raw_outcome == "HUMAN_REVIEW" else "UNKNOWN"
        out.append(f.model_copy(update={"decider_label": None, "decider_outcome": outcome}))
    return out, audits
