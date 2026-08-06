"""Preliminary As-Planned vs As-Recorded.

A *screening-level* view of where slippage clusters. The analyst picks an
activity-code dimension (area, work type, phase, ...); the engine re-breaks the
programme down by that code and, for each group, brackets the work with a
planned band (from the baseline) and an as-recorded band (from the current
programme), then reports the start/finish deltas.

Deliberately labelled "as-recorded", not "as-built": the recorded dates come
from a P6 update, not an independently verified factual record. And it is
indicative only — group min-start / max-finish is a coarse bracket, not a
cause-linked, activity-level forensic analysis. Those limitations are emitted
as standing caveats so they always reach the report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from dcma.models import Task
from dcma.xer_parser import XerData

from .activity_codes import task_code_assignments

UNCODED = "(uncoded)"

# Standing caveats — always emitted, so the screening nature can't be lost.
STANDING_CAVEATS = [
    "Preliminary and indicative only: groups are bracketed by earliest start / "
    "latest finish, which is a screening view, not a cause-linked, "
    "activity-level as-planned-vs-as-built analysis.",
    "'As-recorded' dates are taken from the updated P6 programme and have not "
    "been independently verified against factual records.",
]


@dataclass
class GroupBand:
    """Start/finish bracket for a group of activities."""

    start: datetime | None
    finish: datetime | None
    activity_count: int = 0


@dataclass
class VarianceGroup:
    code_value: str
    planned: GroupBand
    recorded: GroupBand

    @property
    def start_delta_days(self) -> float | None:
        return _delta_days(self.planned.start, self.recorded.start)

    @property
    def finish_delta_days(self) -> float | None:
        return _delta_days(self.planned.finish, self.recorded.finish)

    @property
    def in_both(self) -> bool:
        return self.planned.activity_count > 0 and self.recorded.activity_count > 0


@dataclass
class VarianceResult:
    code_type_name: str
    groups: list[VarianceGroup] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    @property
    def worst_finish_slips(self) -> list[VarianceGroup]:
        """Groups ordered by finish slippage (largest positive first)."""
        scored = [g for g in self.groups if g.finish_delta_days is not None]
        return sorted(scored, key=lambda g: g.finish_delta_days, reverse=True)


def _delta_days(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return (b - a).total_seconds() / 86400.0


DIMENSION_SEPARATOR = " › "


def combine_mappings(
    mappings: list[dict[str, str]], sep: str = DIMENSION_SEPARATOR
) -> dict[str, str]:
    """Compose several task_id -> label mappings into one composite dimension.

    A task's composite label joins its label from each dimension in order,
    e.g. "Zone A › Structure › Level 03". Tasks missing from one dimension get
    UNCODED for that slot, so a partially-coded task still lands in a bucket
    rather than dropping out.
    """
    if len(mappings) == 1:
        return dict(mappings[0])
    all_ids: set[str] = set()
    for m in mappings:
        all_ids.update(m)
    return {
        tid: sep.join(m.get(tid, UNCODED) for m in mappings)
        for tid in all_ids
    }


def _planned_dates(t: Task, basis: str = "target",
                   ) -> tuple[datetime | None, datetime | None]:
    """Baseline planned start/finish under the elected date basis.

    ``target`` — the plan dates as exported (falling back to early);
    ``late``   — the baseline's late dates LS/LF (the position with all
                 float consumed — the contractual backstop);
    ``early``  — the baseline's early dates ES/EF.
    Fallback order keeps a usable date when a family is absent.
    """
    if basis == "late":
        return (t.late_start or t.target_start or t.early_start,
                t.late_finish or t.target_finish or t.early_finish)
    if basis == "early":
        return (t.early_start or t.target_start,
                t.early_finish or t.target_finish)
    return (t.target_start or t.early_start,
            t.target_finish or t.early_finish)


def _recorded_dates(t: Task) -> tuple[datetime | None, datetime | None]:
    """As-recorded start/finish (actuals where present, else forecast)."""
    start = t.act_start or t.early_start
    finish = t.act_finish or t.early_finish
    return start, finish


def _band_for_group(
    tasks: list[Task], date_fn
) -> GroupBand:
    starts: list[datetime] = []
    finishes: list[datetime] = []
    count = 0
    for t in tasks:
        if t.is_loe_or_wbs:
            continue
        count += 1
        s, f = date_fn(t)
        if s:
            starts.append(s)
        if f:
            finishes.append(f)
    return GroupBand(
        start=min(starts) if starts else None,
        finish=max(finishes) if finishes else None,
        activity_count=count,
    )


def compute_variance(
    baseline: XerData,
    recorded: XerData,
    code_type_id: str,
    code_type_name: str,
) -> VarianceResult:
    """Planned vs as-recorded bands, grouped by a P6 activity-code type."""
    return compute_variance_by_mapping(
        baseline,
        recorded,
        task_code_assignments(baseline, code_type_id),
        task_code_assignments(recorded, code_type_id),
        code_type_name,
    )


def compute_variance_by_mapping(
    baseline: XerData,
    recorded: XerData,
    base_codes: dict[str, str],
    rec_codes: dict[str, str],
    dimension_name: str,
) -> VarianceResult:
    """Compare planned (baseline) vs as-recorded (current) bands per group.

    ``base_codes`` / ``rec_codes`` map task_id -> group label in each
    programme (from activity codes, WBS level, or any other dimension). Group
    labels are assumed stable between the two exports. Groups present in only
    one programme are still reported, with the missing side blank.
    """
    result = VarianceResult(code_type_name=dimension_name)
    result.caveats.extend(STANDING_CAVEATS)

    # Bucket each programme's tasks by code value.
    base_groups = _bucket(baseline, base_codes)
    rec_groups = _bucket(recorded, rec_codes)

    all_values = sorted(set(base_groups) | set(rec_groups))
    if all_values == [UNCODED]:
        result.warnings.append(
            "No activities carry a value for the selected code type; only the "
            "uncoded bucket exists — pick a different code type."
        )

    for value in all_values:
        planned = _band_for_group(base_groups.get(value, []), _planned_dates)
        recorded_band = _band_for_group(rec_groups.get(value, []), _recorded_dates)
        group = VarianceGroup(
            code_value=value, planned=planned, recorded=recorded_band
        )
        if not group.in_both:
            side = "baseline" if planned.activity_count == 0 else "current"
            result.warnings.append(
                f"Group '{value}' has no activities in the {side} programme; "
                "its delta cannot be computed."
            )
        result.groups.append(group)

    return result


def _bucket(data: XerData, codes: dict[str, str]) -> dict[str, list[Task]]:
    groups: dict[str, list[Task]] = {}
    for t in data.tasks:
        if t.is_loe_or_wbs:
            continue
        value = codes.get(t.task_id, UNCODED)
        groups.setdefault(value, []).append(t)
    return groups


def planned_vs_actual(
    baseline: "XerData",
    latest: "XerData",
    codes: set[str] | None = None,
    date_basis: str = "target",
) -> list[dict]:
    """Per-activity planned (baseline) vs actual (latest) date comparison.

    Feeds the As-Planned vs As-Built stepped method: ``codes`` limits the
    comparison to the as-built section under review (e.g. the as-built
    critical path); None compares every matched activity. ``date_basis``
    elects which baseline dates are "planned": target (default),
    late (LS/LF) or early (ES/EF). Variances are in calendar days,
    positive = later than planned. The actual side takes recorded
    actuals where present, else the latest revision's forecast — so
    the forecast tail beyond the data date still carries a bar.
    """
    base_by = {t.task_code: t for t in baseline.tasks
               if not t.is_loe_or_wbs}
    rows: list[dict] = []
    for t in latest.tasks:
        if t.is_loe_or_wbs:
            continue
        if codes is not None and t.task_code not in codes:
            continue
        b = base_by.get(t.task_code)
        ps, pf = (_planned_dates(b, date_basis)
                  if b is not None else (None, None))
        rows.append({
            "task_code": t.task_code,
            "name": t.name,
            "planned_start": ps,
            "planned_finish": pf,
            "actual_start": t.act_start or t.early_start,
            "actual_finish": t.act_finish or t.early_finish,
            "actual_is_forecast": t.act_finish is None,
            "start_var_days": _delta_days(ps, t.act_start or t.early_start),
            "finish_var_days": _delta_days(
                pf, t.act_finish or t.early_finish),
            "in_baseline": b is not None,
        })
    rows.sort(key=lambda r: (r["actual_start"] or datetime.max,
                             r["task_code"]))
    return rows


def keydate_windows(rows: list[dict],
                    key_codes: list[str],
                    project_start=None) -> list[dict]:
    """Analysis windows bounded by the analyst's KEY DATES.

    A key date is an as-built critical-path completion point. Its
    measurement is DIRECT: slippage = its recorded (or forecast) finish
    minus its planned finish under the elected date basis (late LS/LF
    by default, early on election) — calendar days, positive = late.

    Windows run PROJECT START → key date 1 → key date 2 → …: window i
    spans from the previous key date's actual finish (or the project
    start for the first window) to key date i's actual finish. The
    delay ACCRUED in a window is the change in slippage across it
    (slippage at its closing key date minus slippage at the previous
    one); the CUMULATIVE figure at each key date is that key date's own
    slippage, measured directly, not a running sum.

    ``resequenced`` flags a key date whose planned finish precedes the
    previous key date's planned finish — the works reached them in a
    different order than planned, so the accrued-in-window figure
    carries a sequencing artefact and is disclosed as such (the direct
    slippage at the key date remains a clean measurement).
    """
    by_code = {r["task_code"]: r for r in rows}
    keys = [by_code[c] for c in key_codes if c in by_code]
    keys = [k for k in keys if k["actual_finish"] and k["planned_finish"]]
    keys.sort(key=lambda r: r["actual_finish"])
    if not keys:
        return []
    if project_start is None:
        starts = [r["actual_start"] for r in rows if r.get("actual_start")]
        project_start = min(starts) if starts else None
    out: list[dict] = []
    prev = None            # previous key row
    prev_slip = 0.0        # slippage carried into the window
    for i, k in enumerate(keys, start=1):
        slip = _delta_days(k["planned_finish"], k["actual_finish"])
        accrued = (round(slip - prev_slip, 1)
                   if slip is not None else None)
        resequenced = (prev is not None
                       and k["planned_finish"] < prev["planned_finish"])
        out.append({
            "from_code": (prev["task_code"] if prev is not None
                          else "PROJECT START"),
            "from_name": (prev["name"] if prev is not None
                          else "Start of the works"),
            "to_code": k["task_code"], "to_name": k["name"],
            "window_start": (prev["actual_finish"] if prev is not None
                             else project_start),
            "window_end": k["actual_finish"],
            "planned_finish": k["planned_finish"],
            "actual_finish": k["actual_finish"],
            "window_delay_days": accrued,
            "cumulative_delay_days": (round(slip, 1)
                                      if slip is not None else None),
            "resequenced": resequenced,
        })
        prev, prev_slip = k, (slip if slip is not None else prev_slip)
    return out
