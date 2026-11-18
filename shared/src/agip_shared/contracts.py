"""Cross-framework contracts (Req 21.1, 21.3): framework-neutral, artifact IDs only. No Strands or other runtime types."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Governance-as-code MVP contracts (framework-neutral; artifact IDs only).
# Reqs 21.1, 21.3. No Strands or other runtime types here.
# ---------------------------------------------------------------------------


class AgentTask(BaseModel):
    """Unit invocation. Passes artifact IDs only, never payloads."""

    task_id: str
    unit: str
    trace_id: str
    artifact_ids: List[str] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    """Unit outcome. Returns artifact IDs only, never payloads."""

    task_id: str
    status: Literal["OK", "ERROR"]
    artifact_ids: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class Artifact(BaseModel):
    """Immutable stored artifact metadata (content lives in the artifact store)."""

    id: str
    kind: str
    sha256: str
    trace_id: str
    path: str
    created: datetime = Field(default_factory=datetime.utcnow)
    versions: Dict[str, Any] = Field(default_factory=dict)
    provenance: Optional["ArtifactProvenance"] = None


class Fact(BaseModel):
    """Provenance-carrying value extracted from an App_Model."""

    id: Optional[str] = None
    trace_id: Optional[str] = None
    element_id: str
    json_path: str
    raw: Any = None
    normalized: Optional[str] = None
    taxonomy_version: Optional[str] = None
    mapping_status: Literal["MAPPED", "UNMAPPED", "UNKNOWN", "INFERRED"] = "UNMAPPED"  # INFERRED: Decider answer accepted by policy (Option B)
    attribute: Optional[str] = None
    dimension: Optional[str] = None
    decider_label: Optional[str] = None      # accepted label (UNMAPPED only, accepted by policy); never a severity or decision
    decider_outcome: Optional[str] = None    # ACCEPTED | ABSTAIN | HUMAN_REVIEW | UNKNOWN | None (not asked)
    extraction_method: Optional[str] = None  # e.g. taxonomy_mapping | taxonomy_absent | decider_classification
    classification_ref: Optional[str] = None  # AcceptedClassification.fact_id when a Decider label was accepted
    provenance: Dict[str, Any] = Field(default_factory=dict)  # app_model_sha256 / source pointers


class FactSet(BaseModel):
    """Facts extracted from an application model, with the taxonomy/app-model hashes they were derived from and any pending human reviews."""
    facts: List[Fact] = Field(default_factory=list)
    taxonomy_version: str = ""
    app_model_sha256: str = ""
    accepted_classifications: List["AcceptedClassification"] = Field(default_factory=list)
    pending_human_tasks: List[str] = Field(default_factory=list)  # HumanTask ids awaiting review (no wait/resume here)


class SpectralResult(BaseModel):
    """One parsed Spectral finding."""

    code: str
    message: str = ""
    path: List[Any] = Field(default_factory=list)
    severity: Optional[int] = None


class SpectralRun(BaseModel):
    """Outcome of one Spectral lint run: OK with parsed results, or ERROR with a message. Raw and parsed outputs are kept as artifacts."""
    status: Literal["OK", "ERROR"]
    results: List[SpectralResult] = Field(default_factory=list)
    version: Optional[str] = None
    error: Optional[str] = None
    raw_artifact_id: Optional[str] = None
    parsed_artifact_id: Optional[str] = None


class ControlResult(BaseModel):
    """Assessment outcome for one control. PASS is design-level evidence only; findings list the failing rule hits."""
    control_id: str
    status: Literal["PASS", "FAIL", "ERROR", "NOT_APPLICABLE"]
    gap_contribution: Optional[str] = None  # catalog severity: critical|high|medium|low
    rule_codes: List[str] = Field(default_factory=list)
    remediation: Optional[str] = None
    title: Optional[str] = None
    mandatory: bool = False
    evidence: Optional[str] = None          # PASS is "design-level evidence only"
    findings: List[Dict[str, Any]] = Field(default_factory=list)  # [{rule_code, path, message}]
    source: Dict[str, Any] = Field(default_factory=dict)


class ControlGapAssessment(BaseModel):
    """All control results for a trace plus the overall gap level (INDETERMINATE_INPUT when the input could not be assessed)."""
    trace_id: Optional[str] = None
    controls: List[ControlResult] = Field(default_factory=list)
    gap_level: Literal["none", "minor", "major", "critical", "INDETERMINATE_INPUT"]
    gap_rule_version: Optional[int] = None


class RiskResult(BaseModel):
    """Scored result for one risk: likelihood and impact (1-5) give the severity. Residual severity never drops below inherent without implementation/operating PASS evidence."""
    risk_id: str
    likelihood: int = Field(ge=1, le=5)
    impact: int = Field(ge=1, le=5)
    severity: Literal["Low", "Medium", "High", "Critical"]
    triggered_by: List[str] = Field(default_factory=list)
    title: Optional[str] = None
    findings: List[Dict[str, Any]] = Field(default_factory=list)  # [{rule_code, path, message}]
    remediation: Optional[str] = None
    source: Dict[str, Any] = Field(default_factory=dict)
    inherent_severity: Optional[Literal["Low", "Medium", "High", "Critical"]] = None   # == severity
    residual_severity: Optional[Literal["Low", "Medium", "High", "Critical"]] = None   # never below inherent without IMPLEMENTATION/OPERATING PASS evidence


class RiskProfile(BaseModel):
    """Per-trace set of risk results with the derived profile level and approval tier. Output is illustrative, not approved policy."""
    trace_id: Optional[str] = None
    risks: List[RiskResult] = Field(default_factory=list)
    tier: Optional[str] = None               # Agent_Approval_Tier from risk_tier.py (approval path only)
    tier_detail: Dict[str, Any] = Field(default_factory=dict)
    label: str = "illustrative, not approved policy"
    unevaluable: List[str] = Field(default_factory=list)
    profile_level: Optional[Literal["Low", "Medium", "High", "Critical"]] = None
    scoring_version: Optional[int] = None
    mandatory_trigger: Optional[str] = None  # e.g. UNEVALUABLE


DecisionOutcome = Literal[
    "APPROVED",
    "APPROVED_WITH_CONDITIONS",
    "RESTRICTED",
    "REJECTED",
    "INDETERMINATE",
]


class Decision(BaseModel):
    """Final approval decision for a trace with the gates evaluated, matrix cell used and any conditions attached."""
    trace_id: Optional[str] = None
    decision: DecisionOutcome
    gates_evaluated: List[Dict[str, Any]] = Field(default_factory=list)
    matrix_cell: Dict[str, Any] = Field(default_factory=dict)
    conditions: List[str] = Field(default_factory=list)


class DeciderResult(BaseModel):
    """Decider gateway outcome. classify() never raises; failures are encoded here."""

    input_hash: str
    outcome: Literal["ACCEPTED", "ABSTAIN", "HUMAN_REVIEW", "ERROR"]
    answer: Optional[Any] = None
    confidence: Optional[float] = None
    model: Optional[str] = None
    latency_ms: Optional[int] = None
    cache_hit: bool = False
    error: Optional[str] = None


class Extraction_Record(BaseModel):  # noqa: N801 - name fixed by spec
    """Persisted LLM extraction (Req 4.5)."""

    id: Optional[str] = None
    item_id: Optional[str] = None
    prompt_id: Optional[str] = None
    prompt_version: str
    model: str
    input_hash: str
    output: Any = None
    prompt_sha256: Optional[str] = None   # full prompt text + runtime parameters; live runs reuse a matching record
    created: datetime = Field(default_factory=datetime.utcnow)


ExtractionRecord = Extraction_Record


# ---------------------------------------------------------------------------
# Revised-backlog contracts (task 20.1). Framework-neutral, artifact IDs only.
# ---------------------------------------------------------------------------

from datetime import timezone  # noqa: E402

from pydantic import ConfigDict  # noqa: E402


def _now() -> datetime:
    """Current time as a timezone-aware UTC datetime (default factory for timestamp fields)."""
    return datetime.now(timezone.utc)


class InvalidTransition(ValueError):
    """Raised when a lifecycle or execution transition is not allowed."""


FrameworkId = Literal["rule_authoring", "calm_generation", "governance_execution"]

# Statuses kept separate (task 23.7).
AssessmentStatus = Literal["QUEUED", "RUNNING", "WAITING_FOR_HUMAN", "COMPLETED", "FAILED", "BLOCKED"]
ValidationStatus = Literal["VALID", "INVALID", "INCOMPLETE", "ERROR"]

# Source and knowledge / artifact lifecycle.
SourceState = Literal["REGISTERED", "INGESTED", "INGEST_FAILED", "SUPERSEDED"]
LifecycleState = Literal["DRAFT", "IN_REVIEW", "APPROVED", "REJECTED", "PUBLISHED", "DEPRECATED"]

KNOWLEDGE_TRANSITIONS: Dict[str, set] = {
    "DRAFT": {"IN_REVIEW"},
    "IN_REVIEW": {"APPROVED", "REJECTED", "DRAFT"},
    "APPROVED": {"DEPRECATED"},
    "REJECTED": {"DRAFT", "DEPRECATED"},
    "DEPRECATED": set(),
}
PATTERN_TRANSITIONS: Dict[str, set] = {
    "DRAFT": {"IN_REVIEW"},
    "IN_REVIEW": {"APPROVED", "REJECTED", "DRAFT"},
    "APPROVED": {"PUBLISHED", "DEPRECATED"},
    "REJECTED": {"DRAFT", "DEPRECATED"},
    "PUBLISHED": {"DEPRECATED"},
    "DEPRECATED": set(),
}


def check_transition(table: Dict[str, set], current: str, target: str) -> None:
    """Validate a state change against a transition table; raise InvalidTransition if target is not reachable from current."""
    if target not in table.get(current, set()):
        raise InvalidTransition(f"{current} -> {target} not allowed")


class ArtifactProvenance(BaseModel):
    """Who/what produced an artifact, from which inputs, at which version."""

    framework: FrameworkId
    producer: str                                   # unit / command name
    version: str
    trace_id: Optional[str] = None
    input_artifact_ids: List[str] = Field(default_factory=list)
    input_hashes: Dict[str, str] = Field(default_factory=dict)  # artifact id -> sha256
    source_ids: List[str] = Field(default_factory=list)         # native AIGF / CCC / pattern IDs
    created: datetime = Field(default_factory=_now)


class WorkflowRef(BaseModel):
    """Reference to the executor run behind a FrameworkExecution."""

    executor: Literal["Direct_Adapter", "Fluxnova"]
    development_only: bool = False
    process_definition: Optional[str] = None
    process_version: Optional[str] = None
    instance_id: Optional[str] = None
    current_task: Optional[str] = None


StepStatus = Literal["RUNNING", "OK", "ERROR", "SKIPPED"]


class ExecutionStep(BaseModel):
    """One step of a framework execution with status, attempt number, timing and the artifact ids it read and wrote."""
    name: str
    status: StepStatus
    attempt: int = Field(default=1, ge=1)
    started: datetime = Field(default_factory=_now)
    ended: Optional[datetime] = None
    input_ids: List[str] = Field(default_factory=list)
    output_ids: List[str] = Field(default_factory=list)
    error: Optional[str] = None


ExecutionStatus = Literal["QUEUED", "RUNNING", "WAITING_FOR_HUMAN", "COMPLETED", "FAILED", "BLOCKED", "CANCELLED"]
_TERMINAL = {"COMPLETED", "FAILED", "BLOCKED", "CANCELLED"}


class FrameworkExecution(BaseModel):
    """Executor-neutral run record. Transition methods return a new copy (history is append-only)."""

    execution_id: str
    framework: FrameworkId
    trace_id: str
    status: ExecutionStatus = "QUEUED"
    steps: List[ExecutionStep] = Field(default_factory=list)
    waiting_on: Optional[str] = None                # HumanTask id
    workflow: Optional[WorkflowRef] = None
    error: Optional[str] = None

    def _to(self, status: str, **upd: Any) -> "FrameworkExecution":
        """Return a deep copy with the new status and field updates; the original is left unchanged."""
        return self.model_copy(update={"status": status, **upd}, deep=True)

    def _require(self, *allowed: str) -> None:
        """Raise InvalidTransition unless the current status is one of the allowed ones."""
        if self.status not in allowed:
            raise InvalidTransition(f"{self.status}: expected one of {allowed}")

    def start(self) -> "FrameworkExecution":
        """QUEUED -> RUNNING."""
        self._require("QUEUED")
        return self._to("RUNNING")

    def step(self, step: ExecutionStep) -> "FrameworkExecution":
        """Return a copy, still RUNNING, with the step appended."""
        self._require("RUNNING")
        out = self._to("RUNNING")
        out.steps.append(step)
        return out

    def wait(self, human_task_id: str) -> "FrameworkExecution":
        """RUNNING -> WAITING_FOR_HUMAN, recording the human task being waited on."""
        self._require("RUNNING")
        return self._to("WAITING_FOR_HUMAN", waiting_on=human_task_id)

    def resume(self) -> "FrameworkExecution":
        """WAITING_FOR_HUMAN -> RUNNING, clearing the awaited task."""
        self._require("WAITING_FOR_HUMAN")
        return self._to("RUNNING", waiting_on=None)

    def fail(self, error: str) -> "FrameworkExecution":
        """RUNNING or WAITING_FOR_HUMAN -> FAILED with the error message."""
        self._require("RUNNING", "WAITING_FOR_HUMAN")
        return self._to("FAILED", error=error)

    def block(self, reason: str) -> "FrameworkExecution":
        """RUNNING -> BLOCKED with the reason stored as the error."""
        self._require("RUNNING")
        return self._to("BLOCKED", error=reason)

    def retry(self) -> "FrameworkExecution":
        """FAILED -> RUNNING, clearing the error."""
        self._require("FAILED")
        return self._to("RUNNING", error=None)

    def cancel(self) -> "FrameworkExecution":
        """Cancel from any non-terminal status; raises InvalidTransition if already terminal."""
        if self.status in _TERMINAL:
            raise InvalidTransition(f"{self.status}: already terminal")
        return self._to("CANCELLED", waiting_on=None)

    def complete(self) -> "FrameworkExecution":
        """RUNNING -> COMPLETED; refused while any step is ERROR or still RUNNING."""
        self._require("RUNNING")
        if any(s.status in ("ERROR", "RUNNING") for s in self.steps):
            raise InvalidTransition("cannot complete with failed or unfinished steps")
        return self._to("COMPLETED")


HumanTaskType = Literal[
    "RULE_REVIEW", "RISK_LI_CONFIRMATION", "PATTERN_APPROVAL", "RA_APPROVAL",
    "DECIDER_CLASSIFICATION_REVIEW", "EVIDENCE_REVIEW", "REMEDIATION_REVIEW",
    "RISK_ACCEPTANCE", "INVALID_CALM_CORRECTION",
]
HumanTaskStatus = Literal["OPEN", "ASSIGNED", "CLAIMED", "COMPLETED", "REJECTED", "CHANGES_REQUESTED", "CANCELLED"]
HumanAction = Literal["ASSIGN", "CLAIM", "COMPLETE", "REJECT", "REQUEST_CHANGES", "CANCEL"]


class HumanTask(BaseModel):
    """Human review work item. Needs at least one subject ref; permitted_actions limit what the actor may do and the role gates who may act."""
    task_id: str
    framework: FrameworkId
    task_type: HumanTaskType
    subject_refs: List[str] = Field(min_length=1)
    trace_id: Optional[str] = None
    status: HumanTaskStatus = "OPEN"
    role: str
    actor: Optional[str] = None
    permitted_actions: List[HumanAction] = Field(default_factory=lambda: ["CLAIM", "COMPLETE", "REJECT", "REQUEST_CHANGES", "CANCEL"])
    priority: Literal["LOW", "NORMAL", "HIGH", "CRITICAL"] = "NORMAL"
    created: datetime = Field(default_factory=_now)
    due: Optional[datetime] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    required_evidence: List[str] = Field(default_factory=list)


class HumanTaskOutcome(BaseModel):
    """Immutable record of one human action on a HumanTask."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    actor: str
    role: str
    action: HumanAction
    rationale: str = Field(min_length=1)
    timestamp: datetime = Field(default_factory=_now)
    outcome_artifact_id: Optional[str] = None
    previous_state: HumanTaskStatus
    resulting_state: HumanTaskStatus


