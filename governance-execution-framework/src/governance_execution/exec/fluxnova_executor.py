"""FluxnovaExecutor: same ``execute(coordinator, steps, trace_id, refs, log)`` interface as DirectAdapter, but every
step is an external task of a Fluxnova process instance (workflow generated from the step list)."""
from __future__ import annotations

import hashlib
import json
import threading
from typing import Any, Optional

from opentelemetry import context as otel_context

from .bpmn import Workflow, WfStep
from .fluxnova_client import FluxnovaClient
from .fluxnova_runner import RunResult, deploy_if_missing, run_workflow


class FluxnovaUnavailable(Exception):
    """Raised when the Fluxnova engine cannot be reached."""
    pass


def assessment_workflow(steps: tuple) -> Workflow:
    """Build the Workflow for ``steps``: fixed keys for the governance and blocked step lists, otherwise a key derived from a hash of the step names."""
    from .coordinator import BLOCKED_STEPS, GOVERNANCE_STEPS
    if steps == GOVERNANCE_STEPS:
        key, name = "assessment_lifecycle", "Assessment Lifecycle"
    elif steps == BLOCKED_STEPS:
        key, name = "assessment_blocked", "Assessment Lifecycle (blocked CALM)"
    else:
        h = hashlib.sha256("|".join(s.name for s in steps).encode()).hexdigest()[:8]
        key, name = f"assessment_part_{h}", "Assessment Lifecycle (part)"
    return Workflow(key, name, tuple(WfStep(s.name, s.name.replace("_", " "), group=s.parallel_group) for s in steps))


class FluxnovaExecutor:
    """Executor that runs each step as an external task of a Fluxnova process instance."""
    label = "Fluxnova"
    note = ""

    def __init__(self, client: Optional[FluxnovaClient] = None, url: str = "http://localhost:8080/engine-rest",
                 timeout_s: float = 300.0):
        """Use ``client``, or create one for ``url``; ``timeout_s`` bounds one workflow run. ``runs`` collects each RunResult."""
        self.client = client or FluxnovaClient(url)
        self.timeout_s = timeout_s
        self.runs: list[RunResult] = []

    def execute(self, coordinator: Any, steps: tuple, trace_id: str, refs: dict[str, str],
                log: list[dict[str, Any]]) -> tuple[bool, Optional[str]]:
        """Run ``steps`` as a Fluxnova workflow. Raises FluxnovaUnavailable if the engine is unreachable; returns (ok, error) like DirectAdapter."""
        if not self.client.available():
            raise FluxnovaUnavailable(f"Fluxnova not reachable at {self.client.base}")
        wf = assessment_workflow(steps)
        by_name = {s.name: s for s in steps}
        ctx = otel_context.get_current()
        lock = threading.Lock()
        results: dict[str, Any] = {}

        def handler_for(name: str):
            """Build the external-task handler for step ``name``."""
            def handle(_vars: dict[str, Any]) -> dict[str, Any]:
                """Run the step through the coordinator and log it under a lock (parallel steps share ``log`` and ``refs``). Raises RuntimeError on a non-OK step so the engine records a failure."""
                token = otel_context.attach(ctx)
                try:
                    step = by_name[name]
                    res = coordinator.run_step(step, trace_id, dict(refs))
                finally:
                    otel_context.detach(token)
                with lock:
                    results[name] = res
                    log.append({"step": step.name, "unit": step.unit, "status": res.status, "error": res.error,
                                "parallel_group": step.parallel_group, "outputs": res.artifact_ids})
                    if res.status == "OK":
                        refs.update({r.partition(":")[0]: r for r in res.artifact_ids})
                if res.status != "OK":
                    raise RuntimeError(res.error or "step failed")
                return {f"out_{name}": sorted(res.artifact_ids)}   # IDs only, one variable per step (parallel-safe)
            return handle

        run = run_workflow(self.client, wf, {s.name: handler_for(s.name) for s in steps},
                           {"trace_id": trace_id, "framework": "governance_execution"},
                           business_key=trace_id, timeout_s=self.timeout_s)
        self.runs.append(run)
        if run.status != "COMPLETED":
            return False, run.error or run.status
        return True, None
