"""Adapt the toolkit's XER/RLPA objects to Path Studio records.

The planned bars come from the BASELINE revision matched by activity ID
— the same convention as ``planned_vs_actual`` — never from the as-built
file's own target dates, so "planned vs current" in the studio means
exactly what it means everywhere else in the toolkit.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from dcma.calendar import relationship_lag_hours_per_day
from dcma.config import DCMAConfig
from dcma.models import TYPE_LOE, TYPE_WBS
from dcma.xer_parser import XerData
from programme.rlpa import activity_context
from programme.variance import _planned_dates

from .models import StudioActivity, StudioDataset, StudioRelationship


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def analysis_key(data: XerData, milestone_code: str) -> str:
    """Stable identity for one programme revision and elected milestone."""
    project = data.project
    raw = "|".join((
        project.short_name if project else "programme",
        (_iso(project.data_date) or "undated") if project else "undated",
        milestone_code,
        str(len(data.tasks)),
        str(len(data.relationships)),
    ))
    return "rlpa-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:18]


def _activity_code_values(data: XerData) -> dict[str, tuple[str, ...]]:
    names = {
        (row.get("actv_code_id") or "").strip():
        (row.get("actv_code_name") or row.get("short_name") or "").strip()
        for row in data.raw_tables.get("ACTVCODE", [])
    }
    task_codes = {task.task_id: task.task_code for task in data.tasks}
    out: dict[str, list[str]] = {}
    for row in data.raw_tables.get("TASKACTV", []):
        code = task_codes.get((row.get("task_id") or "").strip())
        value = names.get((row.get("actv_code_id") or "").strip())
        if code and value and value not in out.setdefault(code, []):
            out[code].append(value)
    return {code: tuple(values) for code, values in out.items()}


def _task_wbs_paths(data: XerData) -> dict[str, str]:
    """Return full root-to-leaf WBS paths keyed by user-facing task code."""
    nodes = {
        (row.get("wbs_id") or "").strip(): {
            "name": (row.get("wbs_name") or row.get("wbs_short_name")
                     or "").strip(),
            "parent": (row.get("parent_wbs_id") or "").strip(),
            "project": (row.get("proj_node_flag") or "").strip() == "Y",
        }
        for row in data.raw_tables.get("PROJWBS", [])
        if (row.get("wbs_id") or "").strip()
    }
    cache: dict[str, str] = {}

    def path_for(wbs_id: str) -> str:
        if wbs_id in cache:
            return cache[wbs_id]
        chain: list[str] = []
        seen: set[str] = set()
        current = wbs_id
        while current in nodes and current not in seen:
            seen.add(current)
            node = nodes[current]
            if not node["project"] and node["name"]:
                chain.append(str(node["name"]))
            current = str(node["parent"])
        cache[wbs_id] = " › ".join(reversed(chain))
        return cache[wbs_id]

    task_codes = {task.task_id: task.task_code for task in data.tasks}
    out: dict[str, str] = {}
    for row in data.raw_tables.get("TASK", []):
        code = task_codes.get((row.get("task_id") or "").strip())
        path = path_for((row.get("wbs_id") or "").strip())
        if code and path:
            out[code] = path
    return out


def dataset_from_xer(
    latest: XerData,
    *,
    path_codes: list[str] | tuple[str, ...],
    basis: str,
    milestone_code: str,
    baseline: XerData | None = None,
    date_basis: str = "target",
    inferred_links: list[object] | tuple[object, ...] = (),
) -> StudioDataset:
    """Build the complete schedule view while retaining one candidate path.

    ``baseline`` supplies the planned dates (matched by ``task_code``,
    honouring the page's ``date_basis`` election). Activities absent from
    the baseline carry no planned bar — scope growth stays visible as
    such. Without a baseline the planned side is left empty rather than
    silently compared against the as-built's own targets.
    """
    cfg = DCMAConfig()
    context = activity_context(latest)
    coded_values = _activity_code_values(latest)
    wbs_paths = _task_wbs_paths(latest)
    calendars = {key: value.name for key, value in latest.calendars.items()}
    base_by = ({t.task_code: t for t in baseline.tasks
                if not t.is_loe_or_wbs} if baseline is not None else {})
    # P6 WBS summaries are hierarchy records, not activities. LOE
    # activities, however, belong in the analyst's All Activities view
    # even though they cannot form part of a driving CPM path.
    tasks = [task for task in latest.tasks if task.task_type != TYPE_WBS]
    by_id = {task.task_id: task for task in tasks}

    activities: list[StudioActivity] = []
    for task in tasks:
        hpd = latest.hours_per_day(task, cfg)
        ctx = context.get(task.task_code, {})
        start = task.act_start or task.early_start or task.target_start
        finish = task.act_finish or task.early_finish or task.target_finish
        base = base_by.get(task.task_code)
        planned_start, planned_finish = (
            _planned_dates(base, date_basis) if base is not None
            else (None, None))
        duration = (task.target_drtn_hr / hpd
                    if task.target_drtn_hr is not None and hpd else None)
        activities.append(StudioActivity(
            code=task.task_code,
            name=task.name,
            start=_iso(start),
            finish=_iso(finish),
            planned_start=_iso(planned_start),
            planned_finish=_iso(planned_finish),
            duration_days=round(duration, 2) if duration is not None else None,
            total_float_days=(round(task.total_float_hr / hpd, 2)
                              if task.total_float_hr is not None and hpd
                              else None),
            free_float_days=(round(task.free_float_hr / hpd, 2)
                             if task.free_float_hr is not None and hpd
                             else None),
            status=task.status,
            task_type=task.task_type,
            calendar=calendars.get(task.clndr_id, task.clndr_id),
            wbs=wbs_paths.get(task.task_code, ctx.get("wbs", "")),
            location=ctx.get("location", ""),
            discipline=ctx.get("discipline", ""),
            system=ctx.get("system", ""),
            activity_codes=coded_values.get(task.task_code, ()),
            path_eligible=task.task_type != TYPE_LOE,
            eligibility_reason=(
                "Level of Effort activity: visible for schedule context but "
                "ineligible for the adopted driving path."
                if task.task_type == TYPE_LOE else ""),
        ))

    relationships: list[StudioRelationship] = []
    for index, rel in enumerate(latest.relationships):
        pred = by_id.get(rel.pred_task_id)
        succ = by_id.get(rel.task_id)
        if not pred or not succ:
            continue
        hpd, lag_basis = relationship_lag_hours_per_day(
            latest, pred.clndr_id, succ.clndr_id, cfg)
        relationships.append(StudioRelationship(
            relationship_id=f"xer-{index}-{pred.task_code}-{succ.task_code}",
            predecessor=pred.task_code,
            successor=succ.task_code,
            relationship_type=rel.pred_type.removeprefix("PR_") or "FS",
            lag_days=round(rel.lag_hr / hpd, 2) if hpd else 0.0,
            lag_calendar=lag_basis,
            source="recorded",
            evidence="P6 relationship table",
        ))

    existing = {(rel.predecessor, rel.successor) for rel in relationships}
    for index, link in enumerate(inferred_links):
        pred = str(getattr(link, "pred_code", ""))
        succ = str(getattr(link, "succ_code", ""))
        if not pred or not succ or (pred, succ) in existing:
            continue
        confidence = str(getattr(link, "confidence", "unqualified"))
        reasons = getattr(link, "reasons", ()) or ()
        relationships.append(StudioRelationship(
            relationship_id=f"inferred-{index}-{pred}-{succ}",
            predecessor=pred,
            successor=succ,
            relationship_type="FS",
            source="inferred",
            evidence=f"{confidence}; " + " / ".join(map(str, reasons)),
        ))

    project = latest.project
    title = (f"{project.short_name} — RLPA path to {milestone_code}"
             if project else f"RLPA path to {milestone_code}")
    source_raw = "|".join(
        f"{a.code}:{a.start}:{a.finish}:{a.planned_start}"
        for a in activities)
    return StudioDataset(
        analysis_id=analysis_key(latest, milestone_code),
        title=title,
        milestone_code=milestone_code,
        candidate_basis=basis,
        data_date=_iso(project.data_date) if project else None,
        activities=tuple(activities),
        relationships=tuple(relationships),
        candidate_path_codes=tuple(dict.fromkeys(path_codes)),
        source_fingerprint=hashlib.sha256(source_raw.encode("utf-8"))
        .hexdigest(),
    )
