"""Activity-code extraction from parsed XER data.

P6 activity codes live across three tables (all captured in
``XerData.raw_tables`` by the parser):

    ACTVTYPE   code-type definitions   (actv_code_type_id -> "Area", "Phase" ...)
    ACTVCODE   code-value definitions  (actv_code_id -> "Zone A", short_name ...)
    TASKACTV   assignments             (task_id -> actv_code_id per code type)

This module resolves those joins into a simple, UI-friendly shape:
    - the list of code TYPES available in a file (so the user can pick one), and
    - a mapping of task_id -> {code_type_name: code_value} for a chosen type.

Used by the variance module (Module 4) to let the analyst re-break-down the
programme by area / work type / phase / etc.
"""

from __future__ import annotations

from dataclasses import dataclass

from dcma.xer_parser import XerData


@dataclass(frozen=True)
class ActivityCodeType:
    """A P6 activity-code type (dimension the schedule can be sliced by)."""

    type_id: str
    name: str
    assigned_task_count: int  # how many activities carry a value for this type


def activity_code_types(data: XerData) -> list[ActivityCodeType]:
    """Return the activity-code types defined in the file, most-used first.

    Empty if the export contains no activity codes (common for lightweight
    exports) — callers should treat that as "variance breakdown unavailable".
    """
    types = data.raw_tables.get("ACTVTYPE", [])
    if not types:
        return []

    # Count assignments per code type from TASKACTV.
    assign_counts: dict[str, set[str]] = {}
    for row in data.raw_tables.get("TASKACTV", []):
        type_id = row.get("actv_code_type_id", "").strip()
        task_id = row.get("task_id", "").strip()
        if type_id and task_id:
            assign_counts.setdefault(type_id, set()).add(task_id)

    result: list[ActivityCodeType] = []
    for row in types:
        type_id = row.get("actv_code_type_id", "").strip()
        if not type_id:
            continue
        name = (row.get("actv_code_type") or "").strip() or f"Code {type_id}"
        result.append(
            ActivityCodeType(
                type_id=type_id,
                name=name,
                assigned_task_count=len(assign_counts.get(type_id, ())),
            )
        )

    result.sort(key=lambda t: t.assigned_task_count, reverse=True)
    return result


def _code_value_lookup(data: XerData) -> dict[str, str]:
    """actv_code_id -> display value (prefer full name, fall back to short)."""
    lookup: dict[str, str] = {}
    for row in data.raw_tables.get("ACTVCODE", []):
        code_id = row.get("actv_code_id", "").strip()
        if not code_id:
            continue
        value = (row.get("actv_code_name") or "").strip()
        if not value:
            value = (row.get("short_name") or "").strip()
        lookup[code_id] = value or code_id
    return lookup


def task_code_assignments(data: XerData, type_id: str) -> dict[str, str]:
    """Map task_id -> code value for a single activity-code type.

    Activities with no value assigned for this type are simply absent from the
    mapping; callers decide how to bucket them (see variance's UNCODED group).
    """
    values = _code_value_lookup(data)
    out: dict[str, str] = {}
    for row in data.raw_tables.get("TASKACTV", []):
        if row.get("actv_code_type_id", "").strip() != type_id:
            continue
        task_id = row.get("task_id", "").strip()
        code_id = row.get("actv_code_id", "").strip()
        if not task_id or not code_id:
            continue
        out[task_id] = values.get(code_id, code_id)
    return out
