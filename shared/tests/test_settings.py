import pytest
from pydantic import ValidationError

from agip_shared.settings import Settings, get_settings


def test_defaults(monkeypatch):
    for k in ("DECIDER_URL", "EXECUTOR", "PGLITE_PORT"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=None)
    assert s.executor == "direct"
    assert s.pglite_port == 5433
    assert s.model_provider == "bedrock"


def test_env_overrides_defaults(monkeypatch):
    monkeypatch.setenv("DECIDER_URL", "http://ec2-host:8000")
    monkeypatch.setenv("EXECUTOR", "fluxnova")
    monkeypatch.setenv("PGLITE_PORT", "6000")
    monkeypatch.setenv("TOOL_TIMEOUT_S", "5")
    s = Settings(_env_file=None)
    assert s.decider_url == "http://ec2-host:8000"
    assert s.executor == "fluxnova"
    assert s.pglite_port == 6000
    assert s.tool_timeout_s == 5


def test_invalid_literal_rejected(monkeypatch):
    monkeypatch.setenv("EXECUTOR", "bogus")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_get_settings_cached():
    assert get_settings() is get_settings()


def test_source_paths_default_and_override(monkeypatch):
    monkeypatch.delenv('CCC_PATH', raising=False)
    assert Settings(_env_file=None).ccc_path == '../common-cloud-controls'
    monkeypatch.setenv('CCC_PATH', '/x/ccc')
    assert Settings(_env_file=None).ccc_path == '/x/ccc'
    assert Settings(_env_file=None).aigf_path == '../ai-governance-framework'
