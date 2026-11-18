"""Direct_Adapter: runs the Coordinator steps in-process, with ``threading`` for the two Spectral lanes (Req 22.4, 22.5).

It is the MVP Executor because the Fluxnova spike was deferred; the Dashboard and spike notes label it
development-only.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from opentelemetry import context as otel_context


class DirectAdapter:
    """In-process Executor: runs steps in order, running each parallel group in a thread pool."""
    label = "Direct_Adapter"
    note = "development-only executor (Fluxnova spike deferred)"

    def execute(self, coordinator: Any, steps: tuple, trace_id: str, refs: dict[str, str],
                log: list[dict[str, Any]]) -> tuple[bool, Optional[str]]:
        """Run ``steps`` and append one log entry per step; stops at the first non-OK step. Returns (ok, error) and updates ``refs`` with each step's output artifact refs."""
        i = 0
        while i < len(steps):
            group = steps[i].parallel_group
            batch = [steps[i]]
            if group:
                while i + len(batch) < len(steps) and steps[i + len(batch)].parallel_group == group:
                    batch.append(steps[i + len(batch)])
            ctx = otel_context.get_current()   # pool threads do not inherit it; call() re-attaches it

            def call(step):
                """Run one step in a worker thread with the caller's OpenTelemetry context attached, so spans nest correctly."""
                token = otel_context.attach(ctx)
                try:
                    return step, coordinator.run_step(step, trace_id, refs)
                finally:
                    otel_context.detach(token)

            if len(batch) > 1:
                with ThreadPoolExecutor(max_workers=len(batch), thread_name_prefix=group) as pool:
                    results = list(pool.map(call, batch))
            else:
                results = [call(batch[0])]
            for step, res in results:
                log.append({"step": step.name, "unit": step.unit, "status": res.status, "error": res.error,
                            "parallel_group": step.parallel_group, "outputs": res.artifact_ids})
                if res.status != "OK":
                    return False, f"{step.name}: {res.error}"
                refs.update({r.partition(":")[0]: r for r in res.artifact_ids})
            i += len(batch)
        return True, None
