"""LLM rule extraction: prose -> schema-validated DRAFT item (Req 4.1, 4.2, 4.5, 4.7).

Pure of storage: ``extract`` returns an :class:`ExtractionResult`; the caller persists
the DRAFT. The gateway strips secrets and file paths and records the Extraction_Record.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Optional, Sequence

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from agip_shared.contracts import Extraction_Record
from agip_shared.gateway import ModelGateway
from agip_shared.hashing import canonical_hash

from .paths import FRAMEWORK_ROOT

PROMPT_ID = "extraction"
PROMPT_VERSION = "v1"
PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"
PROMPT_FILE = PROMPT_DIR / "extraction.v1.md"
CCC_PROMPT_VERSION = "v2"   # CCC input shape: objective, assessment requirements, threat mappings
_CODE_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)+$")
_CORE_FUNCTIONS = {"truthy", "falsy", "defined", "undefined", "pattern", "enumeration", "schema", "length",
                   "alphabetical", "casing", "xor"}


class Trigger(BaseModel):
    """Condition under which an item applies, tied to a risk dimension."""
    dimension: str = Field(min_length=1)
    condition: str = Field(min_length=1)


class Scored(BaseModel):
    """A 1-5 score with the criteria that justify it."""
    score: int = Field(ge=1, le=5)
    criteria: str = Field(min_length=1)


class Then(BaseModel):
    """The `then` clause of a Spectral rule; the function must be a Spectral core function."""
    function: str
    field: Optional[str] = None
    functionOptions: dict[str, Any] = Field(default_factory=dict)  # noqa: N815 - Spectral name

    @field_validator("function")
    @classmethod
    def _known(cls, v: str) -> str:
        """Reject functions that are not Spectral core functions."""
        if v not in _CORE_FUNCTIONS:
            raise ValueError(f"unknown Spectral core function: {v}")
        return v


class CandidateRule(BaseModel):
    """Model-proposed Spectral rule (not yet approved); rule_code must be lowercase kebab-case and given a JSONPath."""
    rule_code: str
    description: str = Field(min_length=1)
    severity: Literal["error", "warn", "info", "hint"]
    given: str = Field(min_length=1)
    then: Then

    @field_validator("rule_code")
    @classmethod
    def _code(cls, v: str) -> str:
        """Require lowercase kebab-case."""
        if not _CODE_RE.match(v):
            raise ValueError("rule_code must be lowercase kebab-case")
        return v

    @field_validator("given")
    @classmethod
    def _given(cls, v: str) -> str:
        """Require a JSONPath starting with $."""
        if not v.startswith("$"):
            raise ValueError("given must be a JSONPath starting with $")
        return v


class Extraction(BaseModel):
    """Validated model output for one source item: triggers, scores, remediation and either a candidate rule or the reason none can be expressed."""
    kind: Literal["control", "risk"]
    triggers: list[Trigger] = Field(min_length=1)
    likelihood: Scored
    impact: Scored
    remediation: str = Field(min_length=1)
    candidate_rule: Optional[CandidateRule] = None   # None = no expressible check (needs inexpressible_reason)
    inexpressible_reason: Optional[str] = None

    @model_validator(mode="after")
    def _rule_or_reason(self) -> "Extraction":
        """A missing rule needs an explanation."""
        if self.candidate_rule is None and not (self.inexpressible_reason or "").strip():
            raise ValueError("candidate_rule is null without inexpressible_reason")
        return self


@dataclass(frozen=True)
class ExtractionResult:
    """Outcome of extracting one item: the DRAFT catalog item and record when ok, otherwise the rejection reason."""
    ok: bool
    item: Optional[dict[str, Any]] = None       # DRAFT catalog item (not yet stored)
    record: Optional[Extraction_Record] = None
    reason: Optional[str] = None                # set when rejected
    inexpressible: bool = False                 # DRAFT kept without a rule; must be reported


def _catalog_codes() -> dict[str, str]:
    """Rule_Code already used by each catalog item (risks: rule_codes; controls: configurations[].rule_codes)."""
    out: dict[str, str] = {}
    for name in ("risks.catalog.yaml", "controls.catalog.yaml"):
        try:
            doc = yaml.safe_load((FRAMEWORK_ROOT / "catalogs" / name).read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        for it in doc.get("items") or []:
            iid = it.get("risk_id") or it.get("control_id") or it.get("id")
            codes = list(it.get("rule_codes") or []) + [c for g in it.get("configurations") or []
                                                        for c in g.get("rule_codes") or []]
            if iid and codes:
                out.setdefault(str(iid), str(codes[0]))
    return out


def rule_code_for(framework: str, native_id: str, kind: str) -> str:
    """Rule_Code for an AIGF item, never from the model: the code already in the catalog (other frameworks
    reference it), else the fixed format ``risk-aigf-ri-001`` / ``ctl-aigf-mi-006``."""
    key = item_key(framework, native_id)
    return _catalog_codes().get(key) or f"{'risk' if kind == 'risk' else 'ctl'}-{key.lower()}"


def _with_rule_code(output: Any, code: str) -> Any:
    """Copy of the output with the candidate rule's rule_code replaced; unchanged if it has no rule."""
    rule = output.get("candidate_rule") if isinstance(output, dict) else None
    if not isinstance(rule, dict):
        return output
    return {**output, "candidate_rule": {**rule, "rule_code": code}}


