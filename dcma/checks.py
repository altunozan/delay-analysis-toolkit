"""DCMA 14-Point Schedule Assessment check engine.

Each check is a pure function of (XerData, DCMAConfig) returning a CheckResult.
The engine is UI-independent so it can feed a CLI, the Streamlit app, or the
downstream forensic-comparison / narrative modules.

Conventions:
- Durations/floats/lags from XER are in HOURS; converted to days using the
  per-activity calendar's day_hr_cnt (fallback default_hours_per_day).
- "Incomplete" = status != Complete.
- WBS-summary and LOE activities are excluded from logic/duration checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .config import DCMAConfig
from .models import (
    REL_FS,
    REL_SF,
    Task,
)
from .xer_parser import XerData


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NA = "N/A"


@dataclass
class CheckResult:
    number: int
    name: str
    status: CheckStatus
    metric_label: str          # e.g. "Activities missing logic"
    metric_value: str          # formatted value, e.g. "14 (3.3%)"
    threshold: str             # e.g. "<= 5%"
    summary: str               # one-line plain-language result
    affected_ids: list[str] = field(default_factory=list)
    detail_rows: list[dict] = field(default_factory=list)
    na_reason: str | None = None

    @property
    def affected_count(self) -> int:
        return len(self.affected_ids)


def _pct(part: int, whole: int) -> float:
    return (part / whole * 100.0) if whole else 0.0


def _eligible_activities(data: XerData) -> list[Task]:
    """Activities eligible for logic/duration/float checks.

    Excludes WBS-summary and LOE activities (not real network activities).
    """
    return [t for t in data.tasks if not t.is_loe_or_wbs]


# ---------------------------------------------------------------------------
# Check 1: Logic (missing predecessors/successors)
# ---------------------------------------------------------------------------
def check_01_logic(data: XerData, config: DCMAConfig) -> CheckResult:
    preds: set[str] = set()      # tasks that HAVE a predecessor
    succs: set[str] = set()      # tasks that HAVE a successor
    for rel in data.relationships:
        succs.add(rel.pred_task_id)   # predecessor task has a successor link
        preds.add(rel.task_id)        # successor task has a predecessor link

    activities = [t for t in _eligible_activities(data) if t.is_incomplete]
    affected = []
    detail = []
    for t in activities:
        missing_pred = t.task_id not in preds
        missing_succ = t.task_id not in succs
        if missing_pred or missing_succ:
            affected.append(t.task_code)
            tag = []
            if missing_pred:
                tag.append("no predecessor")
            if missing_succ:
                tag.append("no successor")
            detail.append({
                "Activity ID": t.task_code,
                "Activity Name": t.name,
                "Issue": "; ".join(tag),
            })

    total = len(activities)
    pct = _pct(len(affected), total)
    status = CheckStatus.PASS if pct <= config.logic_max_pct else CheckStatus.FAIL
    return CheckResult(
        number=1,
        name="Logic",
        status=status,
        metric_label="Incomplete activities missing predecessor/successor",
        metric_value=f"{len(affected)} of {total} ({pct:.1f}%)",
        threshold=f"<= {config.logic_max_pct:.0f}%",
        summary=(
            f"{len(affected)} incomplete activities ({pct:.1f}%) are missing "
            f"a predecessor and/or successor (dangling logic)."
        ),
        affected_ids=affected,
        detail_rows=detail,
    )


# ---------------------------------------------------------------------------
# Check 2: Leads (negative lag)
# ---------------------------------------------------------------------------
def check_02_leads(data: XerData, config: DCMAConfig) -> CheckResult:
    affected = []
    detail = []
    for rel in data.relationships:
        if rel.lag_hr < 0:
            succ = data.tasks_by_id.get(rel.task_id)
            pred = data.tasks_by_id.get(rel.pred_task_id)
            hpd = data.hours_per_day(succ, config) if succ else config.default_hours_per_day
            label = succ.task_code if succ else rel.task_id
            affected.append(label)
            detail.append({
                "Predecessor": pred.task_code if pred else rel.pred_task_id,
                "Successor": label,
                "Type": rel.pred_type,
                "Lag (days)": round(rel.lag_hr / hpd, 2),
            })

    count = len(affected)
    status = CheckStatus.PASS if count <= config.leads_max_count else CheckStatus.FAIL
    return CheckResult(
        number=2,
        name="Leads",
        status=status,
        metric_label="Relationships with negative lag (leads)",
        metric_value=str(count),
        threshold=f"<= {config.leads_max_count}",
        summary=f"{count} relationships use a negative lag (lead).",
        affected_ids=affected,
        detail_rows=detail,
    )


# ---------------------------------------------------------------------------
# Check 3: Lags (positive lag)
# ---------------------------------------------------------------------------
def check_03_lags(data: XerData, config: DCMAConfig) -> CheckResult:
    total_rels = len(data.relationships)
    affected = []
    detail = []
    for rel in data.relationships:
        if rel.lag_hr > 0:
            succ = data.tasks_by_id.get(rel.task_id)
            pred = data.tasks_by_id.get(rel.pred_task_id)
            hpd = data.hours_per_day(succ, config) if succ else config.default_hours_per_day
            label = succ.task_code if succ else rel.task_id
            affected.append(label)
            detail.append({
                "Predecessor": pred.task_code if pred else rel.pred_task_id,
                "Successor": label,
                "Type": rel.pred_type,
                "Lag (days)": round(rel.lag_hr / hpd, 2),
            })

    pct = _pct(len(affected), total_rels)
    status = CheckStatus.PASS if pct <= config.lags_max_pct else CheckStatus.FAIL
    return CheckResult(
        number=3,
        name="Lags",
        status=status,
        metric_label="Relationships with positive lag",
        metric_value=f"{len(affected)} of {total_rels} ({pct:.1f}%)",
        threshold=f"<= {config.lags_max_pct:.0f}%",
        summary=f"{len(affected)} relationships ({pct:.1f}%) carry a positive lag.",
        affected_ids=affected,
        detail_rows=detail,
    )


# ---------------------------------------------------------------------------
# Check 4: Relationship Types (FS percentage)
# ---------------------------------------------------------------------------
def check_04_relationship_types(data: XerData, config: DCMAConfig) -> CheckResult:
    total = len(data.relationships)
    counts = {REL_FS: 0, "PR_SS": 0, "PR_FF": 0, REL_SF: 0}
    non_fs_detail = []
    sf_ids = []
    for rel in data.relationships:
        counts[rel.pred_type] = counts.get(rel.pred_type, 0) + 1
        if rel.pred_type != REL_FS:
            succ = data.tasks_by_id.get(rel.task_id)
            pred = data.tasks_by_id.get(rel.pred_task_id)
            label = succ.task_code if succ else rel.task_id
            non_fs_detail.append({
                "Predecessor": pred.task_code if pred else rel.pred_task_id,
                "Successor": label,
                "Type": rel.pred_type,
            })
            if rel.pred_type == REL_SF:
                sf_ids.append(label)

    fs_pct = _pct(counts.get(REL_FS, 0), total)
    status = CheckStatus.PASS if fs_pct >= config.fs_min_pct else CheckStatus.FAIL
    sf_note = f" {len(sf_ids)} discouraged SF links present." if sf_ids else ""
    return CheckResult(
        number=4,
        name="Relationship Types",
        status=status,
        metric_label="Finish-to-Start relationships",
        metric_value=(
            f"{fs_pct:.1f}% FS "
            f"(FS={counts.get(REL_FS,0)}, SS={counts.get('PR_SS',0)}, "
            f"FF={counts.get('PR_FF',0)}, SF={counts.get(REL_SF,0)})"
        ),
        threshold=f">= {config.fs_min_pct:.0f}% FS",
        summary=f"{fs_pct:.1f}% of relationships are Finish-to-Start.{sf_note}",
        affected_ids=[d["Successor"] for d in non_fs_detail],
        detail_rows=non_fs_detail,
    )


# ---------------------------------------------------------------------------
# Check 5: Hard Constraints
# ---------------------------------------------------------------------------
def check_05_hard_constraints(data: XerData, config: DCMAConfig) -> CheckResult:
    hard = config.hard_constraint_codes
    activities = _eligible_activities(data)
    affected = []
    detail = []
    for t in activities:
        hits = []
        if t.cstr_type in hard:
            hits.append(t.cstr_type)
        if t.cstr_type2 in hard:
            hits.append(t.cstr_type2)
        if hits:
            affected.append(t.task_code)
            detail.append({
                "Activity ID": t.task_code,
                "Activity Name": t.name,
                "Constraint(s)": ", ".join(hits),
            })

    total = len(activities)
    pct = _pct(len(affected), total)
    status = CheckStatus.PASS if pct <= config.hard_constraint_max_pct else CheckStatus.FAIL
    return CheckResult(
        number=5,
        name="Hard Constraints",
        status=status,
        metric_label="Activities with hard constraints",
        metric_value=f"{len(affected)} of {total} ({pct:.1f}%)",
        threshold=f"<= {config.hard_constraint_max_pct:.0f}%",
        summary=(
            f"{len(affected)} activities ({pct:.1f}%) carry a hard constraint "
            f"({', '.join(sorted(hard))})."
        ),
        affected_ids=affected,
        detail_rows=detail,
    )


# ---------------------------------------------------------------------------
# Check 6: High Float (> threshold days)
# ---------------------------------------------------------------------------
def check_06_high_float(data: XerData, config: DCMAConfig) -> CheckResult:
    activities = [t for t in _eligible_activities(data) if t.is_incomplete]
    affected = []
    detail = []
    for t in activities:
        hpd = data.hours_per_day(t, config)
        tf = t.total_float_days(hpd)
        if tf is not None and tf > config.high_float_days:
            affected.append(t.task_code)
            detail.append({
                "Activity ID": t.task_code,
                "Activity Name": t.name,
                "Total Float (days)": round(tf, 1),
            })

    total = len(activities)
    pct = _pct(len(affected), total)
    status = CheckStatus.PASS if pct <= config.high_float_max_pct else CheckStatus.FAIL
    return CheckResult(
        number=6,
        name="High Float",
        status=status,
        metric_label=f"Activities with total float > {config.high_float_days:.0f}d",
        metric_value=f"{len(affected)} of {total} ({pct:.1f}%)",
        threshold=f"<= {config.high_float_max_pct:.0f}%",
        summary=(
            f"{len(affected)} activities ({pct:.1f}%) have total float exceeding "
            f"{config.high_float_days:.0f} working days."
        ),
        affected_ids=affected,
        detail_rows=detail,
    )


# ---------------------------------------------------------------------------
# Check 7: Negative Float
# ---------------------------------------------------------------------------
def check_07_negative_float(data: XerData, config: DCMAConfig) -> CheckResult:
    activities = [t for t in _eligible_activities(data) if t.is_incomplete]
    affected = []
    detail = []
    worst = 0.0
    for t in activities:
        hpd = data.hours_per_day(t, config)
        tf = t.total_float_days(hpd)
        if tf is not None and tf < 0:
            affected.append(t.task_code)
            worst = min(worst, tf)
            detail.append({
                "Activity ID": t.task_code,
                "Activity Name": t.name,
                "Total Float (days)": round(tf, 1),
            })

    count = len(affected)
    status = CheckStatus.PASS if count <= config.negative_float_max_count else CheckStatus.FAIL
    worst_note = f" Max negative float: {worst:.0f} days." if count else ""
    return CheckResult(
        number=7,
        name="Negative Float",
        status=status,
        metric_label="Activities with negative total float",
        metric_value=str(count),
        threshold=f"<= {config.negative_float_max_count}",
        summary=f"{count} activities have negative total float.{worst_note}",
        affected_ids=affected,
        detail_rows=sorted(detail, key=lambda r: r["Total Float (days)"]),
    )


# ---------------------------------------------------------------------------
# Check 8: High Duration (> threshold days)
# ---------------------------------------------------------------------------
def check_08_high_duration(data: XerData, config: DCMAConfig) -> CheckResult:
    # Incomplete, non-milestone, non-summary activities.
    activities = [
        t for t in _eligible_activities(data)
        if t.is_incomplete and not t.is_milestone
    ]
    affected = []
    detail = []
    for t in activities:
        hpd = data.hours_per_day(t, config)
        dur = t.remaining_duration_days(hpd)
        if dur is not None and dur > config.high_duration_days:
            affected.append(t.task_code)
            detail.append({
                "Activity ID": t.task_code,
                "Activity Name": t.name,
                "Remaining Duration (days)": round(dur, 1),
            })

    total = len(activities)
    pct = _pct(len(affected), total)
    status = CheckStatus.PASS if pct <= config.high_duration_max_pct else CheckStatus.FAIL
    return CheckResult(
        number=8,
        name="High Duration",
        status=status,
        metric_label=f"Activities with duration > {config.high_duration_days:.0f}d",
        metric_value=f"{len(affected)} of {total} ({pct:.1f}%)",
        threshold=f"<= {config.high_duration_max_pct:.0f}%",
        summary=(
            f"{len(affected)} activities ({pct:.1f}%) have remaining duration "
            f"exceeding {config.high_duration_days:.0f} working days."
        ),
        affected_ids=affected,
        detail_rows=detail,
    )


# ---------------------------------------------------------------------------
# Check 9: Invalid Dates
# ---------------------------------------------------------------------------
def check_09_invalid_dates(data: XerData, config: DCMAConfig) -> CheckResult:
    project = data.project
    data_date = project.data_date if project else None
    if data_date is None:
        return CheckResult(
            number=9, name="Invalid Dates", status=CheckStatus.NA,
            metric_label="Activities with invalid dates",
            metric_value="N/A", threshold=f"<= {config.invalid_dates_max_count}",
            summary="Project data date (last_recalc_date) not found in file.",
            na_reason="No data date available to validate actual/forecast dates.",
        )

    affected = []
    detail = []
    for t in _eligible_activities(data):
        issues = []
        # Actuals must not be in the future (after the data date).
        if t.act_start and t.act_start > data_date:
            issues.append("actual start after data date")
        if t.act_finish and t.act_finish > data_date:
            issues.append("actual finish after data date")
        # Forecast (early) dates of remaining work must not precede data date.
        if t.is_incomplete:
            if t.early_start and t.early_start < data_date:
                issues.append("forecast start before data date")
            if t.early_finish and t.early_finish < data_date:
                issues.append("forecast finish before data date")
        if issues:
            affected.append(t.task_code)
            detail.append({
                "Activity ID": t.task_code,
                "Activity Name": t.name,
                "Issue": "; ".join(issues),
            })

    count = len(affected)
    status = CheckStatus.PASS if count <= config.invalid_dates_max_count else CheckStatus.FAIL
    return CheckResult(
        number=9,
        name="Invalid Dates",
        status=status,
        metric_label="Activities with invalid actual/forecast dates",
        metric_value=str(count),
        threshold=f"<= {config.invalid_dates_max_count}",
        summary=(
            f"{count} activities have dates inconsistent with the data date "
            f"({data_date:%Y-%m-%d})."
        ),
        affected_ids=affected,
        detail_rows=detail,
    )


# ---------------------------------------------------------------------------
# Check 10: Resources
# ---------------------------------------------------------------------------
def check_10_resources(data: XerData, config: DCMAConfig) -> CheckResult:
    has_resource_table = bool(data.raw_tables.get("TASKRSRC"))
    if not has_resource_table:
        return CheckResult(
            number=10, name="Resources", status=CheckStatus.NA,
            metric_label="Incomplete activities lacking resources",
            metric_value="N/A", threshold=f"<= {config.resources_max_count}",
            summary="No resource assignments (TASKRSRC) present in the file.",
            na_reason="Schedule is not resource-loaded; resource check not applicable.",
        )

    activities = [
        t for t in _eligible_activities(data)
        if t.is_incomplete and not t.is_milestone
    ]
    affected = []
    detail = []
    for t in activities:
        hpd = data.hours_per_day(t, config)
        dur = t.remaining_duration_days(hpd) or 0.0
        if dur > 0 and t.resource_count == 0:
            affected.append(t.task_code)
            detail.append({
                "Activity ID": t.task_code,
                "Activity Name": t.name,
                "Remaining Duration (days)": round(dur, 1),
            })

    count = len(affected)
    status = CheckStatus.PASS if count <= config.resources_max_count else CheckStatus.FAIL
    return CheckResult(
        number=10,
        name="Resources",
        status=status,
        metric_label="Incomplete activities with duration but no resources",
        metric_value=str(count),
        threshold=f"<= {config.resources_max_count}",
        summary=f"{count} incomplete activities have duration but no resource assignment.",
        affected_ids=affected,
        detail_rows=detail,
    )


# ---------------------------------------------------------------------------
# Check 11: Missed Tasks (slipped vs baseline finish)
# ---------------------------------------------------------------------------
def check_11_missed_tasks(data: XerData, config: DCMAConfig) -> CheckResult:
    # Baseline finish proxy = target_finish. If absent across the board, N/A.
    activities = [t for t in _eligible_activities(data) if t.target_finish]
    if not activities:
        return CheckResult(
            number=11, name="Missed Tasks", status=CheckStatus.NA,
            metric_label="Activities finishing late vs baseline",
            metric_value="N/A", threshold=f"<= {config.missed_tasks_max_pct:.0f}%",
            summary="No baseline (target) finish dates available for comparison.",
            na_reason="Baseline finish dates required to evaluate missed tasks.",
        )

    affected = []
    detail = []
    for t in activities:
        # Forecast/actual finish to compare against baseline target finish.
        forecast = t.act_finish or t.early_finish
        if forecast and t.target_finish and forecast > t.target_finish:
            affected.append(t.task_code)
            detail.append({
                "Activity ID": t.task_code,
                "Activity Name": t.name,
                "Baseline Finish": t.target_finish.strftime("%Y-%m-%d"),
                "Forecast/Actual Finish": forecast.strftime("%Y-%m-%d"),
            })

    total = len(activities)
    pct = _pct(len(affected), total)
    status = CheckStatus.PASS if pct <= config.missed_tasks_max_pct else CheckStatus.FAIL
    return CheckResult(
        number=11,
        name="Missed Tasks",
        status=status,
        metric_label="Activities finishing late vs baseline",
        metric_value=f"{len(affected)} of {total} ({pct:.1f}%)",
        threshold=f"<= {config.missed_tasks_max_pct:.0f}%",
        summary=f"{len(affected)} activities ({pct:.1f}%) finished/forecast later than baseline.",
        affected_ids=affected,
        detail_rows=detail,
    )


# ---------------------------------------------------------------------------
# Check 12: Critical Path Test
# ---------------------------------------------------------------------------
def check_12_critical_path(data: XerData, config: DCMAConfig) -> CheckResult:
    tol = config.critical_float_tolerance_days
    activities = [t for t in _eligible_activities(data) if t.is_incomplete]
    critical = []
    for t in activities:
        hpd = data.hours_per_day(t, config)
        tf = t.total_float_days(hpd)
        if tf is not None and tf <= tol:
            critical.append(t.task_code)

    has_critical = len(critical) > 0
    status = CheckStatus.PASS if has_critical else CheckStatus.FAIL
    pct = _pct(len(critical), len(activities))
    return CheckResult(
        number=12,
        name="Critical Path Test",
        status=status,
        metric_label="Critical (near-zero float) activities",
        metric_value=f"{len(critical)} of {len(activities)} ({pct:.1f}%)",
        threshold=">= 1 continuous critical path",
        summary=(
            f"{len(critical)} activities sit on the critical path "
            f"(total float <= {tol:.0f}d)."
            if has_critical else
            "No critical-path activities found; schedule may lack a valid critical path."
        ),
        affected_ids=critical,
    )


# ---------------------------------------------------------------------------
# Check 13: CPLI (Critical Path Length Index)
# ---------------------------------------------------------------------------
def check_13_cpli(data: XerData, config: DCMAConfig) -> CheckResult:
    project = data.project
    data_date = project.data_date if project else None
    project_finish = project.scheduled_finish if project else None
    must_finish = project.must_finish if project else None

    if not (data_date and project_finish and must_finish):
        missing = []
        if not data_date:
            missing.append("data date")
        if not project_finish:
            missing.append("scheduled finish")
        if not must_finish:
            missing.append("must-finish/baseline finish")
        return CheckResult(
            number=13, name="CPLI", status=CheckStatus.NA,
            metric_label="Critical Path Length Index",
            metric_value="N/A", threshold=f">= {config.cpli_min:.2f}",
            summary="CPLI requires data date, scheduled finish, and a target finish.",
            na_reason=f"Missing: {', '.join(missing)}.",
        )

    # CPLI = (critical path length + total float) / critical path length
    # Approximated at project level:
    #   CPL = working days from data date to project scheduled finish
    #   project total float = working days (scheduled finish -> must finish)
    cpl_days = max((project_finish - data_date).days, 1)
    project_float = (must_finish - project_finish).days
    cpli = (cpl_days + project_float) / cpl_days

    status = CheckStatus.PASS if cpli >= config.cpli_min else CheckStatus.FAIL
    return CheckResult(
        number=13,
        name="CPLI",
        status=status,
        metric_label="Critical Path Length Index",
        metric_value=f"{cpli:.2f}",
        threshold=f">= {config.cpli_min:.2f}",
        summary=(
            f"CPLI = {cpli:.2f} (CPL {cpl_days}d, project float {project_float}d). "
            f"{'On track' if cpli >= config.cpli_min else 'Behind required pace'}."
        ),
    )


# ---------------------------------------------------------------------------
# Check 14: BEI (Baseline Execution Index)
# ---------------------------------------------------------------------------
def check_14_bei(data: XerData, config: DCMAConfig) -> CheckResult:
    project = data.project
    data_date = project.data_date if project else None
    activities = [t for t in _eligible_activities(data) if not t.is_milestone]
    baselined = [t for t in activities if t.target_finish]

    if not data_date or not baselined:
        reason = "No data date." if not data_date else "No baseline finish dates."
        return CheckResult(
            number=14, name="BEI", status=CheckStatus.NA,
            metric_label="Baseline Execution Index",
            metric_value="N/A", threshold=f">= {config.bei_min:.2f}",
            summary="BEI requires a data date and baseline finish dates.",
            na_reason=reason,
        )

    # BEI = tasks actually completed / tasks that should have completed
    #       (baseline finish on or before the data date).
    should_complete = [t for t in baselined if t.target_finish <= data_date]
    actually_complete = [t for t in should_complete if t.is_complete]
    # Also credit tasks completed early (baseline finish after data date but done).
    extra_complete = [
        t for t in baselined
        if t.target_finish > data_date and t.is_complete
    ]

    planned = len(should_complete)
    completed = len(actually_complete) + len(extra_complete)
    bei = (completed / planned) if planned else 0.0

    status = CheckStatus.PASS if bei >= config.bei_min else CheckStatus.FAIL
    if planned == 0:
        return CheckResult(
            number=14, name="BEI", status=CheckStatus.NA,
            metric_label="Baseline Execution Index",
            metric_value="N/A", threshold=f">= {config.bei_min:.2f}",
            summary="No activities were baselined to finish on or before the data date.",
            na_reason="No planned-complete activities to measure execution against.",
        )
    return CheckResult(
        number=14,
        name="BEI",
        status=status,
        metric_label="Baseline Execution Index",
        metric_value=f"{bei:.2f}",
        threshold=f">= {config.bei_min:.2f}",
        summary=(
            f"BEI = {bei:.2f} ({completed} completed vs {planned} planned-complete). "
            f"{'On pace' if bei >= config.bei_min else 'Falling behind plan'}."
        ),
    )


ALL_CHECKS = [
    check_01_logic,
    check_02_leads,
    check_03_lags,
    check_04_relationship_types,
    check_05_hard_constraints,
    check_06_high_float,
    check_07_negative_float,
    check_08_high_duration,
    check_09_invalid_dates,
    check_10_resources,
    check_11_missed_tasks,
    check_12_critical_path,
    check_13_cpli,
    check_14_bei,
]


def run_all_checks(data: XerData, config: DCMAConfig | None = None) -> list[CheckResult]:
    """Run the full DCMA 14-point assessment and return ordered results."""
    config = config or DCMAConfig()
    return [check(data, config) for check in ALL_CHECKS]
