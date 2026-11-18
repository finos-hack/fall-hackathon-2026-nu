import pytest
from pydantic import ValidationError

from agip_shared.contracts import (
    AgentResult,
    AgentTask,
    Artifact,
    ControlGapAssessment,
    DeciderResult,
    Decision,
    Extraction_Record,
    FactSet,
    RiskProfile,
    SpectralRun,
)


def test_task_result_roundtrip_ids_only():
    t = AgentTask(task_id="t1", unit="control_assessment", trace_id="tr", artifact_ids=["a1"])
    assert AgentTask.model_validate_json(t.model_dump_json()) == t
    r = AgentResult(task_id="t1", status="OK", artifact_ids=["a2"])
    assert r.error is None


def test_invalid_status_rejected():
    with pytest.raises(ValidationError):
        AgentResult(task_id="t1", status="MAYBE")
    with pytest.raises(ValidationError):
        Decision(decision="MAYBE")


def test_other_contracts_construct():
    Artifact(id="a", kind="facts", sha256="x", trace_id="tr", path="p")
    FactSet()
    SpectralRun(status="OK")
    ControlGapAssessment(gap_level="none")
    RiskProfile()
    DeciderResult(input_hash="h", outcome="ABSTAIN")
    Extraction_Record(prompt_version="v1", model="m", input_hash="h")
