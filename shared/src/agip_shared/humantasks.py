"""Shared file-backed HumanTask service (tasks 24.1, 24.2, 24.6).

RULE: act() never executes side effects. It only records an outcome and moves the
task state. Approving an artifact never grants any financial or privileged action;
callers (e.g. the Direct Adapter) resume execution themselves, optionally through
``ResumeCallbacks`` which are invoked after COMPLETED / REJECTED.

Layout: <data_dir>/human_tasks/<task_id>.json (task, atomically replaced) and
<data_dir>/human_tasks/<task_id>.outcomes.jsonl (append-only outcomes).
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Union

from .contracts import HumanAction, HumanTask, HumanTaskOutcome, HumanTaskStatus

TERMINAL = {"COMPLETED", "REJECTED", "CANCELLED"}

# action -> {previous_state: resulting_state}
TRANSITIONS: Dict[str, Dict[str, str]] = {
    "ASSIGN": {"OPEN": "ASSIGNED"},
    "CLAIM": {"OPEN": "CLAIMED", "ASSIGNED": "CLAIMED", "CHANGES_REQUESTED": "CLAIMED"},
    "COMPLETE": {"CLAIMED": "COMPLETED"},
    "REJECT": {"CLAIMED": "REJECTED"},
    "REQUEST_CHANGES": {"CLAIMED": "CHANGES_REQUESTED"},
    "CANCEL": {"OPEN": "CANCELLED", "ASSIGNED": "CANCELLED", "CLAIMED": "CANCELLED",
               "CHANGES_REQUESTED": "CANCELLED"},
}

# task_type -> roles allowed to act (shared default; override via YAML/dict).
DEFAULT_ROLES: Dict[str, List[str]] = {
    "RULE_REVIEW": ["rule_reviewer", "governance_admin"],
    "RISK_LI_CONFIRMATION": ["risk_analyst", "governance_admin"],
    "PATTERN_APPROVAL": ["architect", "governance_admin"],
    "RA_APPROVAL": ["risk_approver", "governance_admin"],
    "DECIDER_CLASSIFICATION_REVIEW": ["risk_analyst", "governance_admin"],
    "EVIDENCE_REVIEW": ["evidence_reviewer", "governance_admin"],
    "REMEDIATION_REVIEW": ["risk_analyst", "governance_admin"],
    "RISK_ACCEPTANCE": ["risk_approver", "governance_admin"],
    "INVALID_CALM_CORRECTION": ["architect", "governance_admin"],
}


class HumanTaskError(Exception):
    """Base class for human task store errors."""
    pass


class TaskNotFound(HumanTaskError):
    """No task exists with the requested id."""
    pass


class TaskExists(HumanTaskError):
    """A task with this id has already been created."""
    pass


class InvalidTaskTransition(HumanTaskError):
    """The requested action is not allowed from the task's current state."""
    pass


class NotAuthorized(HumanTaskError):
    """The actor's role may not perform the action on this task."""
    pass


def load_roles(path: Optional[Union[str, Path]] = None) -> Dict[str, List[str]]:
    """Default roles merged with an optional YAML/JSON file (task_type -> [roles])."""
    roles = {k: list(v) for k, v in DEFAULT_ROLES.items()}
    if path and Path(path).exists():
        text = Path(path).read_text(encoding="utf-8")
        try:
            import yaml  # optional
            data = yaml.safe_load(text)
        except ImportError:
            data = json.loads(text)
        for k, v in (data or {}).items():
            roles[k] = list(v)
    return roles


class ResumeCallbacks:
    """Minimal registry: fn(task, outcome) called after COMPLETED / REJECTED."""

    def __init__(self) -> None:
        """Start with no callbacks registered."""
        self._fns: Dict[str, List[Callable[[HumanTask, HumanTaskOutcome], Any]]] = {}

    def register(self, task_type: str, fn: Callable[[HumanTask, HumanTaskOutcome], Any]) -> None:
        """Add a callback for a task type; several may be registered per type."""
        self._fns.setdefault(task_type, []).append(fn)

    def invoke(self, task: HumanTask, outcome: HumanTaskOutcome) -> None:
        """Run the callbacks for the task's type, only when the outcome is COMPLETED or REJECTED (terminal decisions)."""
        if outcome.resulting_state in ("COMPLETED", "REJECTED"):
            for fn in self._fns.get(task.task_type, []):
                fn(task, outcome)


resume_callbacks = ResumeCallbacks()
_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


