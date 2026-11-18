"""Static consistency guards (Requirements 1.2, 1.5).

1. Severity is never derived from risk_tier output or summed Dimension values.
2. No calm-guard dependency and no reference to the draft repos
   (design-time-agent-security, cyber-grc-finos-framework) as dependency/import/path.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GE_SRC = ROOT / "governance-execution-framework" / "src" / "governance_execution"
SRC_DIRS = [p for p in ROOT.glob("*/src/*") if p.is_dir()]
TEST_DIRS = [ROOT / "tests", *ROOT.glob("*-framework/tests")]
SELF = Path(__file__).resolve()

RISK_TIER_MODULES = ("governance_execution.risk_tier",)
# Identifiers whose presence in a severity expression indicates derivation from tier/dimensions.
TAINT_RE = re.compile(r"tier|classify_risk|dimension|dims", re.IGNORECASE)

CALM_GUARD_RE = re.compile(r"calm[-_]?guard", re.IGNORECASE)
DRAFT_REPO_RE = re.compile(r"design-time-agent-security|cyber-grc-finos-framework", re.IGNORECASE)


# ---------------------------------------------------------------- checkers

def _imported_modules(tree: ast.AST) -> list[str]:
    mods: list[str] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            base = n.module or ""
            mods.append(base)
            mods += [f"{base}.{a.name}" for a in n.names]
    return mods


def _severity_values(tree: ast.AST) -> list[ast.AST]:
    """Value expressions assigned to anything named `severity`."""
    vals: list[ast.AST] = []

    def is_sev(t: ast.AST) -> bool:
        return (isinstance(t, ast.Name) and t.id == "severity") or (
            isinstance(t, ast.Attribute) and t.attr == "severity"
        ) or (isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
              and t.slice.value == "severity")

    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and any(is_sev(t) for t in n.targets):
            vals.append(n.value)
        elif isinstance(n, ast.AnnAssign) and n.value is not None and is_sev(n.target):
            vals.append(n.value)
        elif isinstance(n, ast.keyword) and n.arg == "severity":
            vals.append(n.value)
        elif isinstance(n, ast.Dict):
            for k, v in zip(n.keys, n.values):
                if isinstance(k, ast.Constant) and k.value == "severity":
                    vals.append(v)
    return vals


def _is_tainted(expr: ast.AST) -> bool:
    for n in ast.walk(expr):
        if isinstance(n, ast.Name) and TAINT_RE.search(n.id):
            return True
        if isinstance(n, ast.Attribute) and TAINT_RE.search(n.attr):
            return True
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "sum":
            return True
    return False


def severity_violations(source: str, *, legacy: bool, name: str = "<mod>") -> list[str]:
    """Return violation messages for one module's source."""
    tree = ast.parse(source)
    out: list[str] = []
    sev_vals = _severity_values(tree)
    if not legacy:
        uses_tier = any(
            m == rt or m.startswith(rt + ".") for m in _imported_modules(tree) for rt in RISK_TIER_MODULES
        )
        if uses_tier and sev_vals:
            out.append(f"{name}: imports risk_tier and assigns severity")
    for v in sev_vals:
        if _is_tainted(v):
            out.append(f"{name}: severity derived from risk tier / summed dimensions")
    return out


def dependency_violations(pyproject_text: str) -> list[str]:
    deps = tomllib.loads(pyproject_text).get("project", {}).get("dependencies", [])
    groups = tomllib.loads(pyproject_text).get("dependency-groups", {})
    alldeps = list(deps) + [d for g in groups.values() for d in g if isinstance(d, str)]
    return [d for d in alldeps if CALM_GUARD_RE.search(d) or DRAFT_REPO_RE.search(d)]


def import_violations(source: str, name: str = "<mod>") -> list[str]:
    tree = ast.parse(source)
    # Module paths only (an imported symbol name such as a legacy in-repo
    # `CALMGuardBridge` class is not an external calm-guard dependency).
    mods = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    mods += [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    out = [f"{name}: import {m}" for m in mods
           if CALM_GUARD_RE.search(m) or DRAFT_REPO_RE.search(m)]
    # Path-like string literals (not docstrings) referencing the draft repos.
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
                  and n.body and isinstance(n.body[0], ast.Expr)
                  and isinstance(n.body[0].value, ast.Constant)}
    for n in ast.walk(tree):
        if (isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings
                and DRAFT_REPO_RE.search(n.value)):
            out.append(f"{name}: path/string references draft repo")
    return out


def _py_files(base: Path):
    return [p for p in base.rglob("*.py") if "__pycache__" not in p.parts and ".venv" not in p.parts]


# ------------------------------------------------------------------- tests

def test_severity_not_derived_from_risk_tier_in_repo():
    problems: list[str] = []
    for src in SRC_DIRS:
        for p in _py_files(src):
            if p.name == "risk_tier.py":
                continue
            # Draft-derived governance_execution modules keep the draft's exemption.
            in_legacy = GE_SRC in p.parents
            problems += severity_violations(
                p.read_text(encoding="utf-8"), legacy=in_legacy, name=p.relative_to(ROOT).as_posix()
            )
    assert not problems, problems


def test_risk_assessment_severity_independent_of_risk_tier():
    tree = ast.parse((GE_SRC / "units" / "risk_assessment.py").read_text(encoding="utf-8"))
    assert not any(_is_tainted(v) for v in _severity_values(tree))


def test_no_calm_guard_or_draft_repo_dependency():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert dependency_violations(text) == []
    problems: list[str] = []
    for p in [f for d in SRC_DIRS + TEST_DIRS for f in _py_files(d)]:
        if p.resolve() == SELF:
            continue
        problems += import_violations(p.read_text(encoding="utf-8"), p.relative_to(ROOT).as_posix())
    assert not problems, problems


def test_checkers_detect_synthetic_violations():
    bad_import_sev = "from governance_execution.risk_tier import classify_risk\nseverity = 'high'\n"
    assert severity_violations(bad_import_sev, legacy=False)
    assert severity_violations("import governance_execution.risk_tier\nx = dict(severity='low')\n", legacy=False)
    assert severity_violations("severity = tier.label\n", legacy=True)
    assert severity_violations("f = {'severity': sum(dims.values())}\n", legacy=True)
    assert not severity_violations("severity = 'high'\n", legacy=False)
    assert not severity_violations("from governance_execution.risk_tier import X\nx = 1\n", legacy=False)

    assert dependency_violations('[project]\ndependencies = ["calm-guard>=1"]\n')
    assert dependency_violations('[project]\ndependencies = ["x @ git+https://h/design-time-agent-security"]\n')
    assert not dependency_violations('[project]\ndependencies = ["pyyaml"]\n')
    assert import_violations("import calm_guard\n")
    assert import_violations("from calmguard.x import y\n")
    assert import_violations("P = '../cyber-grc-finos-framework/src'\n")
    assert not import_violations("import yaml\n")
