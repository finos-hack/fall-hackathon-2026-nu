"""Adapter failure-mode tests with stubbed CLIs (Req 11.1-11.5, 16.2-16.4)."""
import json
import subprocess

import pytest

from governance_execution.adapters.calm import CalmAdapter
from governance_execution.adapters.spectral import SpectralAdapter


def _runner(stdout="", code=0, exc=None, calls=None):
    def run(args, timeout_s, cwd):
        if calls is not None:
            calls.append(list(args))
        if args[1:] == ["--version"]:
            return 0, "1.0.0\n", ""
        if exc:
            raise exc
        return code, stdout, ""
    return run


def _timeout(*a):
    return subprocess.TimeoutExpired("x", 1)


CASES = [
    ("missing", dict(exc=FileNotFoundError())),
    ("timeout", dict(exc=subprocess.TimeoutExpired("x", 1))),
    ("garbage", dict(stdout="not json at all")),
    ("empty", dict(stdout="")),
    ("wrong_shape", dict(stdout='{"foo": 1}')),
]


@pytest.mark.parametrize("name,kw", CASES, ids=[c[0] for c in CASES])
def test_calm_failure_is_error_never_valid(name, kw):
    a = CalmAdapter(runner=_runner(**kw))
    for res in (a.validate({"nodes": []}), a.validate_pattern({"x": 1})):
        assert res.status == "ERROR" and res.status != "VALID"
        assert res.error


@pytest.mark.parametrize("name,kw", CASES[:3], ids=[c[0] for c in CASES[:3]])
def test_calm_generate_failure_is_error(name, kw):
    res = CalmAdapter(runner=_runner(**kw)).generate({"x": 1})
    assert res.status == "ERROR" and res.model is None


def test_calm_warnings_only_is_valid():
    out = json.dumps({"hasErrors": False, "jsonSchemaValidationOutputs": [],
                      "spectralSchemaValidationOutputs": [
                          {"code": "w1", "severity": "warning", "message": "m", "path": "/a"}]})
    res = CalmAdapter(runner=_runner(stdout=out, code=0)).validate({"nodes": []})
    assert res.status == "VALID" and not res.errors and len(res.warnings) == 1


def test_calm_has_errors_is_invalid_regardless_of_exit_code():
    out = json.dumps({"hasErrors": True, "jsonSchemaValidationOutputs": [
        {"code": "e1", "severity": "error", "message": "m", "path": "/a"}]})
    res = CalmAdapter(runner=_runner(stdout=out, code=0)).validate({"nodes": []})
    assert res.status == "INVALID" and res.errors[0].code == "e1"


def test_calm_args_are_list_of_str():
    calls = []
    CalmAdapter(runner=_runner(stdout='{"hasErrors": false}', calls=calls)).validate({"a": 1}, pattern={"p": 1})
    assert calls
    for args in calls:
        assert isinstance(args, list) and all(isinstance(x, str) for x in args)
    assert any(c[1] == "validate" and "-f" in c and "json" in c for c in calls)


@pytest.mark.parametrize("name,kw", CASES[:4], ids=[c[0] for c in CASES[:4]])
def test_spectral_failure_is_error(name, kw):
    res = SpectralAdapter(runner=_runner(**kw)).lint({"a": 1}, "rules.yaml")
    assert res.status == "ERROR" and res.results == [] and res.error


def test_spectral_wrong_shape_is_error():
    res = SpectralAdapter(runner=_runner(stdout='{"a": 1}')).lint({"a": 1}, "r.yaml")
    assert res.status == "ERROR"


def test_spectral_warnings_only_is_ok_and_exit_code_ignored():
    out = json.dumps([{"code": "r1", "message": "m", "path": ["a"], "severity": 1}])
    res = SpectralAdapter(runner=_runner(stdout=out, code=1)).lint({"a": 1}, "r.yaml")
    assert res.status == "OK" and len(res.results) == 1 and res.results[0].severity == 1


def test_spectral_args_are_list():
    calls = []
    SpectralAdapter(runner=_runner(stdout="[]", calls=calls)).lint({"a": 1}, "r.yaml")
    lint = [c for c in calls if len(c) > 1 and c[1] == "lint"][0]
    assert isinstance(lint, list) and "-f" in lint and "json" in lint and "r.yaml" in lint
