"""Task 23.4: no Decider value reaches scoring, gates or the decision (static AST scan + runtime)."""
import ast
from pathlib import Path

from agip_shared.contracts import SpectralResult, SpectralRun
from governance_execution.core import catalogs, decision, facts as fx, gap, gates
from governance_execution.units import control_assessment as ca, risk_assessment as ra

SRC = Path(__file__).resolve().parents[1] / "src" / "governance_execution"
SCANNED = [SRC / "units" / "risk_assessment.py", SRC / "units" / "control_assessment.py",
           SRC / "core" / "gates.py", SRC / "core" / "decision.py"]
FORBIDDEN_PREFIXES = ("decider_",)
FORBIDDEN_NAMES = {"AcceptedClassification", "accepted_classifications", "classification_ref"}


def _names(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            yield n.id
        elif isinstance(n, ast.Attribute):
            yield n.attr
        elif isinstance(n, ast.arg):
            yield n.arg
        elif isinstance(n, ast.keyword) and n.arg:
            yield n.arg
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            mod = getattr(n, "module", "") or ""
            yield from [mod] + [a.name for a in n.names]
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith(FORBIDDEN_PREFIXES):
            yield n.value


def test_static_no_decider_names_in_scoring_or_decision():
    for p in SCANNED:
        bad = [n for n in _names(p) if n.startswith(FORBIDDEN_PREFIXES) or n in FORBIDDEN_NAMES or "adapters.decider" in n
               or n == "decider"]
        assert not bad, f"{p.name} references Decider values: {bad}"


CTL, RSK = catalogs.load("controls"), catalogs.load("risks")
GAP, SCORE, GATES, MATRIX = gap.load_gap_rule(), ra.load_scoring(), gates.load_gates(), decision.load_matrix()
APP = {"nodes": [
    {"unique-id": "pay", "node-type": "ai:agent", "metadata": {"autonomy": "autonomous", "privilege": "restricted-write",
                                                              "can_execute_payment": True, "payment_approval_path": "direct"}},
    {"unique-id": "db", "node-type": "database", "metadata": {"data_classification": "supplier-financial"}},
]}


def _outcome(facts):
    run = SpectralRun(status="OK", results=[SpectralResult(code="risk-agent-autonomous-execution", path=["nodes", "0", "metadata"])])
    prof = ra.assess(run, RSK, facts, APP, SCORE)
    g = ca.assess(run, CTL, APP, GAP)
    d = decision.decide("VALID", g, prof, GATES, MATRIX)
    return ([(r.risk_id, r.severity) for r in prof.risks], prof.profile_level, prof.mandatory_trigger,
            d.decision, [x["id"] + str(x["fired"]) for x in d.gates_evaluated], d.matrix_cell.get("result"))


def test_runtime_varying_decider_answers_never_change_outcome():
    base = fx.extract(APP, TAX := fx.load_taxonomy())
    expected = _outcome(base)
    for label in ("public", "internal", "confidential", "restricted"):
        for outcome in ("ACCEPTED", "ABSTAIN", "HUMAN_REVIEW", "UNKNOWN"):
            facts = base.model_copy(update={"facts": [
                f.model_copy(update={"decider_label": label if outcome == "ACCEPTED" else None, "decider_outcome": outcome,
                                     **({"mapping_status": "INFERRED", "normalized": label} if outcome == "ACCEPTED" else {})})
                if f.attribute == "data_classification" else f for f in base.facts]})
            assert _outcome(facts) == expected