def validate_extraction(output: Any) -> tuple[Optional[Extraction], Optional[str]]:
    """Validate raw model output after repairing known slips (stub rule with a reason, enumeration option aliases). Returns (Extraction, None) or (None, reason)."""
    if not isinstance(output, dict):
        return None, "output is not a JSON object"
    rule = output.get("candidate_rule")
    if isinstance(rule, dict) and not rule.get("then") and str(output.get("inexpressible_reason") or "").strip():
        output = {**output, "candidate_rule": None}   # model flagged it inexpressible but left a stub rule
    elif isinstance(rule, dict) and isinstance(rule.get("then"), dict) and rule["then"].get("function") == "enumeration":
        opts = dict(rule["then"].get("functionOptions") or {})
        for alias in ("enum", "allowedValues", "allowed_values"):   # common model misnames of Spectral's `values`
            if alias in opts and "values" not in opts:
                opts["values"] = opts.pop(alias)
        output = {**output, "candidate_rule": {**rule, "then": {**rule["then"], "functionOptions": opts}}}
    try:
        return Extraction.model_validate(output), None
    except ValidationError as exc:
        return None, "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())


def item_key(framework: str, native_id: str) -> str:
    """Stable catalog ID: ``AIGF-MI-006`` for AIGF ``mi-6``; CCC IDs are kept as given."""
    m = re.match(r"^(ri|mi)-(\d+)$", native_id)
    if framework.upper() == "AIGF" and m:
        return f"AIGF-{m.group(1).upper()}-{int(m.group(2)):03d}"
    return native_id if framework.upper() == "CCC" else f"{framework.upper()}-{native_id}"


CODE_ASSIGNED = ("AIGF", "UPL")   # frameworks whose Rule_Code and metadata fields are fixed by code, not the model


def body_of_markdown(text: str) -> str:
    """Prose without YAML frontmatter."""
    text = text.lstrip("\ufeff")
    if text.startswith("---"):
        parts = text.split("\n---", 1)
        if len(parts) == 2:
            return parts[1].lstrip("-\r\n ")
    return text


def load_prompt(path: Path = PROMPT_FILE) -> str:
    """Text of the extraction prompt file."""
    return path.read_text(encoding="utf-8")


TAXONOMY = FRAMEWORK_ROOT.parent / "governance-execution-framework" / "config" / "taxonomy.yaml"


def load_fields(path: Path = TAXONOMY) -> Optional[dict[str, dict[str, Any]]]:
    """Checkable metadata fields from the taxonomy, read as data: {field: {dimension, values}}. None if unavailable."""
    try:
        attrs = yaml.safe_load(path.read_text(encoding="utf-8")).get("attributes")
    except (OSError, yaml.YAMLError, AttributeError):
        return None
    if not isinstance(attrs, dict) or not attrs:
        return None
    return {str(k): {"dimension": v.get("dimension", ""), "element_types": [str(t) for t in v.get("element_types") or []],
                     "values": sorted(map(str, (v.get("values") or {}).keys()))}
            for k, v in attrs.items() if isinstance(v, dict)}


