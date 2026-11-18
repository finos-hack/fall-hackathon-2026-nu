"""ModelGateway: ``complete(prompt_id, version, input) -> Extraction_Record``.

Providers: ``bedrock`` (live, via an injected runtime), ``none`` (LLM disabled),
``replay`` (serve recorded outputs only). Secrets and file paths are stripped from
every input before hashing, recording or sending (Req 4.7, 12.5). No runtime-specific
types appear here; the Strands adapter lives in ``runtime_strands.py``.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional, Protocol

from agip_shared.contracts import Extraction_Record
from agip_shared.hashing import canonical_hash, canonical_json, sha256_hex

from .recorder import Recorder

REDACTED = "[REDACTED]"
_SECRET_KEY = re.compile(r"(secret|password|passwd|token|api[_-]?key|credential|authorization|private[_-]?key)", re.I)
_SECRET_VALUE = [
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{12,}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\b(secret|password|passwd|token|api[_-]?key)\b\s*[:=]\s*\S+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b[A-Za-z0-9/+=]{40,}\b"),
]
_PATH = [
    re.compile(r"(?<!\w)[A-Za-z]:[\\/](?![\\/])[^\s\"']*"),                      # C:\x\y
    re.compile(r"\\\\[^\s\"']+"),                                 # \\server\share
    re.compile(r"(?<![\w/:.])~?(?:\.{1,2})?/(?:[\w.\-]+/)*[\w.\-]+"),  # /a/b, ./a/b, ~/a
]


class ModelUnavailableError(RuntimeError):
    """Provider is ``none`` or the live runtime failed."""


class RecordingMissingError(LookupError):
    """Replay requested a record that was never recorded."""


class Runtime(Protocol):
    """Protocol for a live model backend that turns a prompt into text."""
    def complete(self, prompt: str, model: str, region: str) -> str:
        """Return the model's text answer for the prompt."""
        ...


def _scrub_text(text: str) -> str:
    """Redact secret-looking values and filesystem paths so they do not leak into error messages."""
    for rx in _SECRET_VALUE:
        text = rx.sub(REDACTED, text)
    for rx in _PATH:
        text = rx.sub(REDACTED, text)
    return text


def sanitize(value: Any) -> Any:
    """Return a copy with secret-looking keys/values and file paths replaced."""
    if isinstance(value, str):
        return _scrub_text(value)
    if isinstance(value, dict):
        return {str(k): (REDACTED if _SECRET_KEY.search(str(k)) else sanitize(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(v) for v in value]
    return value


def _parse_output(text: str) -> Any:
    """Parse model output as JSON, tolerating a surrounding code fence; return the raw text if it is not JSON."""
    body = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", body, re.S)
    if m:
        body = m.group(1)
    try:
        return json.loads(body)
    except ValueError:
        return text


class ModelGateway:
    """Single entry point for model calls. Providers: 'none' (always unavailable), 'replay' (recordings only) and 'bedrock' (live, with record and reuse)."""
    def __init__(self, provider: str = "none", model: str = "", region: str = "",
                 recorder: Optional[Recorder] = None, runtime: Optional[Runtime] = None):
        """Raise ValueError for an unknown provider."""
        if provider not in ("bedrock", "none", "replay"):
            raise ValueError(f"unknown provider: {provider}")
        self.provider, self.model, self.region = provider, model, region
        self.recorder, self.runtime = recorder, runtime
        self.reused = 0   # live calls answered from a matching recording (same inputs_hash)

    @classmethod
    def from_settings(cls, settings: Any, recorder: Optional[Recorder] = None,
                      runtime: Optional[Runtime] = None) -> "ModelGateway":
        """Build a gateway from a settings object's model_provider, bedrock_model_id and aws_region."""
        return cls(settings.model_provider, settings.bedrock_model_id, settings.aws_region, recorder, runtime)

    @staticmethod
    def input_hash(prompt_id: str, version: str, clean_input: Any) -> str:
        """Hash identifying a call by prompt id, prompt version and sanitized input."""
        return canonical_hash({"prompt_id": prompt_id, "prompt_version": version, "input": clean_input})

    def complete(self, prompt_id: str, version: str, input: Any, prompt: str = "",
                 item_id: Optional[str] = None) -> Extraction_Record:
        """Return an Extraction_Record for the input. Raises ModelUnavailableError (no model, runtime failure or unrecordable result) or RecordingMissingError (replay without a matching recording). Live calls reuse a recording when model and prompt fingerprint match; new results are recorded."""
        clean = sanitize(input)
        h = self.input_hash(prompt_id, version, clean)
        if self.provider == "none":
            raise ModelUnavailableError("no model configured (provider: none)")
        if self.provider == "replay":
            try:
                rec = self.recorder.load(prompt_id, version, h) if self.recorder else None
            except (OSError, ValueError) as exc:  # unreadable/corrupt recording counts as missing
                raise RecordingMissingError(f"unreadable recording: {prompt_id}/{version}/{h}") from exc
            if rec is None:
                raise RecordingMissingError(f"missing recording: {prompt_id}/{version}/{h}")
            return rec
        if self.runtime is None:
            raise ModelUnavailableError("bedrock runtime not configured")
        full = f"{sanitize(prompt)}\n\nINPUT:\n{canonical_json(clean)}" if prompt else canonical_json(clean)
        fp = sha256_hex(f"{getattr(self.runtime, 'fingerprint', '')}\n{full}")
        try:   # same input, prompt text, model and runtime parameters as a recorded run: replay it, no model call
            prev = self.recorder.load(prompt_id, version, h) if self.recorder else None
        except (OSError, ValueError):
            prev = None
        if prev is not None and prev.model == self.model and prev.prompt_sha256 == fp:
            self.reused += 1
            return prev
        try:
            text = self.runtime.complete(full, self.model, self.region)
        except Exception as exc:  # noqa: BLE001
            raise ModelUnavailableError(f"{type(exc).__name__}: {_scrub_text(str(exc))[:200]}") from exc
        rec = Extraction_Record(item_id=item_id, prompt_id=prompt_id, prompt_version=version,
                                model=self.model, input_hash=h, output=_parse_output(text), prompt_sha256=fp)
        if self.recorder:
            try:
                self.recorder.save(rec)
            except OSError as exc:  # an unrecorded output is not replayable; fall back like an unavailable model
                raise ModelUnavailableError(f"recording failed: {type(exc).__name__}") from exc
        return rec
