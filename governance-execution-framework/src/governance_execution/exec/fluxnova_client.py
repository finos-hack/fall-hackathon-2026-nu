"""Fluxnova REST client (stdlib only). Paths follow the Camunda 7 style ``/engine-rest`` API confirmed by the spike
(docs/spike/fluxnova.md): deployment/create, process-definition start, external-task fetchAndLock/complete/failure,
task list/complete, process-instance and history lookups."""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional
from urllib import error, request


class FluxnovaError(Exception):
    """Engine unreachable or returned an error. ``status`` is the HTTP status (0 when unreachable)."""

    def __init__(self, message: str, status: int = 0):
        """Store the HTTP status alongside the message."""
        super().__init__(message)
        self.status = status


def _var(value: Any) -> dict[str, Any]:
    """Encode a Python value as an engine variable: Boolean, Long, Json (dict/list, sorted keys) or String (None becomes an empty string)."""
    if isinstance(value, bool):
        return {"value": value, "type": "Boolean"}
    if isinstance(value, int):
        return {"value": value, "type": "Long"}
    if isinstance(value, (dict, list)):
        return {"value": json.dumps(value, sort_keys=True), "type": "Json"}
    return {"value": "" if value is None else str(value), "type": "String"}


def to_variables(values: dict[str, Any]) -> dict[str, Any]:
    """Encode a dict as engine variables with ``_var``."""
    return {k: _var(v) for k, v in values.items()}


def from_variables(variables: dict[str, Any]) -> dict[str, Any]:
    """Decode engine variables to plain values; Json values are parsed, and unparseable ones are kept as text."""
    out = {}
    for k, v in (variables or {}).items():
        val = v.get("value")
        if v.get("type") == "Json" and isinstance(val, str):
            try:
                val = json.loads(val)
            except ValueError:
                pass
        out[k] = val
    return out


