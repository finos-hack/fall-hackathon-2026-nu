"""Dependency direction between frameworks (no cycles).

shared -> nothing; rule_authoring, calm_generation -> shared only;
governance_execution -> shared, rule_authoring, calm_generation.
"""

import ast
from pathlib import Path

FRAMEWORKS = Path(__file__).resolve().parents[1]
PACKAGES = {
    "agip_shared": FRAMEWORKS / "shared" / "src" / "agip_shared",
    "rule_authoring": FRAMEWORKS / "rule-authoring-framework" / "src" / "rule_authoring",
    "calm_generation": FRAMEWORKS / "calm-app-generation-framework" / "src" / "calm_generation",
    "governance_execution": FRAMEWORKS / "governance-execution-framework" / "src" / "governance_execution",
}
ALLOWED = {
    "agip_shared": set(),
    "rule_authoring": {"agip_shared"},
    "calm_generation": {"agip_shared"},
    "governance_execution": {"agip_shared", "rule_authoring", "calm_generation"},
}


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Import):
            roots |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            roots.add(n.module.split(".")[0])
    return roots


def test_framework_dependency_direction():
    problems = []
    for pkg, root in PACKAGES.items():
        for f in root.rglob("*.py"):
            bad = (_imported_roots(f) & set(PACKAGES)) - ALLOWED[pkg] - {pkg}
            if bad:
                problems.append(f"{f.relative_to(FRAMEWORKS)}: imports {sorted(bad)}")
    assert not problems, problems