_GIVEN_RE = re.compile(r"^\$\.nodes\[\?\(@\['node-type'\]==['\"]([^'\"]+)['\"](?:\s*&&[^\]]*)?\)\]\.metadata$")


def _rule_problem(rule: "CandidateRule", fields: dict[str, dict[str, Any]]) -> Optional[str]:
    """Why a candidate rule cannot match App_Model metadata, or None when it can."""
    f = rule.then.field
    if f not in fields:
        return f"field {f!r} is not a taxonomy attribute {sorted(fields)}"
    if rule.then.function not in ("pattern", "enumeration"):
        return f"function {rule.then.function!r} does not test a value (use pattern or enumeration)"
    opts = rule.then.functionOptions
    if rule.then.function == "enumeration" and not (isinstance(opts.get("values"), list) and opts["values"]):
        return f"enumeration needs functionOptions.values (a non-empty list), got {sorted(opts)}"
    if rule.then.function == "pattern" and not any(isinstance(opts.get(k), str) and opts[k] for k in ("match", "notMatch")):
        return f"pattern needs functionOptions.match or notMatch, got {sorted(opts)}"
    m = _GIVEN_RE.match(rule.given)
    if not m:
        return f"given {rule.given!r} is not $.nodes[?(@['node-type']=='<type>')].metadata"
    types = fields[f]["element_types"]
    if types and m.group(1) not in types:
        return f"field {f!r} applies to node types {types}, not {m.group(1)!r}"
    return None


def prompt_path(version: str) -> Path:
    """Path of the extraction prompt for a version."""
    return PROMPT_DIR / f"extraction.{version}.md"


def steering_check(dimensions: Optional[Sequence[str]] = None,
                   fields: Optional[dict[str, dict[str, Any]]] = None) -> Callable[[str], Optional[str]]:
    """Check for live steering: the same rules ``_finish`` applies, returned as guidance text (None = accept).

    Used by the Strands steering handler to make the model retry before its answer is recorded.
    """
    from agip_shared.gateway.model_gateway import _parse_output

    def check(text: str) -> Optional[str]:
        """Return a problem description when the text fails schema, dimension or field checks (triggering a retry), else None."""
        out = _parse_output(text)
        if fields and isinstance(out, dict):   # AIGF: Rule_Code is assigned by code, so never retry on its name
            out = _with_rule_code(out, rule_code_for("AIGF", "x", str(out.get("kind") or "risk")))
        parsed, reason = validate_extraction(out)
        if parsed is None:
            return f"schema errors: {reason}"
        if parsed.kind != "risk":
            return None
        if dimensions:
            bad = [x.dimension for x in parsed.triggers if x.dimension not in dimensions]
            if bad:
                return f"triggers.dimension {bad} must each be exactly one of: {'; '.join(dimensions)}"
        if fields and parsed.candidate_rule is not None:
            problem = _rule_problem(parsed.candidate_rule, fields)
            if problem:
                return (f"candidate_rule invalid ({problem}). Fix it, or set candidate_rule to null and give "
                        f"inexpressible_reason")
        return None
    check.fingerprint = canonical_hash({"dimensions": list(dimensions or []), "fields": fields or {}})  # type: ignore[attr-defined]
    return check


