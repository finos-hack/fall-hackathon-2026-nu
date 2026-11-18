"""Acceptance_Policy for Decider answers (Req 14.4-14.8). Pure.

``choice``/``score``: ACCEPTED iff confidence >= min_confidence AND top-2 probability margin >= min_top2_margin.
``noul``: ACCEPTED iff value >= accept_high or <= accept_low; confidence is never read.
Anything missing, invalid or undeterminable is not accepted (the task's ``on_fail``: ABSTAIN or HUMAN_REVIEW).
Decider scores are not calibrated probabilities.

Option B (Accepted Classification): an ACCEPTED ``choice`` that is one of the taxonomy values becomes a
normalized classification (see ``decider.classify_unmapped``); everything else keeps the fact UNKNOWN/UNMAPPED.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import yaml

CONFIG = Path(__file__).resolve().parents[3] / "config" / "decider_policy.yaml"
ACCEPTED, ABSTAIN, HUMAN_REVIEW = "ACCEPTED", "ABSTAIN", "HUMAN_REVIEW"


def load_policy(path: Path = CONFIG) -> dict[str, Any]:
    """Load the Decider acceptance policy YAML (default ``config/decider_policy.yaml``)."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _num(x: Any) -> float | None:
    """Return ``x`` as a float, or None for non-numbers, bools, NaN and infinities."""
    # bool is an int subclass; True/False must not count as a confidence or score
    if isinstance(x, bool) or not isinstance(x, (int, float)) or math.isnan(x) or math.isinf(x):
        return None
    return float(x)


def top2_margin(probabilities: Any) -> float | None:
    """Gap between the two highest probabilities (the top one if only one); None if the input is not a dict/list of valid numbers."""
    if isinstance(probabilities, dict):
        vals = list(probabilities.values())
    elif isinstance(probabilities, list):
        vals = [p.get("probability") if isinstance(p, dict) else p for p in probabilities]
    else:
        return None
    nums = [_num(v) for v in vals]
    if not nums or any(n is None for n in nums):
        return None
    nums.sort(reverse=True)
    # a single option has no runner-up, so its margin is its full probability
    return nums[0] - (nums[1] if len(nums) > 1 else 0.0)


def evaluate(task: dict[str, Any], answer: Any) -> str:
    """Return ACCEPTED, or the task's ``on_fail`` (ABSTAIN or HUMAN_REVIEW) when the answer is missing, invalid or below the policy thresholds."""
    fail = task.get("on_fail", ABSTAIN)
    if fail not in (ABSTAIN, HUMAN_REVIEW):
        fail = ABSTAIN
    if not isinstance(answer, dict):
        return fail
    if task["type"] == "noul":
        v = _num(answer.get("noul"))
        if v is None or not 0.0 <= v <= 1.0:
            return fail
        return ACCEPTED if v >= task.get("accept_high", 0.9) or v <= task.get("accept_low", 0.1) else fail
    if task["type"] in ("choice", "score"):
        key = "choice" if task["type"] == "choice" else "score"
        if answer.get(key) in (None, ""):
            return fail
        conf, margin = _num(answer.get("confidence")), top2_margin(answer.get("probabilities"))
        if conf is None or margin is None:
            return fail
        return ACCEPTED if conf >= task["min_confidence"] and margin >= task["min_top2_margin"] else fail
    return fail


def finalize(task: dict[str, Any], answer: Any, choices: list[str]) -> str:
    """``evaluate`` plus the Option B check: a ``choice`` answer must be one of the allowed taxonomy values."""
    outcome = evaluate(task, answer)
    if outcome == ACCEPTED and task["type"] == "choice" and choices and answer.get("choice") not in choices:
        fail = task.get("on_fail", ABSTAIN)
        return fail if fail in (ABSTAIN, HUMAN_REVIEW) else ABSTAIN
    return outcome