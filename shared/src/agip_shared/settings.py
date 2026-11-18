"""Environment-driven settings. Every connection setting is overridable via .env or env vars."""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration read from env vars or .env (unknown keys ignored). Covers decider, model provider, executor, tool binaries, data dir and sibling source checkouts."""
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    decider_provider: Literal["http", "fixture"] = "http"
    decider_url: str = "http://localhost:8000"
    decider_model: str = ""
    decider_timeout_s: float = 10

    model_provider: Literal["bedrock", "none", "replay"] = "bedrock"
    aws_region: str = "us-east-1"
    aws_profile: str = ""
    bedrock_model_id: str = ""

    executor: Literal["direct", "fluxnova"] = "direct"
    fluxnova_url: str = "http://localhost:8080/engine-rest"

    pglite_host: str = "127.0.0.1"
    pglite_port: int = 5433
    pglite_data_dir: str = "data/pglite"

    calm_bin: str = "calm"
    spectral_bin: str = "spectral"
    tool_timeout_s: float = 60

    data_dir: str = "data"

    # Source checkouts (sibling repos) for rule-authoring ingestion
    aigf_path: str = "../ai-governance-framework"
    ccc_path: str = "../common-cloud-controls"


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached Settings instance; call get_settings.cache_clear() to reload after changing the environment."""
    return Settings()