class HumanTaskStore:
    """File-backed human task store: one JSON file per task plus a JSONL outcome log, guarded by an in-process lock."""
    def __init__(self, data_dir: Union[str, Path], roles: Optional[Dict[str, List[str]]] = None,
                 roles_path: Optional[Union[str, Path]] = None,
                 callbacks: Optional[ResumeCallbacks] = None) -> None:
        """Create <data_dir>/human_tasks; roles come from the argument, else roles_path/default config. Callbacks default to the module-level registry."""
        self.dir = Path(data_dir) / "human_tasks"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.roles = roles if roles is not None else load_roles(roles_path)
        self.callbacks = callbacks if callbacks is not None else resume_callbacks
        self._lock = threading.RLock()

    # -- paths / io
    def _p(self, task_id: str, suffix: str) -> Path:
        """Path of a task file with the given suffix; rejects ids that could escape the directory."""
        if not _ID.match(task_id) or task_id in (".", ".."):
            raise HumanTaskError(f"invalid task_id: {task_id!r}")
        return self.dir / f"{task_id}{suffix}"

    def _write_atomic(self, path: Path, task: HumanTask) -> None:
        """Write via a temp file then os.replace so readers never see a partial file."""
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(task.model_dump_json(), encoding="utf-8")
        os.replace(tmp, path)

    # -- API
    def create(self, task: HumanTask) -> HumanTask:
        """Persist a new task; raises TaskExists if the id is taken (exclusive-create, so concurrent creates cannot overwrite)."""
        path = self._p(task.task_id, ".json")
        with self._lock:
            try:
                with open(path, "x", encoding="utf-8") as f:  # exclusive create
                    f.write(task.model_dump_json())
            except FileExistsError:
                raise TaskExists(task.task_id)
        return task

    def get(self, task_id: str) -> HumanTask:
        """Load a task by id; raises TaskNotFound if missing."""
        path = self._p(task_id, ".json")
        if not path.exists():
            raise TaskNotFound(task_id)
        return HumanTask.model_validate_json(path.read_text(encoding="utf-8"))

    def outcomes(self, task_id: str) -> List[HumanTaskOutcome]:
        """Recorded outcomes for a task in the order they were appended; empty if none."""
        path = self._p(task_id, ".outcomes.jsonl")
        if not path.exists():
            return []
        return [HumanTaskOutcome.model_validate_json(line)
                for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def list(self, framework: Optional[str] = None, task_type: Optional[str] = None,
             status: Optional[str] = None, role: Optional[str] = None,
             actor: Optional[str] = None, subject_ref: Optional[str] = None,
             trace_id: Optional[str] = None, app: Optional[str] = None,
             priority: Optional[str] = None) -> List[HumanTask]:
        """Tasks matching all given filters (None skips a filter). trace_id and app also match the task context."""
        out: List[HumanTask] = []
        for f in sorted(self.dir.glob("*.json")):
            if f.name.startswith("."):
                continue
            t = HumanTask.model_validate_json(f.read_text(encoding="utf-8"))
            if framework and t.framework != framework: continue
            if task_type and t.task_type != task_type: continue
            if status and t.status != status: continue
            if role and t.role != role: continue
            if actor and t.actor != actor: continue
            if priority and t.priority != priority: continue
            if trace_id and t.trace_id != trace_id and t.context.get("trace_id") != trace_id: continue
            if subject_ref and subject_ref not in t.subject_refs: continue
            if app and app not in t.subject_refs and t.context.get("app") != app: continue
            out.append(t)
        return out

    def _allowed_roles(self, task: HumanTask) -> Set[str]:
        """Roles permitted to act on the task: the configured roles for its type, else just the task's own role."""
        return set(self.roles.get(task.task_type) or [task.role])

    def act(self, task_id: str, actor: str, role: str, action: HumanAction, rationale: str,
            outcome_artifact_id: Optional[str] = None) -> HumanTaskOutcome:
        """Record one human action. Never performs side effects (see module docstring)."""
        with self._lock:
            task = self.get(task_id)
            if role not in self._allowed_roles(task):
                raise NotAuthorized(f"role {role!r} may not act on {task.task_type}")
            if action not in task.permitted_actions:
                raise NotAuthorized(f"action {action} not permitted on task {task_id}")
            nxt = TRANSITIONS.get(action, {}).get(task.status)
            if nxt is None:
                raise InvalidTaskTransition(f"{action} not valid from {task.status}")
            if action == "COMPLETE" and task.context.get("created_by") == actor:
                raise NotAuthorized("self-approval refused: actor created the subject")
            outcome = HumanTaskOutcome(
                task_id=task_id, actor=actor, role=role, action=action, rationale=rationale,
                outcome_artifact_id=outcome_artifact_id,
                previous_state=task.status, resulting_state=nxt)
            with open(self._p(task_id, ".outcomes.jsonl"), "a", encoding="utf-8") as f:
                f.write(outcome.model_dump_json() + "\n")
            keep_actor = nxt in ("ASSIGNED", "CLAIMED", "COMPLETED", "REJECTED", "CHANGES_REQUESTED")
            task = task.model_copy(update={"status": nxt, "actor": actor if keep_actor else task.actor})
            self._write_atomic(self._p(task_id, ".json"), task)
        self.callbacks.invoke(task, outcome)
        return outcome
