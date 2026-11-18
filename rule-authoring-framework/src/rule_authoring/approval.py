"""Approval lifecycle (Req 4.3, 4.4, 21.4): DRAFT -> IN_REVIEW -> APPROVED / REJECTED -> DEPRECATED.

Transitions use ``agip_shared.contracts.KNOWLEDGE_TRANSITIONS``. Each step appends an immutable history record
(from, to, by, role, rationale, at, version[, superseded_by]). A risk cannot be APPROVED until a human has
confirmed its model-proposed likelihood and impact (``confirmation``); severity is never stored, it stays computed
by the Scoring_Profile. CLI: submit/approve/reject/deprecate/confirm <id> --by --role --rationale.

Two entry points share one transition:
* ``approve(store, item_id, by)`` for any store with ``get_catalog_item``/``upsert_catalog_item``.
* ``approve_in_catalog(path, item_id, by)`` for ``*.catalog.yaml`` files (what ``compile`` reads).

CLI: ``python -m rule_authoring.approval approve <id> --by <name> [--catalog PATH ...]``
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Protocol

import yaml

from agip_shared.contracts import KNOWLEDGE_TRANSITIONS, InvalidTransition, check_transition

from .paths import FRAMEWORK_ROOT

DEFAULT_CATALOGS = [FRAMEWORK_ROOT / "catalogs" / "controls.catalog.yaml",
                    FRAMEWORK_ROOT / "catalogs" / "risks.catalog.yaml"]
ID_KEYS = ("control_id", "risk_id", "id")


class ApprovalError(Exception):
    """Raised when a review action is refused (missing reviewer, unconfirmed risk scores, illegal transition, item not found or ambiguous)."""
    pass


class CatalogStore(Protocol):
    """Protocol for a store that can fetch and upsert catalog items by id."""
    def get_catalog_item(self, item_id: str, version: str | None = None) -> dict[str, Any] | None:
        """Return the item (optionally a specific version) or None."""
        ...
    def upsert_catalog_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Insert or replace the item and return the stored form."""
        ...


def _stamp(now: Optional[datetime]) -> str:
    """ISO-8601 timestamp for `now`, or the current UTC time if not given."""
    return (now or datetime.now(timezone.utc)).isoformat()


def _is_risk(entry: dict[str, Any]) -> bool:
    """True if the catalog entry is a risk (type 'risk' or has a risk_id) rather than a control."""
    return entry.get("type") == "risk" or "risk_id" in entry


def confirm_risk(entry: dict[str, Any], by: str, role: str, note: str = "", now: Optional[datetime] = None) -> None:
    """Record human confirmation of the model-proposed likelihood and impact (at their current values)."""
    if not (by or "").strip() or not (role or "").strip():
        raise ApprovalError("confirmation needs a reviewer and a role")
    if not _is_risk(entry):
        raise ApprovalError("only risks carry likelihood/impact to confirm")
    entry["confirmation"] = {"likelihood": entry.get("likelihood"), "impact": entry.get("impact"), "by": by.strip(),
                             "role": role.strip(), "at": _stamp(now), "note": note}


def _check_confirmed(entry: dict[str, Any], item_id: str) -> None:
    """For risks, require a human confirmation of both likelihood and impact matching the current values; raise ApprovalError otherwise. Controls are exempt."""
    if not _is_risk(entry):
        return
    c = entry.get("confirmation") or {}
    for f in ("likelihood", "impact"):
        if entry.get(f) is None or c.get(f) != entry.get(f) or not c.get("by"):
            raise ApprovalError(f"{item_id}: {f} is not confirmed by a human; confirm it before approval")


def _move(entry: dict[str, Any], item_id: str, target: str, by: str, role: str, rationale: str,
          now: Optional[datetime], superseded_by: Optional[str] = None) -> None:
    """Move the entry to `target` in place after validating the transition table and risk confirmation, appending a record to its history (history is append-only). Raises ApprovalError on a refused move."""
    current = entry.get("status")
    try:
        check_transition(KNOWLEDGE_TRANSITIONS, str(current), target)
    except InvalidTransition as exc:
        raise ApprovalError(f"{item_id}: {exc}") from exc
    if target == "APPROVED":
        _check_confirmed(entry, item_id)
    at = _stamp(now)
    record = {"from": current, "to": target, "by": by, "role": role, "rationale": rationale, "at": at,
              "version": entry.get("version", 1)}
    if superseded_by:
        record["superseded_by"] = superseded_by
        entry["superseded_by"] = superseded_by
    entry["history"] = list(entry.get("history") or []) + [record]   # append-only
    entry["status"] = target
    if target == "APPROVED":
        entry["approved_by"], entry["approved_at"] = by, at
        entry.pop("previous_approved", None)   # this version is now the one in force


