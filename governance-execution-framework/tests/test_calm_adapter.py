import json
import subprocess

from governance_execution.adapters.calm import CalmAdapter


def _runner(out="{}", code=0, exc=None):
    def run(args, timeout, cwd):
        if "--version" in args:
            return 0, "1.60.1\n", ""
        if exc:
            raise exc
        return code, out, ""
    return run


def test_valid_iff_no_errors_and_warnings_kept():
    out = json.dumps({
        "jsonSchemaValidationOutputs": [],
        "spectralSchemaValidationOutputs": [
            {"code": "w1", "severity": "warning", "message": "m", "path": "/nodes/a"}],
        "hasErrors": False, "hasWarnings": True,
    })
    a = CalmAdapter(runner=_runner(out))
    r = a.validate({"nodes": []}, {"$id": "p"})
    assert r.status == "VALID" and r.version == "1.60.1"
    assert [w.code for w in r.warnings] == ["w1"] and not r.errors


def test_invalid_returns_errors_regardless_of_exit_code():
    out = json.dumps({
        "jsonSchemaValidationOutputs": [
            {"code": "json-schema", "severity": "error", "message": "m", "path": "/nodes/svc"}],
        "spectralSchemaValidationOutputs": [], "hasErrors": True, "hasWarnings": False,
    })
    r = CalmAdapter(runner=_runner(out, code=1)).validate({})
    assert r.status == "INVALID" and r.errors[0].path == "/nodes/svc" and r.exit_code == 1


def test_errors_never_valid_never_raise():
    for rn in (_runner(exc=FileNotFoundError()),
               _runner(exc=subprocess.TimeoutExpired("c", 1)),
               _runner("not json"), _runner("{}")):
        assert CalmAdapter(runner=rn).validate({}).status == "ERROR"
    assert CalmAdapter(runner=_runner(exc=FileNotFoundError())).generate({}).status == "ERROR"
