"""Task 20.1: round-trip and invalid-value tests for the revised-backlog contracts."""

import pytest
from pydantic import ValidationError

from agip_shared.contracts import (
    KNOWLEDGE_TRANSITIONS,
    PATTERN_TRANSITIONS,
    AcceptedClassification,
    Artifact,
    ArtifactProvenance,
    AssessmentRequirement,
    Evidence,
    ExecutionStep,
    FrameworkExecution,
    HumanTask,
    HumanTaskOutcome,
    InvalidTransition,
    WorkflowRef,
    check_transition,
)

PROV = dict(framework="rule_authoring", producer="compile", version="1", input_hashes={"a1": "ab"})

SAMPLES = {
    ArtifactProvenance: PROV,
    WorkflowRef: dict(executor="Direct_Adapter", development_only=True),
    ExecutionStep: dict(name="facts", status="OK", output_ids=["a2"]),
    FrameworkExecution: dict(execution_id="e1", framework="governance_execution", trace_id="t1"),
    HumanTask: dict(task_id="h1", framework="rule_authoring", task_type="RULE_REVIEW",
                    subject_refs=["MI-024"], role="rule_reviewer"),
    HumanTaskOutcome: dict(task_id="h1", actor="alice", role="rule_reviewer", action="COMPLETE",
                           rationale="ok", previous_state="CLAIMED", resulting_state="COMPLETED"),
    AssessmentRequirement: dict(requirement_id="AR-1", control_id="C-1", description="audit log exists"),
    Evidence: dict(evidence_id="ev1", requirement_id="AR-1", evidence_type="calm", source="spectral",
                   app_id="v1", sha256="00", maturity="DESIGN"),
    AcceptedClassification: dict(fact_id="f1", original_raw="weird", normalized="high", question_type="choice",
                                 model="m", input_hash="h", answer="high", confidence=0.9, margin=0.3,
                                 policy_version="1"),
}

INVALID = {
    ArtifactProvenance: {"framework": "other"},
    WorkflowRef: {"executor": "Airflow"},
    ExecutionStep: {"attempt": 0},
    FrameworkExecution: {"status": "DONE"},
    HumanTask: {"subject_refs": []},
    HumanTaskOutcome: {"rationale": ""},
    AssessmentRequirement: {"required_maturity": "RUNTIME"},
    Evidence: {"maturity": "PROD"},
    AcceptedClassification: {"confidence": 1.5},
}


@pytest.mark.parametrize("cls", list(SAMPLES), ids=lambda c: c.__name__)
def test_round_trip(cls):
    obj = cls(**SAMPLES[cls])
    assert cls.model_validate_json(obj.model_dump_json()) == obj


@pytest.mark.parametrize("cls", list(INVALID), ids=lambda c: c.__name__)
def test_invalid_value_rejected(cls):
    with pytest.raises(ValidationError):
        cls(**{**SAMPLES[cls], **INVALID[cls]})


def test_artifact_carries_provenance():
    a = Artifact(id="a1", kind="ruleset", sha256="ab", trace_id="t", path="p",
                 provenance=ArtifactProvenance(**PROV))
    assert Artifact.model_validate_json(a.model_dump_json()) == a


@pytest.mark.parametrize("cls", [HumanTaskOutcome, AcceptedClassification], ids=lambda c: c.__name__)
def test_immutable_records(cls):
    obj = cls(**SAMPLES[cls])
    with pytest.raises(ValidationError):
        obj.rationale = "x" if cls is HumanTaskOutcome else None  # type: ignore[misc]
    if cls is AcceptedClassification:
        with pytest.raises(ValidationError):
            obj.normalized = "low"  # type: ignore[misc]


def _ex():
    return FrameworkExecution(**SAMPLES[FrameworkExecution])


def test_execution_happy_path_with_wait_and_resume():
    ex = _ex().start().step(ExecutionStep(name="a", status="OK"))
    ex = ex.wait("h1")
    assert ex.status == "WAITING_FOR_HUMAN" and ex.waiting_on == "h1"
    ex = ex.resume().step(ExecutionStep(name="b", status="OK")).complete()
    assert ex.status == "COMPLETED" and [s.name for s in ex.steps] == ["a", "b"]


def test_execution_transitions_return_copies():
    q = _ex()
    r = q.start()
    assert q.status == "QUEUED" and r.status == "RUNNING"


def test_failed_step_blocks_completion_and_retry_works():
    ex = _ex().start().step(ExecutionStep(name="a", status="ERROR", error="boom"))
    with pytest.raises(InvalidTransition):
        ex.complete()
    failed = ex.fail("boom")
    assert failed.retry().status == "RUNNING"


@pytest.mark.parametrize("op", ["resume", "complete", "retry"])
def test_invalid_execution_transitions(op):
    with pytest.raises(InvalidTransition):
        getattr(_ex(), op)()


def test_cancel_terminal_refused():
    done = _ex().start().complete()
    with pytest.raises(InvalidTransition):
        done.cancel()
    assert _ex().start().wait("h").cancel().status == "CANCELLED"


def test_lifecycle_tables():
    check_transition(KNOWLEDGE_TRANSITIONS, "DRAFT", "IN_REVIEW")
    check_transition(PATTERN_TRANSITIONS, "APPROVED", "PUBLISHED")
    for table, cur, tgt in [(KNOWLEDGE_TRANSITIONS, "DRAFT", "APPROVED"),
                            (KNOWLEDGE_TRANSITIONS, "APPROVED", "PUBLISHED"),
                            (PATTERN_TRANSITIONS, "DEPRECATED", "DRAFT")]:
        with pytest.raises(InvalidTransition):
            check_transition(table, cur, tgt)
