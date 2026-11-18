"""Demo run: instantiate and assess V1-V4 on recorded outputs, print the decisions (Req 20.1, 26.1).

``python -m governance_execution.demo [--real-tools] [--data-dir DIR]``
LLM and Decider always come from recordings. CALM and Spectral come from recordings unless ``--real-tools``.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from agip_shared.settings import Settings, get_settings

from .exec import factory
from .store.repository import MemoryRepository
from .units.calm_builder import instantiate, load_template

FORMS = factory.REPO_ROOT / "governance-execution-framework" / "forms"


def main(argv: list[str] | None = None) -> int:
    """Assess forms v1-v4 against RA03-LITE with recorded LLM/Decider outputs and print one row per variant. Returns 0."""
    ap = argparse.ArgumentParser(prog="governance_execution.demo")
    ap.add_argument("--real-tools", action="store_true")
    ap.add_argument("--data-dir", type=Path, default=None)
    args = ap.parse_args(argv)
    base = get_settings()
    s = Settings(_env_file=None, decider_provider="fixture", model_provider="replay", data_dir=str(args.data_dir or base.data_dir),
                 calm_bin=base.calm_bin, spectral_bin=base.spectral_bin, tool_timeout_s=base.tool_timeout_s)
    data = Path(s.data_dir)
    repo = MemoryRepository(data)
    coord, ex = factory.build("normal", settings=s, repo=repo, data_dir=data, cli="real" if args.real_tools else "replay")
    tpl, text = load_template("RA03-LITE")
    print(f"{'variant':<20} {'CALM':<8} {'status':<11} {'decision':<26} trace")
    for v in ("v1", "v2", "v3", "v4"):
        form = yaml.safe_load((FORMS / f"{v}.attributes.yaml").read_text(encoding="utf-8"))
        r = instantiate(form, template=tpl, template_text=text, template_status="PUBLISHED", calm=coord.ctx.calm,
                        sink=coord.ctx.sink)
        if r.app_model is None:
            print(f"{form['app']['id']:<20} {r.status:<8} instantiation failed: {r.errors}")
            continue
        out = coord.run(r.app_model, executor=ex, template_id="RA03-LITE", source={"app_id": form["app"]["id"]})
        print(f"{form['app']['id']:<20} {r.status:<8} {out.status:<11} {str(out.decision or '(none)'):<26} {out.trace_id}")
    print(f"Executor: {ex.label} ({ex.note}). Artifacts in {data.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
