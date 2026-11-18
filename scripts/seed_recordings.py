"""Write the recorded Decider and remediation-LLM outputs for V1-V4 (Req 24, 26.1).

Run from the repo root after instantiating V1-V4: ``uv run python scripts/seed_recordings.py``.
Uses the recorded CLI outputs (no tools needed); pass ``--record-cli`` to run calm/spectral and record them. The recorded outputs are authored, not produced by a
live model or Decider: the Decider fixture answers the UNMAPPED data classification as ``confidential``
with high confidence, and the remediation recording is a numbered fix prompt built from the catalog
remediation texts. Their model name is ``recorded-seed``.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import yaml

from agip_shared.gateway import ModelGateway, Recorder
from agip_shared.settings import Settings
from governance_execution.adapters.decider import FIXTURES as DECIDER_FIXTURES
from governance_execution.exec import factory
from governance_execution.units.calm_builder import instantiate, load_template

ROOT = Path(__file__).resolve().parents[1]
FORMS = ROOT / "governance-execution-framework" / "forms"


class SeedRuntime:
    """Offline stand-in for the model runtime that builds the summary and fix prompt directly from the input items."""
    def complete(self, prompt: str, model: str, region: str) -> str:
        """Return the canned summary and numbered fix list for the items in the prompt's INPUT section."""
        data = json.loads(prompt.split("INPUT:\n", 1)[1])
        items = data["items"]
        fix = "\n".join(f"{i + 1}. {it['text']} [{it['id']}]" for i, it in enumerate(items))
        ids = ", ".join(it["id"] for it in items)
        return json.dumps({"summary": f"The design has {len(items)} item(s) to fix ({ids}). "
                                      "Change the attributes or the model and run a new assessment.",
                           "fix_prompt": fix})


def main() -> int:
    """Run the assessments for variants v1 to v4 and record model (and optionally CLI) outputs for later replay. Returns 1 if instantiation fails."""
    tmp = Path(tempfile.mkdtemp(prefix="agip-seed-"))
    s = Settings(_env_file=None, decider_provider="fixture", model_provider="none")
    cli = "record" if "--record-cli" in sys.argv else "replay"   # --record-cli runs calm/spectral and saves their outputs
    coord, ex = factory.build("normal", settings=s, data_dir=tmp, cli=cli)
    coord.ctx.gateway = ModelGateway("bedrock", "recorded-seed", "none", Recorder(factory.LLM_RECORDINGS), SeedRuntime())
    tpl, text = load_template("RA03-LITE")
    for v in ("v1", "v2", "v3", "v4"):
        form = yaml.safe_load((FORMS / f"{v}.attributes.yaml").read_text(encoding="utf-8"))
        r = instantiate(form, template=tpl, template_text=text, template_status="PUBLISHED", calm=coord.ctx.calm)
        if r.app_model is None:
            print(v, "instantiation failed:", r.status, r.errors)
            return 1
        out = coord.run(r.app_model, executor=ex, template_id="RA03-LITE", source={"app_id": form["app"]["id"]})
        if "decider_calls" in out.artifacts:
            for call in coord.ctx.sink.get(out.trace_id, "decider_calls", "result"):
                q = call["question"]
                fixture = {"model": "recorded-seed", "usage": {},
                           "answers": [{"id": q["id"], "choice": "confidential", "confidence": 0.91,
                                        "probabilities": {c: (0.88 if c == "confidential" else round(0.12 / (len(q["choices"]) - 1), 4))
                                                          for c in q["choices"]}}]}
                DECIDER_FIXTURES.mkdir(parents=True, exist_ok=True)
                (DECIDER_FIXTURES / f"{call['input_hash']}.json").write_text(json.dumps(fixture, indent=1, sort_keys=True), encoding="utf-8")
        print(v, out.status, out.decision)
    return 0


if __name__ == "__main__":
    sys.exit(main())