EvidenceMaturity = Literal["DESIGN", "IMPLEMENTATION", "OPERATING"]


class AssessmentRequirement(BaseModel):
    """Evidence requirement derived from a control or risk, with the minimum evidence maturity and acceptance criteria."""
    requirement_id: str
    control_id: Optional[str] = None
    risk_id: Optional[str] = None
    description: str
    required_maturity: EvidenceMaturity = "DESIGN"
    evidence_criteria: List[str] = Field(default_factory=list)
    source: Dict[str, Any] = Field(default_factory=dict)


class Evidence(BaseModel):
    """Evidence item supplied for a requirement, hashed and tagged with maturity, validity and evaluation status."""
    evidence_id: str
    requirement_id: str
    evidence_type: str
    source: str
    app_id: str
    app_version: Optional[str] = None
    timestamp: datetime = Field(default_factory=_now)
    sha256: str
    maturity: EvidenceMaturity
    validity: Literal["VALID", "EXPIRED", "INVALID"] = "VALID"
    evaluation_status: Literal["PASS", "FAIL", "NOT_VERIFIED", "ERROR"] = "NOT_VERIFIED"
    reviewer: Optional[str] = None
    rationale: Optional[str] = None


class AcceptedClassification(BaseModel):
    """Decider answer accepted under policy (Option B). Original fact value is kept, never overwritten."""

    model_config = ConfigDict(frozen=True)

    fact_id: str
    original_raw: Any = None
    normalized: str
    question_type: Literal["noul", "choice", "score"]
    model: str
    model_version: Optional[str] = None
    input_hash: str
    answer: Any
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    margin: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    policy_version: str
    timestamp: datetime = Field(default_factory=_now)
    provenance: Dict[str, Any] = Field(default_factory=dict)


Artifact.model_rebuild()
FactSet.model_rebuild()
