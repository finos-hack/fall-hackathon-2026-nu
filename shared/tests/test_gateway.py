import pytest

from agip_shared.contracts import Extraction_Record
from agip_shared.gateway import ModelGateway, ModelUnavailableError, Recorder, RecordingMissingError, sanitize


class FakeRuntime:
    def __init__(self, text='{"ok": true}'):
        self.text, self.prompts = text, []

    def complete(self, prompt, model, region):
        self.prompts.append(prompt)
        return self.text


def test_sanitize_strips_secrets_and_paths():
    out = sanitize({"api_key": "x", "t": "key AKIAABCDEFGHIJKLMNOP at C:\\Users\\a\\f.md and /home/u/x.md, see https://a.b/c",
                    "n": [1, "password=hunter2"]})
    s = str(out)
    assert out["api_key"] == "[REDACTED]"
    for leak in ("AKIA", "C:\\", "/home/u", "hunter2"):
        assert leak not in s
    assert "https://a.b/c" in s and out["n"][0] == 1


def test_none_provider():
    with pytest.raises(ModelUnavailableError):
        ModelGateway("none").complete("extraction", "v1", {"a": 1})


def test_bedrock_records_and_replay_serves(tmp_path):
    rt = FakeRuntime('```json\n{"x": 1}\n```')
    gw = ModelGateway("bedrock", "m1", "us-east-1", Recorder(tmp_path), rt)
    rec = gw.complete("extraction", "v1", {"prose": "see /etc/passwd", "password": "p"}, prompt="P")
    assert rec.output == {"x": 1} and rec.model == "m1" and rec.prompt_version == "v1"
    assert "/etc/passwd" not in rt.prompts[0] and '"p"' not in rt.prompts[0]
    replay = ModelGateway("replay", recorder=Recorder(tmp_path))
    assert replay.complete("extraction", "v1", {"prose": "see /etc/passwd", "password": "p"}).output == {"x": 1}


def test_replay_missing_names_record(tmp_path):
    with pytest.raises(RecordingMissingError, match="extraction/v1/"):
        ModelGateway("replay", recorder=Recorder(tmp_path)).complete("extraction", "v1", {"a": 1})


def test_runtime_failure_wrapped(tmp_path):
    class Boom:
        def complete(self, *a):
            raise RuntimeError("down")

    with pytest.raises(ModelUnavailableError):
        ModelGateway("bedrock", "m", "r", Recorder(tmp_path), Boom()).complete("e", "v1", {})


def test_recorder_rejects_bad_key(tmp_path):
    with pytest.raises(ValueError):
        Recorder(tmp_path).key("../x", "v1", "h")
