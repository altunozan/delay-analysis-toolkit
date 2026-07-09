"""Module 8 — Progress S-curve (planned vs recorded).

Builds the planned cumulative progress profile from the baseline and the
recorded profile from an update's actualised dates and physical percent
complete, plus one overall as-at point per revision. Slippage shows as the
horizontal offset between the curves at the data date.

Weighting options: activity duration (default), equal count, or planned
resource quantity (sum of TASKRSRC target quantities per activity).

Pure engine: XerData in, structured result out. No LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from dcma.config import DCMAConfig
from dcma.xer_parser import XerData

STANDING_CAVEATS = [
    "The recorded curve is built from the programme's own actual dates and "
    "physical percent complete as recorded by the programmer — 'as-recorded' "
    "progress, not independently verified progress.",
    "Planned and recorded curves are each measured over their own file's "
    "activity population; where scope changed between revisions the two "
    "curves compare like-for-like only approximately.",
    "Progress is spread uniformly across each activity's duration (and, for "
    "in-progress activities, from actual start to the data date) — actual "
    "earning profiles within activities are not recorded in an XER.",
]

WEIGHT_OPTIONS = {
    "duration": "Activity duration (activity-days)",
    "count": "Equal weight per activity",
    "resource_qty": "Planned resource quantity",
}


@dataclass
class CurvePoint:
    date: datetime
    cum_pct: float


@dataclass
class RevisionPoint:
    label: str
    data_date: datetime | None
    recorded_pct: float | None
    planned_pct: float | None       # planned curve value at that data date


@dataclass
class ProgressResult:
    weight_scheme: str
    planned_curve: list[CurvePoint] = field(default_factory=list)
    recorded_curve: list[CurvePoint] = field(default_factory=list)
    recorded_label: str | None = None
    revision_points: list[RevisionPoint] = field(default_factory=list)
    planned_pct_at_dd: float | None = None
    recorded_pct_at_dd: float | None = None
    time_offset_days: float | None = None    # + = behind plan (in time)
    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


def _task_weights(data: XerData, scheme: str,
                  config: DCMAConfig) -> dict[str, float]:
    """Weight per task_id under the chosen scheme (LOE/WBS excluded)."""
    tasks = [t for t in data.tasks if not t.is_loe_or_wbs]
    if scheme == "resource_qty":
        qty: dict[str, float] = {}
        for row in data.raw_tables.get("TASKRSRC", []):
            tid = (row.get("task_id") or "").strip()
            try:
                q = float(row.get("target_qty") or 0)
            except ValueError:
                q = 0.0
            if tid and q > 0:
                qty[tid] = qty.get(tid, 0.0) + q
        return {t.task_id: qty.get(t.task_id, 0.0) for t in tasks}
    if scheme == "count":
        return {t.task_id: 1.0 for t in tasks}
    # duration (default): planned duration in days; milestones get 0.
    out = {}
    for t in tasks:
        hpd = data.hours_per_day(t, config)
        d = t.original_duration_days(hpd)
        out[t.task_id] = max(d or 0.0, 0.0)
    return out


def _phys_pct(data: XerData) -> dict[str, float]:
    out = {}
    for row in data.raw_tables.get("TASK", []):
        tid = (row.get("task_id") or "").strip()
        try:
            out[tid] = float(row.get("phys_complete_pct") or 0.0)
        except ValueError:
            out[tid] = 0.0
    return out


def _spread(buckets: dict[datetime, float], start: datetime,
            finish: datetime, weight: float) -> None:
    """Distribute weight uniformly across [start, finish] by month bucket."""
    if weight <= 0:
        return
    if finish < start:
        finish = start
    # Continuous-time overlap per month so bucket fractions sum to exactly 1.
    span = (finish - start).total_seconds()
    if span <= 0:                                   # instantaneous (milestone)
        nxt = (datetime(start.year + 1, 1, 1) if start.month == 12
               else datetime(start.year, start.month + 1, 1))
        key = nxt - timedelta(days=1)
        buckets[key] = buckets.get(key, 0.0) + weight
        return
    cur = datetime(start.year, start.month, 1)
    while cur <= finish:
        nxt = (datetime(cur.year + 1, 1, 1) if cur.month == 12
               else datetime(cur.year, cur.month + 1, 1))
        overlap = (min(finish, nxt) - max(start, cur)).total_seconds()
        if overlap > 0:
            key = nxt - timedelta(days=1)          # bucket = month end
            buckets[key] = buckets.get(key, 0.0) + weight * overlap / span
        cur = nxt


def _to_curve(buckets: dict[datetime, float],
              total: float) -> list[CurvePoint]:
    pts, cum = [], 0.0
    for date in sorted(buckets):
        cum += buckets[date]
        pts.append(CurvePoint(date, min(100.0 * cum / total, 100.0)))
    return pts


def _value_at(curve: list[CurvePoint], when: datetime) -> float | None:
    """Linear interpolation of a curve at a date."""
    if not curve:
        return None
    if when <= curve[0].date:
        return 0.0 if when < curve[0].date else curve[0].cum_pct
    for a, b in zip(curve, curve[1:]):
        if a.date <= when <= b.date:
            span = (b.date - a.date).days or 1
            f = (when - a.date).days / span
            return a.cum_pct + f * (b.cum_pct - a.cum_pct)
    return curve[-1].cum_pct


def _date_at(curve: list[CurvePoint], pct: float) -> datetime | None:
    """Inverse: earliest date the curve reaches pct."""
    prev = None
    for p in curve:
        if p.cum_pct >= pct:
            if prev is None or p.cum_pct == prev.cum_pct:
                return p.date
            span = (p.date - prev.date).days
            f = (pct - prev.cum_pct) / (p.cum_pct - prev.cum_pct)
            return prev.date + timedelta(days=f * span)
        prev = p
    return None


def compute_progress(
    baseline: XerData,
    baseline_label: str,
    updates: list[tuple[str, XerData]],
    *,
    weight_scheme: str = "duration",
    config: DCMAConfig | None = None,
) -> ProgressResult:
    """Planned curve from the baseline; recorded from the latest update."""
    config = config or DCMAConfig()
    result = ProgressResult(weight_scheme=weight_scheme)
    result.caveats.extend(STANDING_CAVEATS)

    # --- planned curve from baseline -------------------------------------
    weights = _task_weights(baseline, weight_scheme, config)
    total = sum(weights.values())
    if total <= 0:
        result.warnings.append(
            f"No usable weights under scheme '{weight_scheme}' in the "
            "baseline — cannot build a planned curve."
        )
        return result
    zero_w = sum(1 for w in weights.values() if w <= 0)
    if weight_scheme == "resource_qty" and zero_w:
        result.warnings.append(
            f"{zero_w} activities carry no planned resource quantity and "
            "contribute nothing to the resource-weighted curve."
        )

    buckets: dict[datetime, float] = {}
    for t in baseline.tasks:
        if t.is_loe_or_wbs:
            continue
        s = t.target_start or t.early_start or t.act_start
        f = t.target_finish or t.early_finish or t.act_finish or s
        if s and f:
            _spread(buckets, s, f, weights.get(t.task_id, 0.0))
    result.planned_curve = _to_curve(buckets, total)

    # --- recorded curve + per-revision points -----------------------------
    for label, data in updates:
        dd = data.project.data_date if data.project else None
        w = _task_weights(data, weight_scheme, config)
        tot = sum(w.values())
        pct = _phys_pct(data)
        if tot <= 0:
            result.revision_points.append(RevisionPoint(label, dd, None, None))
            continue
        earned = 0.0
        for t in data.tasks:
            if t.is_loe_or_wbs:
                continue
            if t.is_complete:
                earned += w.get(t.task_id, 0.0)
            elif t.act_start is not None:
                earned += w.get(t.task_id, 0.0) * pct.get(t.task_id, 0.0) / 100.0
        rec_pct = 100.0 * earned / tot
        planned_here = (_value_at(result.planned_curve, dd)
                        if dd else None)
        result.revision_points.append(
            RevisionPoint(label, dd, round(rec_pct, 1),
                          round(planned_here, 1)
                          if planned_here is not None else None))

    if updates:
        label, data = updates[-1]
        result.recorded_label = label
        dd = data.project.data_date if data.project else None
        w = _task_weights(data, weight_scheme, config)
        tot = sum(w.values())
        pct = _phys_pct(data)
        rbuckets: dict[datetime, float] = {}
        for t in data.tasks:
            if t.is_loe_or_wbs or t.act_start is None:
                continue
            if t.act_finish is not None:
                _spread(rbuckets, t.act_start, t.act_finish,
                        w.get(t.task_id, 0.0))
            elif dd is not None:
                _spread(rbuckets, t.act_start, dd,
                        w.get(t.task_id, 0.0) * pct.get(t.task_id, 0.0) / 100.0)
        if rbuckets and tot > 0:
            curve = _to_curve(rbuckets, tot)
            if dd is not None:
                curve = [p for p in curve if p.date <= dd] or curve
            result.recorded_curve = curve

        last = result.revision_points[-1]
        result.recorded_pct_at_dd = last.recorded_pct
        result.planned_pct_at_dd = last.planned_pct
        if (last.recorded_pct is not None and dd is not None
                and result.planned_curve):
            planned_reach = _date_at(result.planned_curve, last.recorded_pct)
            if planned_reach is not None:
                result.time_offset_days = float((dd - planned_reach).days)

    # --- diagnostics -------------------------------------------------------
    if (result.planned_pct_at_dd is not None
            and result.recorded_pct_at_dd is not None):
        gap = result.planned_pct_at_dd - result.recorded_pct_at_dd
        if gap > 0.5:
            result.warnings.append(
                f"As at the latest data date the programme records "
                f"{result.recorded_pct_at_dd:.1f}% against a planned "
                f"{result.planned_pct_at_dd:.1f}% — {gap:.1f} percentage "
                "points behind the baseline profile"
                + (f", equivalent to roughly {result.time_offset_days:.0f} "
                   "days in time." if result.time_offset_days else ".")
            )
        else:
            result.warnings.append(
                "Favourable: recorded progress "
                f"({result.recorded_pct_at_dd:.1f}%) is at or ahead of the "
                f"planned profile ({result.planned_pct_at_dd:.1f}%) as at "
                "the latest data date."
            )
    return result
