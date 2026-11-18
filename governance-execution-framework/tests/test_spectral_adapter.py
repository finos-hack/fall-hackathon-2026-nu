import json
import subprocess

from governance_execution.adapters.spectral import SpectralAdapter


def _runner(lint_out="[]", lint_code=0, exc=None):
    def run(args, timeout, cwd):
        if "--version" in args:
            return 0, "6.17.1\n", ""
        if exc:
            raise exc
        return lint_code, lint_out, ""
    return run


def test_parses_json_despite_nonzero_exit():
    out = json.dumps([{"code": "r1", "message": "m", "path": ["a"], "severity": 0}])
    a = SpectralAdapter(runner=_runner(out, lint_code=1))
    run = a.lint({"x": 1}, "rules.yaml")
    assert run.status == "OK" and run.version == "6.17.1"
    assert [r.code for r in run.results] == ["r1"]
    assert a.last.exit_code == 1 and a.last.parsed and a.last.raw_stdout == out


def test_errors_never_raise():
    assert SpectralAdapter(runner=_runner(exc=FileNotFoundError())).lint({}, "r").status == "ERROR"
    assert SpectralAdapter(runner=_runner(exc=subprocess.TimeoutExpired("s", 1))).lint({}, "r").status == "ERROR"
    assert SpectralAdapter(runner=_runner("not json")).lint({}, "r").status == "ERROR"