class FluxnovaClient:
    """Minimal REST client for the Fluxnova (Camunda 7 style) engine. Errors are raised as FluxnovaError."""
    def __init__(self, base_url: str = "http://localhost:8080/engine-rest", timeout_s: float = 10.0,
                 worker_id: Optional[str] = None):
        """``worker_id`` identifies this worker when locking external tasks (random if not given)."""
        self.base = base_url.rstrip("/")
        self.timeout = timeout_s
        self.worker_id = worker_id or f"agip-worker-{uuid.uuid4().hex[:8]}"

    def _call(self, method: str, path: str, body: Any = None, *, raw: Optional[tuple[bytes, str]] = None) -> Any:
        """Send one JSON (or raw multipart) request and return the parsed body, or None for an empty body. Raises FluxnovaError with the HTTP status, or status 0 when unreachable."""
        data, headers = None, {"Accept": "application/json"}
        if raw is not None:
            data, headers["Content-Type"] = raw
        elif body is not None:
            data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
        req = request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with request.urlopen(req, timeout=self.timeout) as r:
                text = r.read().decode("utf-8")
                return json.loads(text) if text else None
        except error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise FluxnovaError(f"{method} {path} -> {e.code}: {detail}", e.code) from e
        except (error.URLError, TimeoutError, OSError) as e:
            raise FluxnovaError(f"{method} {path} unreachable: {e}") from e

    # health and discovery
    def health(self) -> str:
        """Engine version string."""
        return self._call("GET", "/version")["version"]

    def available(self) -> bool:
        """True if the engine answers its version endpoint."""
        try:
            self.health()
            return True
        except FluxnovaError:
            return False

    # deployment and process definitions
    def deploy(self, name: str, filename: str, xml: str) -> dict[str, Any]:
        """Deploy BPMN XML as a multipart upload with duplicate filtering, so unchanged XML does not create a new version."""
        b = uuid.uuid4().hex
        parts = []
        for field, value in (("deployment-name", name), ("enable-duplicate-filtering", "true"),
                             ("deployment-source", "agip")):
            parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{field}"\r\n\r\n{value}\r\n')
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="data"; filename="{filename}"\r\n'
                     f'Content-Type: text/xml\r\n\r\n{xml}\r\n')
        payload = ("".join(parts) + f"--{b}--\r\n").encode("utf-8")
        return self._call("POST", "/deployment/create", raw=(payload, f"multipart/form-data; boundary={b}"))

    def latest_definition(self, key: str) -> Optional[dict[str, Any]]:
        """Latest process definition for ``key``, or None if there is none (HTTP 404)."""
        try:
            return self._call("GET", f"/process-definition/key/{key}")
        except FluxnovaError as e:
            if e.status == 404:
                return None
            raise

    def start(self, key: str, variables: dict[str, Any], business_key: Optional[str] = None) -> dict[str, Any]:
        """Start an instance of process ``key`` with variables and an optional business key."""
        body: dict[str, Any] = {"variables": to_variables(variables)}
        if business_key:
            body["businessKey"] = business_key
        return self._call("POST", f"/process-definition/key/{key}/start", body)

    # external tasks
    def fetch_and_lock(self, topics: list[str], instance_id: str, lock_ms: int = 60000, max_tasks: int = 10) -> list[dict[str, Any]]:
        """Lock available external tasks on ``topics`` for this instance only; returns an empty list if none."""
        body = {"workerId": self.worker_id, "maxTasks": max_tasks, "usePriority": False,
                "topics": [{"topicName": t, "lockDuration": lock_ms, "processInstanceId": instance_id} for t in topics]}
        return self._call("POST", "/external-task/fetchAndLock", body) or []

    def complete_external(self, task_id: str, variables: Optional[dict[str, Any]] = None, attempts: int = 6) -> None:
        """Parallel branches that join can hit OptimisticLockingException; the engine rolled back, so retrying is safe."""
        for n in range(attempts):
            try:
                self._call("POST", f"/external-task/{task_id}/complete",
                           {"workerId": self.worker_id, "variables": to_variables(variables or {})})
                return
            except FluxnovaError as e:
                if e.status != 500 or "OptimisticLocking" not in str(e) or n == attempts - 1:
                    raise
                time.sleep(0.15 * (n + 1))

    def fail_external(self, task_id: str, message: str, details: str = "", retries: int = 0, retry_timeout_ms: int = 0) -> None:
        """Report an external task failure (message and details are truncated). With retries=0 the engine raises an incident."""
        self._call("POST", f"/external-task/{task_id}/failure",
                   {"workerId": self.worker_id, "errorMessage": message[:500], "errorDetails": details[:4000],
                    "retries": retries, "retryTimeout": retry_timeout_ms})

    # user tasks
    def tasks(self, instance_id: str) -> list[dict[str, Any]]:
        """Open user tasks of the instance."""
        return self._call("GET", f"/task?processInstanceId={instance_id}") or []

    def claim(self, task_id: str, user: str) -> None:
        """Assign a user task to ``user``."""
        self._call("POST", f"/task/{task_id}/claim", {"userId": user})

    def complete_task(self, task_id: str, variables: Optional[dict[str, Any]] = None) -> None:
        """Complete a user task with output variables."""
        self._call("POST", f"/task/{task_id}/complete", {"variables": to_variables(variables or {})})

    # status and variables
    def instance(self, instance_id: str) -> Optional[dict[str, Any]]:
        """The running process instance, or None once it has ended (HTTP 404)."""
        try:
            return self._call("GET", f"/process-instance/{instance_id}")
        except FluxnovaError as e:
            if e.status == 404:
                return None
            raise

    def history_instance(self, instance_id: str) -> dict[str, Any]:
        """History record of the instance, including its final state."""
        return self._call("GET", f"/history/process-instance/{instance_id}")

    def incidents(self, instance_id: str) -> list[dict[str, Any]]:
        """Open incidents of the instance."""
        return self._call("GET", f"/incident?processInstanceId={instance_id}") or []

    def variables(self, instance_id: str) -> dict[str, Any]:
        """Current variables of the instance, decoded."""
        return from_variables(self._call("GET", f"/process-instance/{instance_id}/variables") or {})

    def history_variables(self, instance_id: str) -> dict[str, Any]:
        """Variables of a finished instance as {name: raw value}."""
        rows = self._call("GET", f"/history/variable-instance?processInstanceId={instance_id}") or []
        return {r["name"]: r["value"] for r in rows}

    def human_task_completer(self, instance_id: str, task_key: str) -> Optional[str]:
        """Who completed a user task (assignee in history), for tasks completed in Tasklist."""
        rows = self._call("GET", f"/history/task?processInstanceId={instance_id}&taskDefinitionKey={task_key}&finished=true") or []
        return (rows[-1].get("assignee") or None) if rows else None

    def cancel(self, instance_id: str, reason: str = "cancelled") -> None:
        """Delete the running instance (custom listeners are skipped). ``reason`` is accepted but not sent to the engine."""
        self._call("DELETE", f"/process-instance/{instance_id}?skipCustomListeners=true")
