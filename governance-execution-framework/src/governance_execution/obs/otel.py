"""Observability: one OTel trace per assessment, span per stage, secret scrubbing,
and a recorder for all versioned inputs (stored as the `versions` artifact)."""
from __future__ import annotations

import logging
import re
import sys
from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)

REDACTED = "[REDACTED]"
_SECRET_KEY = re.compile(
    r"(secret|token|password|passwd|api[_-]?key|authorization|credential|private[_-]?key)", re.I
)
_SECRET_VALUE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|"
    r"Bearer\s+[A-Za-z0-9._\-]+|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
_INLINE_ASSIGN = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|authorization)\b(\s*[=:]\s*)\S+"
)


def scrub_text(text: str) -> str:
    """Redact inline ``key=value`` secrets and known secret formats (API keys, AWS keys, GitHub tokens, bearer tokens, private keys) in text."""
    text = _INLINE_ASSIGN.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
    return _SECRET_VALUE.sub(REDACTED, text)


def scrub(value: Any, key: str | None = None) -> Any:
    """Recursively redact secrets in attributes/log payloads."""
    if key is not None and _SECRET_KEY.search(key):
        return REDACTED
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        return {k: scrub(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    return value


class ScrubbingLogFilter(logging.Filter):
    """Logging filter that redacts secrets from every record before it is emitted."""
    def filter(self, record: logging.LogRecord) -> bool:
        """Pre-format the message, scrub it and clear ``args`` so later formatting cannot reintroduce secrets. Always keeps the record."""
        record.msg = scrub_text(record.getMessage())
        record.args = ()
        return True


def install_log_scrubbing(logger: logging.Logger | None = None) -> None:
    """Attach ScrubbingLogFilter to ``logger`` (default: root logger). Mutates the logger; calling twice adds two filters."""
    (logger or logging.getLogger()).addFilter(ScrubbingLogFilter())


def _attr(v: Any) -> Any:
    """Coerce a value to a type OpenTelemetry attributes accept (str, bool, int, float); anything else becomes ``str(v)``."""
    return v if isinstance(v, (str, bool, int, float)) else str(v)


class Tracing:
    """One trace per assessment; one span per stage."""

    def __init__(self, exporter: SpanExporter | None = None, out=None) -> None:
        """Create a private TracerProvider that exports each span immediately (default: console on stderr)."""
        self.provider = TracerProvider()
        self.provider.add_span_processor(
            SimpleSpanProcessor(exporter or ConsoleSpanExporter(out=out or sys.stderr))
        )
        self.tracer = self.provider.get_tracer("governance_execution")
        self.trace_id: str | None = None

    @contextmanager
    def assessment(self, name: str = "assessment", **attrs: Any) -> Iterator[str]:
        """Open the root span, store its 32-hex trace id on ``self.trace_id`` and yield it. Attributes are scrubbed."""
        with self.tracer.start_as_current_span(name) as span:
            self.trace_id = format(span.get_span_context().trace_id, "032x")
            self._set(span, attrs)
            span.set_attribute("trace_id", self.trace_id)
            yield self.trace_id

    @contextmanager
    def stage(self, name: str, **attrs: Any) -> Iterator[Any]:
        """Open a child span for one pipeline stage and yield it. Attributes are scrubbed."""
        with self.tracer.start_as_current_span(name) as span:
            self._set(span, attrs)
            yield span

    @staticmethod
    def _set(span, attrs: dict[str, Any]) -> None:
        """Set scrubbed attributes on ``span``."""
        for k, v in scrub(attrs).items():
            span.set_attribute(k, _attr(v))

    def attach(self, artifact: dict[str, Any]) -> dict[str, Any]:
        """Attach the current Trace_ID to an artifact record."""
        artifact["trace_id"] = self.trace_id
        return artifact

    def shutdown(self) -> None:
        """Flush and shut down the tracer provider."""
        self.provider.shutdown()


class VersionsRecorder:
    """Collects every versioned input of an assessment."""

    SECTIONS = (
        "rulesets", "catalogs", "scoring_profile", "matrix", "gates", "taxonomy",
        "calm", "spectral", "prompts", "models",
    )

    def __init__(self) -> None:
        """Start with an empty dict for every section in SECTIONS."""
        self._data: dict[str, Any] = {s: {} for s in self.SECTIONS}

    def record(self, section: str, name: str, version: str, sha: str | None = None) -> None:
        """Record ``name`` in ``section`` with its version and optional sha, replacing any earlier entry. Unknown sections are created."""
        entry: dict[str, Any] = {"version": version}
        if sha:
            entry["sha"] = sha
        self._data.setdefault(section, {})[name] = entry

    def to_dict(self) -> dict[str, Any]:
        """Copy of all recorded versions with secrets scrubbed."""
        return scrub({k: dict(v) for k, v in self._data.items()})