def _require(by: str, role: str, rationale: str) -> tuple[str, str, str]:
    """Return stripped (by, role, rationale); raise ApprovalError if any is blank."""
    if not (by or "").strip():
        raise ApprovalError("reviewer is required")
    if not (role or "").strip() or not (rationale or "").strip():
        raise ApprovalError("role and rationale are required")
    return by.strip(), role.strip(), rationale.strip()


def transition(entry: dict[str, Any], target: str, by: str, role: str, rationale: str,
               now: Optional[datetime] = None, superseded_by: Optional[str] = None) -> None:
    """Apply one lifecycle step in place; raises ApprovalError on an invalid step or unconfirmed risk."""
    by, role, rationale = _require(by, role, rationale)
    _move(entry, entry_id(entry) or "?", target, by, role, rationale, now, superseded_by)


def history_is_append_only(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> bool:
    """True if `after` starts with exactly the entries of `before` (nothing rewritten or removed)."""
    return list(after[:len(before)]) == list(before)


def _transition(entry: dict[str, Any], item_id: str, by: str, now: Optional[datetime],
                confirm_scores: bool = False) -> None:
    """Legacy approve: DRAFT -> IN_REVIEW -> APPROVED in one call (also approves an IN_REVIEW item).

    A risk is refused unless its likelihood/impact are already confirmed, or ``confirm_scores`` is set, which
    records the approver's explicit confirmation of the current values first."""
    if not by or not by.strip():
        raise ApprovalError("approver is required")
    by = by.strip()
    if confirm_scores and _is_risk(entry):
        if entry.get("status") not in ("DRAFT", "IN_REVIEW"):
            raise ApprovalError(f"{item_id}: {entry.get('status')} -> APPROVED not allowed")
        confirm_risk(entry, by, "approver", "confirmed at approval", now)
    if entry.get("status") == "DRAFT":
        _move(entry, item_id, "IN_REVIEW", by, "approver", "legacy approve", now)
    _move(entry, item_id, "APPROVED", by, "approver", "legacy approve", now)


def approve(store: CatalogStore, item_id: str, by: str, now: Optional[datetime] = None,
            confirm_scores: bool = False) -> dict[str, Any]:
    """Legacy approve of a stored item through the CatalogStore; raises ApprovalError if the item does not exist."""
    item = store.get_catalog_item(item_id)
    if item is None:
        raise ApprovalError(f"{item_id}: not found")
    item = dict(item)
    _transition(item, item_id, by, now, confirm_scores)
    return store.upsert_catalog_item(item)


def _entries(doc: Any, name: str) -> list[Any]:
    """Item list of a catalog document (bare list, or under 'items'/'entries'); raises ApprovalError if absent."""
    entries = doc if isinstance(doc, list) else (doc or {}).get("items") or (doc or {}).get("entries")
    if not isinstance(entries, list):
        raise ApprovalError(f"{name}: catalog has no item list")
    return entries


def _find(doc: Any, p: Path, item_id: str) -> dict[str, Any]:
    """The single entry with this id in the catalog document; raises ApprovalError if missing or duplicated."""
    matches = [e for e in _entries(doc, p.name) if isinstance(e, dict) and entry_id(e) == item_id]
    if not matches:
        raise ApprovalError(f"{item_id}: not found in {p.name}")
    if len(matches) > 1:
        raise ApprovalError(f"{item_id}: defined {len(matches)} times in {p.name}")
    return matches[0]


def _edit(path: str | Path, item_id: str, fn) -> dict[str, Any]:
    """Load a YAML catalog, apply `fn` to the entry with item_id and write the file back (comment header kept); return the entry."""
    p = Path(path)
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    entry = _find(doc, p, item_id)
    fn(entry)
    from .versioning import write_catalog
    write_catalog(p, doc)
    return entry

def entry_id(entry: dict[str, Any]) -> Optional[str]:
    """Id of a catalog entry using the first matching key of ID_KEYS, or None."""
    return next((str(entry[k]) for k in ID_KEYS if k in entry), None)


def approve_in_catalog(path: str | Path, item_id: str, by: str, now: Optional[datetime] = None,
                       confirm_scores: bool = False) -> dict[str, Any]:
    """Legacy approve applied to an entry in a YAML catalog file."""
    return _edit(path, item_id, lambda e: _transition(e, item_id, by, now, confirm_scores))


def transition_in_catalog(path: str | Path, item_id: str, target: str, by: str, role: str, rationale: str,
                          now: Optional[datetime] = None, superseded_by: Optional[str] = None) -> dict[str, Any]:
    """Apply a reviewed lifecycle transition to an entry in a YAML catalog file."""
    return _edit(path, item_id, lambda e: transition(e, target, by, role, rationale, now, superseded_by))


def confirm_in_catalog(path: str | Path, item_id: str, by: str, role: str, note: str = "",
                       now: Optional[datetime] = None) -> dict[str, Any]:
    """Record a human confirmation of a risk's likelihood/impact in a YAML catalog file."""
    return _edit(path, item_id, lambda e: confirm_risk(e, by, role, note, now))


_TARGETS = {"submit": "IN_REVIEW", "approve": "APPROVED", "reject": "REJECTED", "deprecate": "DEPRECATED"}


def main(argv: Optional[list[str]] = None) -> int:
    """CLI for review actions on catalog entries. Returns the process exit code."""
    ap = argparse.ArgumentParser(prog="rule_authoring.approval")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in (*_TARGETS, "confirm"):
        a = sub.add_parser(name)
        a.add_argument("id")
        a.add_argument("--by", required=True)
        a.add_argument("--role")
        a.add_argument("--rationale")
        a.add_argument("--catalog", action="append", type=Path)
        if name == "deprecate":
            a.add_argument("--superseded-by")
    args = ap.parse_args(argv)
    legacy = args.cmd == "approve" and not args.role and not args.rationale
    for path in args.catalog or DEFAULT_CATALOGS:
        if not path.is_file():
            continue
        try:
            if args.cmd == "confirm":
                e = confirm_in_catalog(path, args.id, args.by, args.role or "", args.rationale or "")
            elif legacy:
                e = approve_in_catalog(path, args.id, args.by)
            else:
                e = transition_in_catalog(path, args.id, _TARGETS[args.cmd], args.by, args.role or "", args.rationale or "",
                                          superseded_by=getattr(args, "superseded_by", None))
        except ApprovalError as exc:
            if "not found" in str(exc):
                continue
            print(f"error: {exc}", file=sys.stderr)
            return 1
        verb = {"submit": "submitted", "approve": "approved", "reject": "rejected", "deprecate": "deprecated",
                "confirm": "confirmed"}[args.cmd]
        print(f"{verb} {args.id} in {path.name} by {args.by.strip()} (version {e.get('version', 1)})")
        return 0
    print(f"error: {args.id}: not found in any catalog", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())


# ---- shared HumanTask integration (task 24.4): the human decision comes from agip_shared.humantasks ------------
def request_review(store: Any, item_id: str, requested_by: str, task_type: str = "RULE_REVIEW",
                   version: Optional[int] = None) -> Any:
    """Create a RULE_REVIEW (approve/reject the item) or RISK_LI_CONFIRMATION (confirm likelihood/impact) task.

    ``version`` (the catalog entry's version) is part of the task, so each revision is reviewed separately."""
    from agip_shared.contracts import HumanTask
    if task_type not in ("RULE_REVIEW", "RISK_LI_CONFIRMATION"):
        raise ApprovalError(f"unsupported task type {task_type}")
    suffix = f"-v{version}" if version is not None else ""
    ctx: dict[str, Any] = {"item_id": item_id, "created_by": requested_by}
    if version is not None:
        ctx["version"] = int(version)
    return store.create(HumanTask(
        task_id=f"{task_type.lower().replace('_', '-')}-{item_id}{suffix}", framework="rule_authoring", task_type=task_type,
        subject_refs=[f"catalog:{item_id}" + (f"@v{version}" if version is not None else "")],
        role=store.roles[task_type][0], context=ctx))


def apply_review(store: Any, task_id: str, catalog_path: str | Path) -> Optional[dict[str, Any]]:
    """Apply a decided review task to the catalog. COMPLETED: approve (RULE_REVIEW) / confirm (LI); REJECTED: reject."""
    task = store.get(task_id)
    done = [o for o in store.outcomes(task_id) if o.resulting_state in ("COMPLETED", "REJECTED")]
    if not done:
        raise ApprovalError(f"{task_id}: not decided yet ({task.status})")
    o, item_id = done[-1], task.context["item_id"]
    if task.task_type == "RISK_LI_CONFIRMATION":
        if o.resulting_state != "COMPLETED":
            return None                       # not confirmed: the approval gate keeps refusing
        return confirm_in_catalog(catalog_path, item_id, o.actor, o.role, o.rationale)
    target = "APPROVED" if o.resulting_state == "COMPLETED" else "REJECTED"
    return transition_in_catalog(catalog_path, item_id, target, o.actor, o.role, o.rationale)