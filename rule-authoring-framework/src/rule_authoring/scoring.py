"""Risk likelihood and impact from the Strands Decider (a decision model), not from the LLM.

One ``POST /v1/systemone`` request asks two ``score`` questions over the risk prose, with the rubrics taken from the
Scoring_Profile (``likelihood_scale`` / ``impact_scale``). The score is the most probable level (1-5); the expected
level, per-level probabilities and the Decider's confidence are kept for the reviewer. A human still confirms the
scores before a risk can be approved (``approval confirm``).

Hash rule: answers are cached by ``input_hash(model, state, questions)`` in ``recordings``; the same input is replayed
without a call. Providers: ``http`` (live, records), ``replay`` (recordings only).
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from agip_shared.gateway import sanitize
from agip_shared.hashing import input_hash

from .paths import FRAMEWORK_ROOT

SCORING_PROFILE = FRAMEWORK_ROOT.parent / "governance-execution-framework" / "config" / "scoring_profile.yaml"
RECORDINGS = FRAMEWORK_ROOT / "fixtures" / "recordings" / "decider-scores"
MAX_STATE = 4000
LOW_CONFIDENCE = 0.5


class ScoringUnavailable(RuntimeError):
    """The Decider could not be reached or answered unexpectedly, or replay had no recording."""


def load_scales(path: Path = SCORING_PROFILE) -> dict[str, list[str]]:
    """Ascending rubric labels per dimension from the Scoring_Profile, e.g. {'likelihood': ['Rare', ...]}."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {k: [str(doc[f"{k}_scale"][i]) for i in sorted(doc[f"{k}_scale"], key=int)] for k in ("likelihood", "impact")}


@dataclass
class Scored:
    score: int                     # 1..5, the most probable level
    expected: float                # Decider's expected level, 1..5
    confidence: float
    probabilities: dict[str, float]
    label: str

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "label": self.label, "expected": round(self.expected, 3),
                "confidence": round(self.confidence, 3), "probabilities": self.probabilities}


@dataclass
class ScoreResult:
    likelihood: Scored
    impact: Scored
    model: str
    input_hash: str
    reused: bool = False
    needs_review: list[str] = field(default_factory=list)   # dimensions below LOW_CONFIDENCE

    def to_dict(self) -> dict[str, Any]:
        return {"source": "decider", "model": self.model, "input_hash": self.input_hash,
                "likelihood": self.likelihood.to_dict(), "impact": self.impact.to_dict(),
                "low_confidence": self.needs_review, "threshold": LOW_CONFIDENCE}


def _post(url: str, body: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 - URL from settings
        return json.loads(resp.read().decode("utf-8"))


class DeciderScorer:
    def __init__(self, provider: str = "http", base_url: str = "", model: str = "", timeout_s: float = 10,
                 recordings: Path = RECORDINGS, scales: Optional[dict[str, list[str]]] = None, post=None):
        if provider not in ("http", "replay"):
            raise ValueError(f"unknown scorer provider: {provider}")
        self.provider, self.base_url, self.model, self.timeout_s = provider, base_url.rstrip("/"), model, timeout_s
        self.recordings, self.scales, self._post = Path(recordings), scales or load_scales(), post or _post

    def questions(self) -> dict[str, Any]:
        return {
            "likelihood": {"type": "score", "criteria": self.scales["likelihood"], "instructions":
                           "How likely is this risk to materialise in a typical AI system deployed in a regulated "
                           "financial institution that has not applied the mitigations described?"},
            "impact": {"type": "score", "criteria": self.scales["impact"], "instructions":
                       "If this risk materialises, how severe is the impact on the institution (financial loss, "
                       "regulatory breach, customer harm, reputational damage)?"},
        }

    def score(self, title: str, prose: str) -> ScoreResult:
        state = sanitize(f"Risk: {title}\n\n{' '.join(str(prose).split())}")[:MAX_STATE]
        qs = self.questions()
        h = input_hash(self.model or "strands-decider-default", state, qs)
        rec = self.recordings / f"{h}.json"
        reused = rec.is_file()
        if reused:
            resp = json.loads(rec.read_text(encoding="utf-8"))
        elif self.provider == "replay":
            raise ScoringUnavailable(f"no decider score recording for {h}")
        else:
            body: dict[str, Any] = {"state": state, "questions": qs, "images": []}
            if self.model:
                body["model"] = self.model
            try:
                resp = self._post(f"{self.base_url}/v1/systemone", body, self.timeout_s)
            except Exception as exc:  # noqa: BLE001 - reported, the LLM score is kept
                raise ScoringUnavailable(f"{type(exc).__name__}: {str(exc)[:160]}") from exc
            rec.parent.mkdir(parents=True, exist_ok=True)
            rec.write_text(json.dumps(resp, indent=2, sort_keys=True), encoding="utf-8")
        try:
            dims = {k: self._level(k, resp["answers"][k]) for k in ("likelihood", "impact")}
        except (KeyError, TypeError, ValueError) as exc:
            raise ScoringUnavailable(f"unexpected decider answer: {exc}") from exc
        low = [k for k, s in dims.items() if s.confidence < LOW_CONFIDENCE]
        return ScoreResult(dims["likelihood"], dims["impact"], str(resp.get("model") or self.model), h, reused, low)

    def _level(self, dim: str, ans: dict[str, Any]) -> Scored:
        probs = {str(k): float(v) for k, v in (ans.get("probabilities") or {}).items()}
        labels = self.scales[dim]
        if not probs:
            raise ValueError(f"{dim}: no probabilities")
        # probabilities are keyed by level index ("0".."4") or by label; map both to a 0-based index
        def idx(k: str) -> int:
            return int(k) if k.isdigit() else labels.index(k)
        best = max(probs, key=lambda k: probs[k])
        i = idx(best)
        return Scored(score=i + 1, expected=float(ans.get("score", i)) + 1, confidence=float(ans.get("confidence", 0.0)),
                      probabilities={labels[idx(k)]: round(v, 4) for k, v in probs.items()}, label=labels[i])


def from_settings(settings: Any, provider: Optional[str] = None, recordings: Path = RECORDINGS) -> DeciderScorer:
    return DeciderScorer(provider or ("http" if settings.decider_provider == "http" else "replay"),
                         settings.decider_url, settings.decider_model, settings.decider_timeout_s, recordings)
