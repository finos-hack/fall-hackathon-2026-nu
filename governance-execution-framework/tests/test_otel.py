import io
import json

from governance_execution.obs.otel import Tracing, VersionsRecorder, scrub


def test_trace_spans_scrub_and_versions():
    buf = io.StringIO()
    t = Tracing(out=buf)
    with t.assessment(app="a1", api_key="sk-abcdef123456") as tid:
        with t.stage("scan", note="token=abc123"):
            pass
        art = t.attach({"id": "x"})
    t.shutdown()
    assert art["trace_id"] == tid and len(tid) == 32
    out = buf.getvalue()
    assert "sk-abcdef123456" not in out and "abc123" not in out
    assert out.count(tid) >= 2  # same trace across assessment + stage spans
    assert scrub({"password": "p", "n": 1}) == {"password": "[REDACTED]", "n": 1}

    v = VersionsRecorder()
    v.record("rulesets", "ai-gov", "1.0", sha="deadbeef")
    v.record("models", "m", "x")
    d = v.to_dict()
    assert d["rulesets"]["ai-gov"]["sha"] == "deadbeef" and "taxonomy" in d
    json.dumps(d)