def _finish(gateway: ModelGateway, *, framework: str, native_id: str, title: str, inp: dict[str, Any],
            version: str, prompt: Optional[str], source_path: str, dimensions: Optional[Sequence[str]],
            source_version: str, references: Optional[dict[str, list[str]]],
            extra_body: Optional[dict[str, Any]] = None, scorer: Any = None) -> ExtractionResult:
    """Run the gateway for one item and turn the validated output into an ExtractionResult. Rejected outputs become not-ok results with a reason."""
    key = item_key(framework, native_id)
    fields = load_fields() if dimensions and framework.upper() in CODE_ASSIGNED else None
    if prompt is None:
        prompt = load_prompt(prompt_path(version))
        if dimensions:
            prompt += ("\n- For a risk, each `triggers[].dimension` MUST be exactly one of: "
                       + "; ".join(dimensions) + ".\n")
        if fields:
            prompt += ("- `candidate_rule.then.field` MUST be one of these checkable App_Model metadata fields "
                       "(field: dimension; node types; raw values). `given` MUST be "
                       "`$.nodes[?(@['node-type']=='<node type>')].metadata` with a node type listed for that field, "
                       "and `function` must test the field: `enumeration` with `functionOptions: {\"values\": [...]}` "
                       "listing the SAFE values, or `pattern` with `functionOptions: {\"notMatch\": \"<regex of the "
                       "risky value>\"}`. Spectral reports a finding when the value violates the rule, so a finding "
                       "must mean the risk is present:\n"
                       + "\n".join(f"  - {f}: {d['dimension']}; {', '.join(d['element_types'])}; "
                                   f"{d['values'] or 'free-form list'}" for f, d in fields.items())
                       + "\n- If no field above can express the check, set `candidate_rule` to null and give "
                         "`inexpressible_reason`. Do not use `truthy` on the whole metadata object.\n")
    record = gateway.complete(PROMPT_ID, version, inp, prompt=prompt, item_id=key)
    output = record.output
    if framework.upper() in CODE_ASSIGNED and isinstance(output, dict):
        output = _with_rule_code(output, rule_code_for(framework, native_id, str(output.get("kind") or "")))
    parsed, reason = validate_extraction(output)
    if parsed is not None and dimensions and parsed.kind == "risk":
        bad = [x.dimension for x in parsed.triggers if x.dimension not in dimensions]
        if bad:
            parsed, reason = None, f"triggers.dimension not in Scoring_Profile dimensions: {bad}"
        elif fields and parsed.candidate_rule is not None:
            problem = _rule_problem(parsed.candidate_rule, fields)
            if problem:
                # keep the risk (dimension, likelihood, impact) for review, but never a rule that cannot match
                parsed = parsed.model_copy(update={"candidate_rule": None, "inexpressible_reason": (
                    f"model-proposed rule rejected: {problem}; rule needs human authoring")})
    if parsed is None:
        return ExtractionResult(False, None, record, f"schema-invalid extraction for {key}: {reason}")
    scoring: Optional[dict[str, Any]] = None
    if scorer is not None and parsed.kind == "risk":
        scoring, parsed = _decider_scores(scorer, parsed, title, str(inp.get("prose") or inp.get("objective") or ""))
    kind = "control_rule" if parsed.kind == "control" else "risk_rule"
    body: dict[str, Any] = {
        "title": title,
        "source": {"framework": framework, "id": native_id, "path": source_path, "version": source_version},
        "extraction": parsed.model_dump(),
        "extraction_input_hash": record.input_hash,
        "prompt_version": record.prompt_version,
        "extraction_record": {"prompt_id": record.prompt_id, "prompt_version": record.prompt_version,
                              "model": record.model, "input_hash": record.input_hash},
        "references": references or {},
    }
    if scoring is not None:
        body["scoring"] = scoring
    body.update(extra_body or {})
    item = {"id": key, "kind": kind, "version": "1", "status": "DRAFT",
            "source_ids": [f"{framework}:{native_id}"], "body": body}
    return ExtractionResult(True, item, record, None, inexpressible=parsed.candidate_rule is None)


def _decider_scores(scorer: Any, parsed: "Extraction", title: str, prose: str) -> tuple[dict[str, Any], "Extraction"]:
    """Likelihood/impact scores from the Decider; the LLM's criteria text is kept as the explanation. When the Decider
    is unavailable the LLM scores stay and the reason is recorded (never silent)."""
    from .scoring import ScoringUnavailable
    llm = {"likelihood": parsed.likelihood.score, "impact": parsed.impact.score}
    try:
        r = scorer.score(title, prose)
    except ScoringUnavailable as exc:
        return {"source": "llm", "decider_error": str(exc), "llm": llm}, parsed
    upd = {d: Scored(score=getattr(r, d).score,
                     criteria=f"{getattr(r, d).label} (Decider, confidence {getattr(r, d).confidence:.2f}). "
                              f"{getattr(parsed, d).criteria}") for d in ("likelihood", "impact")}
    return {**r.to_dict(), "llm": llm}, parsed.model_copy(update=upd)


