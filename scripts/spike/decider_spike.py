"""Decider spike (task 1.3): GET /health and one POST /v1/systemone at localhost:8000.

Writes docs/spike/decider.md (notes fragment). Stdlib only. Run: python scripts/spike/decider_spike.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "http://localhost:8000"
OUT = Path(__file__).resolve().parents[2] / "docs" / "spike" / "decider.md"

REQUEST = {
    "state": "The agent can send email to external recipients and reads customer records.",
    "model": "strands-decider-latest",
    "images": [],
    "questions": {
        "external_comms": {
            "type": "noul",
            "instructions": "Does the agent communicate with parties outside the organisation?",
        },
        "data_class": {
            "type": "choice",
            "instructions": "Which data class does the agent handle?",
            "criteria": {"public": "Public data", "internal": "Internal data", "pii": "Personal data"},
        },
        "autonomy": {
            "type": "score",
            "instructions": "Rate the autonomy of the agent.",
            "criteria": ["none", "suggests only", "acts with approval", "acts autonomously"],
        },
    },
}


def call(method: str, path: str, body: dict | None = None):
    """HTTP call to the decider. Returns (status, parsed body, latency in ms, error text); status and body are None on connection errors."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw, status = r.read().decode(), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read().decode(), e.code
    except Exception as e:  # connection refused, timeout
        return None, None, (time.perf_counter() - t0) * 1000, f"{type(e).__name__}: {e}"
    ms = (time.perf_counter() - t0) * 1000
    try:
        return status, json.loads(raw), ms, None
    except ValueError:
        return status, raw, ms, None


def main() -> int:
    """Probe /health and /v1/systemone, write the findings report and return the exit code."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    hs, hb, hms, herr = call("GET", "/health")
    lines = [f"# Decider spike (task 1.3)", "", f"Run: {stamp}; base URL `{BASE}`.", "",
             "## GET /health", "", f"- status: `{hs}`; client latency: {hms:.1f} ms",
             f"- error: `{herr}`" if herr else f"- body: `{json.dumps(hb)}`", ""]
    ok = False
    if herr is None and hs == 200:
        ps, pb, pms, perr = call("POST", "/v1/systemone", REQUEST)
        # second call: warm latency
        _, _, pms2, _ = call("POST", "/v1/systemone", REQUEST)
        ok = perr is None and ps == 200 and isinstance(pb, dict) and "answers" in pb
        lines += ["## POST /v1/systemone", "", f"- status: `{ps}`; client latency: {pms:.1f} ms (first), "
                  f"{pms2:.1f} ms (second)", "", "Request:", "```json", json.dumps(REQUEST, indent=2),
                  "```", "", "Response:", "```json", json.dumps(pb, indent=2) if not isinstance(pb, str) else pb,
                  "```", "", "Shape: `{model, answers{name: {type, noul | choice+probabilities+confidence | "
                  "score+legend+probabilities+confidence}}, usage{input_tokens, output_tokens}}`.", ""]
    else:
        lines += ["## POST /v1/systemone", "", "Not attempted: Decider unavailable.", ""]
    if not ok:
        lines += ["## Fallback (Decider down or failing)", "",
                  "Use a deterministic fixture provider keyed by Input_Hash (SHA-256 of canonical JSON of "
                  "model, state, questions) returning recorded answers in the shape above. Decider stays "
                  "advisory (D8); every UNMAPPED fact falls back to `HUMAN_REVIEW` when no fixture matches.", ""]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"{'PASS' if ok else 'DOWN/FAIL (fallback recorded)'}; wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
