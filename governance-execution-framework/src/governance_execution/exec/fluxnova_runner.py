"""Generic Fluxnova workflow runner: deploy the BPMN if missing, start an instance, and act as the external-task
worker until the instance ends, fails, or waits on a user task. Handlers hold the business logic; the engine holds
only process state and artifact IDs (never artifact content)."""
from __future__ import annotations

import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .bpmn import Workflow, xml_for
from .fluxnova_client import FluxnovaClient, FluxnovaError

Handler = Callable[[dict[str, Any]], Optional[dict[str, Any]]]     # variables -> output variables
UserHandler = Callable[[dict[str, Any], dict[str, Any]], Optional[dict[str, Any]]]   # task, variables -> variables


@dataclass
class RunResult:
    """Outcome of one workflow run, with the engine instance and definition ids, per-step records and any waiting user tasks."""
    instance_id: str
    process_key: str
    process_definition_id: str
    version: int
    status: str                      # COMPLETED | FAILED | WAITING_FOR_HUMAN | TIMEOUT
    error: Optional[str] = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    waiting_tasks: list[dict[str, Any]] = field(default_factory=list)


def deploy_if_missing(client: FluxnovaClient, wf: Workflow) -> dict[str, Any]:
    """Deploy (duplicate filtering makes this a no-op when the BPMN is unchanged) and return the definition."""
    client.deploy(f"{wf.key}", f"{wf.key}.bpmn", xml_for(wf))
    d = client.latest_definition(wf.key)
    if d is None:
        raise FluxnovaError(f"process definition {wf.key} not found after deploy")
    return d


def run_workflow(client: FluxnovaClient, wf: Workflow, handlers: dict[str, Handler], variables: dict[str, Any], *,
                 user_handler: Optional[UserHandler] = None, business_key: Optional[str] = None,
                 poll_s: float = 0.25, timeout_s: float = 300.0, on_step: Optional[Callable[[dict[str, Any]], None]] = None,
                 instance_id: Optional[str] = None, definition: Optional[dict[str, Any]] = None,
                 wait_for_humans: bool = False) -> RunResult:
    """Start (or continue) an instance and work its external tasks with ``handlers`` until it completes, fails, times out or waits for a human. Handler errors fail the task with no retries and end the run as FAILED."""
    d = definition or deploy_if_missing(client, wf)
    if instance_id is None:
        instance_id = client.start(wf.key, variables, business_key)["id"]
    res = RunResult(instance_id, wf.key, d["id"], int(d.get("version", 0)), "RUNNING")
    topics = [s.name for s in wf.steps if s.kind == "service"]
    done: set[str] = set()
    announced: set[str] = set()
    deadline = time.monotonic() + timeout_s

    def work(task: dict[str, Any]) -> None:
        """Run the handler for one locked task, then complete or fail it, and record the result in ``res.steps``."""
        name = task["topicName"]
        vars_now = {k: v.get("value") for k, v in (task.get("variables") or {}).items()}
        vars_now["_instance_id"] = task.get("processInstanceId")
        try:
            out = handlers[name](vars_now) or {}
            client.complete_external(task["id"], out)
            done.add(task["id"])
            rec = {"step": name, "status": "OK", "task_id": task["id"]}
        except Exception as e:  # a failed step is never marked successful: report failure, retries=0 raises an incident
            client.fail_external(task["id"], f"{name}: {e}", traceback.format_exc(), retries=0)
            rec = {"step": name, "status": "ERROR", "task_id": task["id"], "error": f"{name}: {e}"}
        res.steps.append(rec)
        if on_step:
            on_step(rec)

    while time.monotonic() < deadline:
        tasks = client.fetch_and_lock(topics, instance_id) if topics else []
        if len(tasks) > 1:
            with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
                list(pool.map(work, tasks))
        else:
            for t in tasks:
                work(t)
        if any(s["status"] == "ERROR" for s in res.steps):
            res.status, res.error = "FAILED", next(s["error"] for s in res.steps if s["status"] == "ERROR")
            return res
        if client.instance(instance_id) is None:
            h = client.history_instance(instance_id)
            res.status = "COMPLETED" if h.get("state") == "COMPLETED" else "FAILED"
            if res.status == "FAILED":
                res.error = f"process ended in state {h.get('state')}"
            return res
        utasks = client.tasks(instance_id)
        if utasks:
            if user_handler is None:
                if wait_for_humans:          # a person completes the task in Tasklist; keep the instance and keep polling
                    for ut in utasks:
                        if ut["id"] not in announced:
                            announced.add(ut["id"])
                            if on_step:
                                on_step({"step": ut["taskDefinitionKey"], "status": "WAITING_FOR_HUMAN", "task_id": ut["id"]})
                    time.sleep(max(poll_s, 1.0))
                    continue
                res.status, res.waiting_tasks = "WAITING_FOR_HUMAN", utasks
                return res
            for ut in utasks:
                vars_now = client.variables(instance_id)
                out = user_handler(ut, vars_now) or {}
                client.complete_task(ut["id"], out)
                rec = {"step": ut["taskDefinitionKey"], "status": "OK", "task_id": ut["id"], "user_task": True}
                res.steps.append(rec)
                if on_step:
                    on_step(rec)
            continue
        if not tasks:
            time.sleep(poll_s)
    res.status, res.error = "TIMEOUT", f"instance {instance_id} did not finish in {timeout_s}s"
    return res
