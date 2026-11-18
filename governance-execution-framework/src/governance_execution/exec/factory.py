"""Wire a Coordinator and Executor from settings (used by the dashboard, the demo and the golden tests)."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Optional

from agip_shared.gateway import ModelGateway, Recorder
from agip_shared.settings import Settings, get_settings

from ..adapters import recorded
from ..adapters.calm import CalmAdapter
from ..adapters.calm import default_runner as calm_runner
from ..adapters.decider import FIXTURES as DECIDER_FIXTURES, DeciderGateway
from ..adapters.spectral import SpectralAdapter
from ..adapters.spectral import default_runner as spectral_runner
from ..store.repository import MemoryRepository
from ..store.sink import ArtifactSink
from ..units.registry import UnitContext
from .coordinator import Coordinator
from .direct_adapter import DirectAdapter

REPO_ROOT = Path(__file__).resolve().parents[4]
FIXTURES = REPO_ROOT / "governance-execution-framework" / "fixtures" / "recordings"
LLM_RECORDINGS = FIXTURES / "llm"
CLI_RECORDINGS = FIXTURES / "cli"
LOCAL_SPECTRAL = REPO_ROOT / ".tools" / "node_modules" / ".bin" / "spectral"


def resolve_spectral(bin_name: str) -> str:
    """Spectral binary to run: ``bin_name`` if on PATH, else the repo-local install, else ``bin_name`` unchanged."""
    if shutil.which(bin_name):
        return bin_name
    for cand in (LOCAL_SPECTRAL.with_suffix(".cmd"), LOCAL_SPECTRAL):
        if cand.exists():
            return str(cand)
    return bin_name


def tools_available(settings: Optional[Settings] = None) -> bool:
    """True when both the CALM and Spectral CLIs can be found."""
    s = settings or get_settings()
    return bool(shutil.which(s.calm_bin)) and bool(shutil.which(resolve_spectral(s.spectral_bin)))


def build(mode: str = "normal", *, settings: Optional[Settings] = None, repo: Any = None, data_dir: Optional[Path] = None,
          cli: str = "real", decider_provider: Optional[str] = None, runtime: Any = None) -> tuple[Coordinator, DirectAdapter]:
    """``cli``: ``real`` (run tools), ``record`` (run tools and save outputs), ``replay`` (recorded outputs only)."""
    s = settings or get_settings()
    data = Path(data_dir or s.data_dir)
    repo = repo if repo is not None else MemoryRepository(data)
    c_run, s_run = calm_runner, spectral_runner
    if cli == "record":
        c_run, s_run = recorded.RecordingRunner(calm_runner, CLI_RECORDINGS), recorded.RecordingRunner(spectral_runner, CLI_RECORDINGS)
    elif cli == "replay":
        c_run = s_run = recorded.ReplayRunner(CLI_RECORDINGS)
    calm = CalmAdapter("calm" if cli == "replay" else s.calm_bin, max(s.tool_timeout_s, 120), c_run)
    spectral = SpectralAdapter("spectral" if cli == "replay" else resolve_spectral(s.spectral_bin), max(s.tool_timeout_s, 120), s_run)

    if mode == "no-llm":
        gateway = None
    elif mode == "replay":
        gateway = ModelGateway("replay", recorder=Recorder(LLM_RECORDINGS))
    else:
        if runtime is None and s.model_provider == "bedrock":
            from agip_shared.gateway.runtime_strands import StrandsRuntime
            runtime = StrandsRuntime(profile=s.aws_profile)
        gateway = ModelGateway.from_settings(s, Recorder(LLM_RECORDINGS if s.model_provider == "replay" else data / "llm-records"),
                                             runtime)
    ctx_cfg = UnitContext.default_config()
    provider = "fixture" if mode == "replay" else (decider_provider or s.decider_provider)
    decider = DeciderGateway(ctx_cfg["decider_policy"], provider, s.decider_url, s.decider_model, s.decider_timeout_s,
                             DECIDER_FIXTURES)
    ctx = UnitContext(sink=ArtifactSink(repo, data), calm=calm, spectral=spectral, decider=decider, gateway=gateway,
                      mode=mode, config=ctx_cfg)
    return Coordinator(ctx), build_executor(s)


def build_executor(s: Settings) -> Any:
    """EXECUTOR=fluxnova selects the Fluxnova executor; it falls back to Direct_Adapter when the engine is unreachable."""
    if s.executor == "fluxnova":
        from .fluxnova_client import FluxnovaClient
        from .fluxnova_executor import FluxnovaExecutor
        client = FluxnovaClient(s.fluxnova_url)
        if client.available():
            return FluxnovaExecutor(client)
        print(f"warning: Fluxnova unreachable at {s.fluxnova_url}; using Direct_Adapter (development-only)")
    return DirectAdapter()