def extract(gateway: ModelGateway, *, framework: str, native_id: str, title: str, prose: str,
            source_path: str = "", prompt: Optional[str] = None, dimensions: Optional[Sequence[str]] = None,
            source_version: str = "unknown", references: Optional[dict[str, list[str]]] = None,
            scorer: Any = None) -> ExtractionResult:
    """Extract a DRAFT from prose (prompt v1 input). ``scorer`` (a scoring.DeciderScorer) sets risk likelihood/impact.
    Raises ModelUnavailableError/RecordingMissingError."""
    return _finish(gateway, framework=framework, native_id=native_id, title=title,
                   inp={"framework": framework, "id": native_id, "title": title, "prose": prose},
                   version=PROMPT_VERSION, prompt=prompt, source_path=source_path, dimensions=dimensions,
                   source_version=source_version, references=references, scorer=scorer)


def ccc_input(*, native_id: str, kind: str, title: str, objective: str,
              assessment_requirements: Sequence[dict[str, str]],
              threat_mappings: Sequence[dict[str, str]]) -> dict[str, Any]:
    """Structured prompt v2 input for a CCC control or threat."""
    return {"framework": "CCC", "id": native_id, "kind": kind, "title": title, "objective": objective,
            "assessment_requirements": [{"id": a["id"], "text": a["text"]} for a in assessment_requirements],
            "threat_mappings": [{"id": x["id"], "title": x.get("title", "")} for x in threat_mappings]}


def extract_ccc(gateway: ModelGateway, *, native_id: str, kind: str, title: str, objective: str,
                assessment_requirements: Sequence[dict[str, str]], threat_mappings: Sequence[dict[str, str]],
                references: Optional[dict[str, list[str]]] = None, source_path: str = "",
                prompt: Optional[str] = None, dimensions: Optional[Sequence[str]] = None,
                source_version: str = "unknown") -> ExtractionResult:
    """Extract a DRAFT from a CCC control or threat as structured input (prompt v2).

    The CCC ID is kept unchanged and ``references`` come from the source mappings, never from the model.
    """
    inp = ccc_input(native_id=native_id, kind=kind, title=title, objective=objective,
                    assessment_requirements=assessment_requirements, threat_mappings=threat_mappings)
    return _finish(gateway, framework="CCC", native_id=native_id, title=title, inp=inp,
                   version=CCC_PROMPT_VERSION, prompt=prompt, source_path=source_path, dimensions=dimensions,
                   source_version=source_version, references=references,
                   extra_body={"ccc_kind": kind,
                               "assessment_requirement_ids": [a["id"] for a in inp["assessment_requirements"]]})


def to_catalog_entry(item: dict[str, Any], *, catalog_severity: str = "medium", mandatory: bool = False) -> dict[str, Any]:
    """Convert a stored DRAFT item into a catalog entry (status unchanged; approve it separately)."""
    body = item["body"]
    x = body["extraction"]
    rule = x.get("candidate_rule")
    code = rule["rule_code"] if rule else None
    spectral = {"description": rule["description"], "message": f"{{{{path}}}}: {rule['description']}",
                "severity": rule["severity"], "given": rule["given"],
                "then": {k: v for k, v in rule["then"].items() if v not in (None, {})}} if rule else None
    codes = [code] if code else []
    src = body["source"]
    entry: dict[str, Any] = {
        "title": body["title"], "version": int(item["version"]), "status": item["status"],
        "source": {"framework": src["framework"], "id": src["id"], "path": src.get("path", "")},
        "references": [f"{s}:{i}" for s, ids in sorted((body.get("references") or {}).items()) for i in ids],
        "spectral_rules": {code: spectral} if rule else {},
        "extraction": {"input_hash": body["extraction_input_hash"], "prompt_version": body["prompt_version"]},
    }
    if body.get("scoring"):
        entry["scoring"] = body["scoring"]      # who proposed likelihood/impact (Decider or LLM), shown to the reviewer
    if x["kind"] == "control":
        entry["control_id"] = item["id"]
        entry["configurations"] = [] if not rule else [{"id": f"CFG-{code.upper()}", "mandatory": mandatory, "severity": catalog_severity,
                                    "rule_codes": codes, "remediation": x["remediation"]}]
    else:
        entry.update({"risk_id": item["id"], "dimension": x["triggers"][0]["dimension"],
                      "likelihood": x["likelihood"]["score"], "impact": x["impact"]["score"],
                      "mandatory_trigger": mandatory, "rule_codes": codes, "remediation": x["remediation"]})
    return entry