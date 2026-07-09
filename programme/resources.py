"""Module 10 — Planned Resource Histograms.

Builds monthly planned resource-loading histograms from a programme's
resource assignments (RSRC / TASKRSRC): each assignment's target quantity is
spread uniformly across its activity's planned dates. Labour, equipment,
and material resources are reported separately.

This is PLANNED loading as scheduled — not actual expenditure; actual
manpower needs labour returns/daily reports, which an XER does not carry.

Pure engine: XerData in, structured result out. No LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from dcma.config import DCMAConfig
from dcma.xer_parser import XerData

STANDING_CAVEATS = [
    "These histograms show PLANNED resource loading as scheduled in the "
    "selected programme — not actual expenditure or actual manpower on "
    "site. Actual levels require labour returns or daily reports, which an "
    "XER export does not contain.",
    "Each assignment's quantity is spread uniformly across its activity's "
    "scheduled dates; front- or back-loaded deployment within an activity "
    "is not recorded in the file.",
    "Quantities are reported in the units used by the programme's resource "
    "definitions; mixed units within a resource type are summed as given.",
]

RESOURCE_TYPE_LABELS = {
    "RT_Labor": "Labour",
    "RT_Equip": "Equipment",
    "RT_Mat": "Material",
    "RT_Expense": "Expense",
}


@dataclass
class ResourceInfo:
    rsrc_id: str
    short_name: str
    name: str
    rsrc_type: str                  # label from RESOURCE_TYPE_LABELS
    total_qty: float = 0.0
    assignment_count: int = 0


@dataclass
class HistogramPoint:
    resource: str                   # short_name
    rsrc_type: str
    month_end: datetime
    qty: float


@dataclass
class ResourceLoadingResult:
    programme_label: str
    resources: list[ResourceInfo] = field(default_factory=list)
    histogram: list[HistogramPoint] = field(default_factory=list)
    unassigned_activities: int = 0
    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


def extract_resource_loading(
    data: XerData,
    programme_label: str,
    *,
    config: DCMAConfig | None = None,
) -> ResourceLoadingResult:
    """Monthly planned loading per resource from TASKRSRC target quantities."""
    config = config or DCMAConfig()
    result = ResourceLoadingResult(programme_label=programme_label)
    result.caveats.extend(STANDING_CAVEATS)

    rsrc_rows = data.raw_tables.get("RSRC", [])
    if not rsrc_rows:
        result.warnings.append(
            "The programme carries no resource definitions (RSRC table "
            "absent or empty) — no histogram can be built."
        )
        return result

    resources: dict[str, ResourceInfo] = {}
    for row in rsrc_rows:
        rid = (row.get("rsrc_id") or "").strip()
        rtype = (row.get("rsrc_type") or "").strip()
        resources[rid] = ResourceInfo(
            rsrc_id=rid,
            short_name=(row.get("rsrc_short_name") or rid).strip(),
            name=(row.get("rsrc_name") or "").strip(),
            rsrc_type=RESOURCE_TYPE_LABELS.get(rtype, rtype or "Other"),
        )

    tasks_by_id = {t.task_id: t for t in data.tasks if not t.is_loe_or_wbs}

    # month_end -> resource short_name -> qty
    buckets: dict[tuple[str, datetime], float] = {}
    skipped_no_dates = 0
    for row in data.raw_tables.get("TASKRSRC", []):
        tid = (row.get("task_id") or "").strip()
        rid = (row.get("rsrc_id") or "").strip()
        try:
            qty = float(row.get("target_qty") or 0.0)
        except ValueError:
            qty = 0.0
        t = tasks_by_id.get(tid)
        info = resources.get(rid)
        if t is None or info is None or qty <= 0:
            continue
        start = t.target_start or t.early_start or t.act_start
        finish = (t.target_finish or t.early_finish or t.act_finish
                  or start)
        if start is None or finish is None:
            skipped_no_dates += 1
            continue
        info.total_qty += qty
        info.assignment_count += 1

        if finish < start:
            finish = start
        # Continuous-time overlap per month so fractions sum to exactly 1.
        span = (finish - start).total_seconds()
        cur = datetime(start.year, start.month, 1)
        while cur <= finish:
            nxt = (datetime(cur.year + 1, 1, 1) if cur.month == 12
                   else datetime(cur.year, cur.month + 1, 1))
            key = (info.short_name, nxt - timedelta(days=1))
            if span <= 0:                       # instantaneous assignment
                buckets[key] = buckets.get(key, 0.0) + qty
                break
            overlap = (min(finish, nxt) - max(start, cur)).total_seconds()
            if overlap > 0:
                buckets[key] = buckets.get(key, 0.0) + qty * overlap / span
            cur = nxt

    type_by_name = {r.short_name: r.rsrc_type for r in resources.values()}
    result.histogram = [
        HistogramPoint(name, type_by_name.get(name, "Other"), month, qty)
        for (name, month), qty in sorted(buckets.items(),
                                         key=lambda kv: (kv[0][1], kv[0][0]))
    ]
    result.resources = sorted(
        [r for r in resources.values() if r.assignment_count],
        key=lambda r: -r.total_qty)

    result.unassigned_activities = sum(
        1 for t in tasks_by_id.values() if t.resource_count == 0
        and not t.is_milestone)
    if result.unassigned_activities:
        result.warnings.append(
            f"{result.unassigned_activities} non-milestone activities carry "
            "no resource assignment — the histogram under-represents those "
            "parts of the works."
        )
    if skipped_no_dates:
        result.warnings.append(
            f"{skipped_no_dates} assignment(s) skipped for lack of "
            "scheduled dates on their activity."
        )
    if not result.histogram:
        result.warnings.append(
            "No assignments with positive planned quantities and scheduled "
            "dates — no histogram can be built."
        )
    return result
