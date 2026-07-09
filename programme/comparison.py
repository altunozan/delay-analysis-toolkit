"""Module 6 — Revision Comparison / Change Log.

Diffs two programme revisions (a "Claim Digger" equivalent): added and
deleted activities, renamed activities, original-duration changes, logic
added/removed, lag changes, constraint changes, calendar reassignments, and
— the forensically loaded category — retrospective changes to actual dates
(an actualised date that differs between revisions).

Activities are matched by Activity ID (``task_code``); relationships by
(predecessor ID, successor ID, link type). Pure engine: two XerData in,
structured result out. No LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from dcma.config import DCMAConfig
from dcma.models import Task
from dcma.xer_parser import XerData

STANDING_CAVEATS = [
    "The comparison is between the two programme files as submitted; it "
    "records what changed, not why — changes are descriptive facts, not "
    "evidence of intent or of entitlement.",
    "Activities are matched by Activity ID. An activity that was re-coded "
    "between revisions appears as one deletion plus one addition, not as a "
    "change.",
    "Durations are compared as original (planned) durations converted at "
    "each file's own activity calendar.",
]

CONSTRAINT_LABELS = {
    "CS_MSO": "Must Start On",
    "CS_MSOA": "Start On or After",
    "CS_MSOB": "Start On or Before",
    "CS_MEO": "Must Finish On",
    "CS_MEOA": "Finish On or After",
    "CS_MEOB": "Finish On or Before",
    "CS_ALAP": "As Late As Possible",
    "CS_MANDSTART": "Mandatory Start",
    "CS_MANDFIN": "Mandatory Finish",
}

_LINK_LABELS = {"PR_FS": "FS", "PR_SS": "SS", "PR_FF": "FF", "PR_SF": "SF"}


def _cstr_text(ctype: str, cdate: datetime | None) -> str:
    if not ctype:
        return "none"
    label = CONSTRAINT_LABELS.get(ctype, ctype)
    return f"{label} {cdate:%Y-%m-%d}" if cdate else label


@dataclass
class ActivityRef:
    task_code: str
    name: str
    is_milestone: bool
    start: datetime | None          # early/actual start in its revision
    finish: datetime | None
    duration_days: float | None


@dataclass
class FieldChange:
    """One activity whose attribute changed between revisions."""

    task_code: str
    name: str
    old_value: str
    new_value: str
    delta_days: float | None = None     # for numeric/date changes


@dataclass
class LogicChange:
    pred_code: str
    succ_code: str
    link_type: str
    lag_days: float
    pred_name: str = ""
    succ_name: str = ""


@dataclass
class ComparisonResult:
    old_label: str
    new_label: str
    old_data_date: datetime | None = None
    new_data_date: datetime | None = None
    old_finish: datetime | None = None
    new_finish: datetime | None = None

    added: list[ActivityRef] = field(default_factory=list)
    deleted: list[ActivityRef] = field(default_factory=list)
    renamed: list[FieldChange] = field(default_factory=list)
    duration_changes: list[FieldChange] = field(default_factory=list)
    logic_added: list[LogicChange] = field(default_factory=list)
    logic_removed: list[LogicChange] = field(default_factory=list)
    lag_changes: list[FieldChange] = field(default_factory=list)
    constraint_changes: list[FieldChange] = field(default_factory=list)
    calendar_changes: list[FieldChange] = field(default_factory=list)
    actual_date_changes: list[FieldChange] = field(default_factory=list)

    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    @property
    def total_changes(self) -> int:
        return (len(self.added) + len(self.deleted) + len(self.renamed)
                + len(self.duration_changes) + len(self.logic_added)
                + len(self.logic_removed) + len(self.lag_changes)
                + len(self.constraint_changes) + len(self.calendar_changes)
                + len(self.actual_date_changes))

    @property
    def category_counts(self) -> dict[str, int]:
        return {
            "Activities added": len(self.added),
            "Activities deleted": len(self.deleted),
            "Activities renamed": len(self.renamed),
            "Duration changes": len(self.duration_changes),
            "Logic added": len(self.logic_added),
            "Logic removed": len(self.logic_removed),
            "Lag changes": len(self.lag_changes),
            "Constraint changes": len(self.constraint_changes),
            "Calendar reassignments": len(self.calendar_changes),
            "Actual dates changed retrospectively":
                len(self.actual_date_changes),
        }


def _ref(t: Task, dur: float | None) -> ActivityRef:
    return ActivityRef(
        task_code=t.task_code,
        name=t.name,
        is_milestone=t.is_milestone,
        start=t.act_start or t.early_start,
        finish=t.act_finish or t.early_finish,
        duration_days=dur,
    )


def compare_revisions(
    old: XerData,
    new: XerData,
    old_label: str,
    new_label: str,
    *,
    duration_tolerance_days: float = 0.5,
    config: DCMAConfig | None = None,
) -> ComparisonResult:
    """Diff two revisions. ``old`` should be the earlier programme."""
    config = config or DCMAConfig()
    result = ComparisonResult(old_label=old_label, new_label=new_label)
    result.caveats.extend(STANDING_CAVEATS)

    def usable(data: XerData) -> dict[str, Task]:
        return {t.task_code: t for t in data.tasks if not t.is_loe_or_wbs}

    old_by_code, new_by_code = usable(old), usable(new)

    if old.project:
        result.old_data_date = old.project.data_date
        result.old_finish = old.project.scheduled_finish
    if new.project:
        result.new_data_date = new.project.data_date
        result.new_finish = new.project.scheduled_finish
    if (result.old_data_date and result.new_data_date
            and result.old_data_date > result.new_data_date):
        result.warnings.append(
            f"'{old_label}' has a LATER data date than '{new_label}' — the "
            "comparison direction looks reversed; interpret added/deleted "
            "accordingly."
        )

    def dur(data: XerData, t: Task) -> float | None:
        return t.original_duration_days(data.hours_per_day(t, config))

    # --- added / deleted / per-activity field changes -------------------
    for code, t in new_by_code.items():
        if code not in old_by_code:
            result.added.append(_ref(t, dur(new, t)))
    for code, t in old_by_code.items():
        if code not in new_by_code:
            result.deleted.append(_ref(t, dur(old, t)))

    cal_name = lambda d, t: (d.calendars.get(t.clndr_id).name
                             if d.calendars.get(t.clndr_id) else t.clndr_id)

    for code in old_by_code.keys() & new_by_code.keys():
        ot, nt = old_by_code[code], new_by_code[code]

        if ot.name.strip() != nt.name.strip():
            result.renamed.append(FieldChange(
                code, nt.name, old_value=ot.name, new_value=nt.name))

        od, nd = dur(old, ot), dur(new, nt)
        if (od is not None and nd is not None
                and abs(nd - od) > duration_tolerance_days):
            result.duration_changes.append(FieldChange(
                code, nt.name,
                old_value=f"{od:.1f}d", new_value=f"{nd:.1f}d",
                delta_days=round(nd - od, 1)))

        oc = _cstr_text(ot.cstr_type, ot.cstr_date)
        nc = _cstr_text(nt.cstr_type, nt.cstr_date)
        if oc != nc:
            result.constraint_changes.append(FieldChange(
                code, nt.name, old_value=oc, new_value=nc))

        ocal, ncal = cal_name(old, ot), cal_name(new, nt)
        if ocal != ncal:
            result.calendar_changes.append(FieldChange(
                code, nt.name, old_value=ocal, new_value=ncal))

        # Retrospective changes to actuals: a date that was recorded as
        # ACTUAL in the old revision differs (or vanished) in the new one.
        for label, oa, na in (("actual start", ot.act_start, nt.act_start),
                              ("actual finish", ot.act_finish, nt.act_finish)):
            if oa is None:
                continue
            if na is None:
                result.actual_date_changes.append(FieldChange(
                    code, nt.name,
                    old_value=f"{label} {oa:%Y-%m-%d}",
                    new_value=f"{label} removed (de-actualised)"))
            elif na.date() != oa.date():
                result.actual_date_changes.append(FieldChange(
                    code, nt.name,
                    old_value=f"{label} {oa:%Y-%m-%d}",
                    new_value=f"{label} {na:%Y-%m-%d}",
                    delta_days=round((na - oa).total_seconds() / 86400, 1)))

    # --- relationship diff ------------------------------------------------
    def rel_map(data: XerData, by_code: dict[str, Task]):
        id_to_code = {t.task_id: t.task_code
                      for t in data.tasks if not t.is_loe_or_wbs}
        rels = {}
        for r in data.relationships:
            p, s = id_to_code.get(r.pred_task_id), id_to_code.get(r.task_id)
            if p is None or s is None:
                continue
            pred = by_code[p]
            hpd = data.hours_per_day(pred, config)
            lag = round(r.lag_hr / hpd, 1) if r.lag_hr else 0.0
            rels[(p, s, r.pred_type)] = lag
        return rels

    old_rels = rel_map(old, old_by_code)
    new_rels = rel_map(new, new_by_code)

    def name_of(by_code: dict[str, Task], code: str) -> str:
        t = by_code.get(code)
        return t.name if t else ""

    for key in new_rels.keys() - old_rels.keys():
        p, s, lt = key
        # Ignore links that only exist because an endpoint is new/deleted —
        # those are already reported under added/deleted activities.
        if p in old_by_code and s in old_by_code:
            result.logic_added.append(LogicChange(
                p, s, _LINK_LABELS.get(lt, lt), new_rels[key],
                name_of(new_by_code, p), name_of(new_by_code, s)))
    for key in old_rels.keys() - new_rels.keys():
        p, s, lt = key
        if p in new_by_code and s in new_by_code:
            result.logic_removed.append(LogicChange(
                p, s, _LINK_LABELS.get(lt, lt), old_rels[key],
                name_of(old_by_code, p), name_of(old_by_code, s)))
    for key in old_rels.keys() & new_rels.keys():
        if abs(new_rels[key] - old_rels[key]) > 0.1:
            p, s, lt = key
            result.lag_changes.append(FieldChange(
                f"{p} -{_LINK_LABELS.get(lt, lt)}-> {s}",
                name_of(new_by_code, s),
                old_value=f"{old_rels[key]:+.1f}d",
                new_value=f"{new_rels[key]:+.1f}d",
                delta_days=round(new_rels[key] - old_rels[key], 1)))

    # --- sort largest-first where a magnitude exists ---------------------
    result.duration_changes.sort(
        key=lambda c: -abs(c.delta_days or 0))
    result.actual_date_changes.sort(
        key=lambda c: -abs(c.delta_days or 0))
    result.lag_changes.sort(key=lambda c: -abs(c.delta_days or 0))

    # --- diagnostics ------------------------------------------------------
    if result.actual_date_changes:
        worst = result.actual_date_changes[:5]
        result.warnings.append(
            f"{len(result.actual_date_changes)} actual date(s) recorded in "
            f"'{old_label}' were changed or removed in '{new_label}' (e.g. "
            + "; ".join(f"{c.task_code}: {c.old_value} -> {c.new_value}"
                        for c in worst)
            + "). Retrospective changes to actualised dates undermine the "
            "contemporaneity of the records and should be raised with the "
            "programmer."
        )
    matched = len(old_by_code.keys() & new_by_code.keys())
    if matched and (len(result.added) + len(result.deleted)) > 0.3 * matched:
        result.warnings.append(
            "The volume of added/deleted activities exceeds 30% of the "
            "matched population — the newer file may be a re-baselined or "
            "restructured programme rather than a routine progress update."
        )

    return result
