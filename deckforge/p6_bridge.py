"""Forensic P6 bridge — turns two XER programmes into DeckForge datasheets.

Every function returns a plain DataFrame shaped for the corresponding chart
datasheet, so imported data stays analyst-editable before it becomes a slide.
Requires the delay-analysis toolkit (``dcma`` + ``programme`` packages) next
to DeckForge; import this module lazily and handle ImportError.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from dcma import parse_xer  # noqa: F401 — re-exported for callers
from dcma.xer_parser import XerData
from programme import track_milestone_shifts


def _revs(base: XerData, cur: XerData) -> list[tuple[str, datetime, XerData]]:
    b_date = base.project.data_date if base.project else None
    c_date = cur.project.data_date if cur.project else None
    if b_date is None or c_date is None:
        raise ValueError("Both programmes need a data date for comparison.")
    return [("Baseline", b_date, base), ("Current", c_date, cur)]


def _tracked_series(base: XerData, cur: XerData, top: int):
    """Milestones matched across both programmes, worst slippage first."""
    result = track_milestone_shifts(_revs(base, cur))
    tracked = [s for s in result.series
               if s.total_shift_days is not None
               and len({p.data_date for p in s.points}) > 1]
    tracked.sort(key=lambda s: abs(s.total_shift_days), reverse=True)
    return tracked[:top]


def milestone_slip_frame(base: XerData, cur: XerData,
                         top: int = 15) -> pd.DataFrame:
    """Bar datasheet: one row per milestone, slip in days (+ = later)."""
    rows = [
        {"Milestone": f"{s.key} · {s.name[:38]}",
         "Slip (days)": round(s.total_shift_days, 1)}
        for s in _tracked_series(base, cur, top)
    ]
    if not rows:
        raise ValueError("No milestone could be matched across both files.")
    return pd.DataFrame(rows)


def comparison_gantt_frame(base: XerData, cur: XerData,
                           top: int = 15) -> pd.DataFrame:
    """Gantt datasheet: per milestone, a Baseline diamond and a Current
    diamond on the SAME row (shared label), slip as the remark."""
    rows = []
    for s in _tracked_series(base, cur, top):
        if s.first_value is None or s.last_value is None:
            continue
        label = f"{s.key} · {s.name[:32]}"
        rows.append({"Activity": label, "Start": s.first_value,
                     "Finish": s.first_value, "Type": "milestone",
                     "Group": "Baseline", "Style": "solid", "Remark": ""})
        rows.append({"Activity": label, "Start": s.last_value,
                     "Finish": s.last_value, "Type": "milestone",
                     "Group": "Current", "Style": "solid",
                     "Remark": f"{s.total_shift_days:+.0f}d"
                               + (" ✓" if s.is_achieved else "")})
    if not rows:
        raise ValueError("No milestone could be matched across both files.")
    return pd.DataFrame(rows)


def _month_end(d: datetime) -> datetime:
    nxt = datetime(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return nxt - timedelta(seconds=1)


def s_curve_frame(base: XerData, cur: XerData) -> pd.DataFrame:
    """Line datasheet: monthly cumulative % of activities finished —
    planned (baseline target dates) vs actual (current actual finishes)."""
    def eligible(data: XerData):
        return [t for t in data.tasks if not t.is_loe_or_wbs]

    base_tasks, cur_tasks = eligible(base), eligible(cur)
    planned = sorted(t.target_finish or t.early_finish for t in base_tasks
                     if t.target_finish or t.early_finish)
    actual = sorted(t.act_finish for t in cur_tasks if t.act_finish)
    if not planned:
        raise ValueError("Baseline has no planned finish dates.")
    data_date = cur.project.data_date if cur.project else None

    end = max(planned[-1], actual[-1] if actual else planned[-1])
    months = []
    m = datetime(planned[0].year, planned[0].month, 1)
    while m <= end:
        months.append(m)
        m = datetime(m.year + (m.month == 12), m.month % 12 + 1, 1)

    rows = []
    for m in months:
        me = _month_end(m)
        pl = sum(1 for d in planned if d <= me) / len(base_tasks) * 100
        if data_date is not None and m > data_date:
            ac = None
        else:
            ac = sum(1 for d in actual if d <= me) / len(cur_tasks) * 100
        rows.append({"Month": m.strftime("%b %y"),
                     "Planned %": round(pl, 1),
                     "Actual %": round(ac, 1) if ac is not None else None})
    return pd.DataFrame(rows)
