"""Shared P6 relationship-calendar and working-time arithmetic.

This module sits below both the standalone DCMA checks and the programme
analytics.  Keeping one implementation here prevents the two layers from
quietly converting the same XER lag or holiday differently.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from .config import DCMAConfig
from .xer_parser import XerData

P6_EPOCH = datetime(1899, 12, 30)


def relationship_lag_calendar_id(
    data: XerData,
    pred_calendar_id: str,
    succ_calendar_id: str,
) -> tuple[str | None, str]:
    """Calendar selected by P6's relationship-lag scheduling option."""
    rows = data.raw_tables.get("SCHEDOPTIONS", [])
    option = ((rows[0].get("sched_calendar_on_relationship_lag") or "")
              .strip() if rows else "")
    if option == "rcal_Successor":
        return succ_calendar_id, "successor calendar"
    if option == "rcal_24Hour":
        return None, "24-hour calendar"
    if option == "rcal_Project":
        project_rows = data.raw_tables.get("PROJECT", [])
        project_cal = ((project_rows[0].get("clndr_id") or "").strip()
                       if project_rows else "")
        return project_cal, "project default calendar"
    return pred_calendar_id, "predecessor calendar"


def relationship_lag_hours_per_day(
    data: XerData,
    pred_calendar_id: str,
    succ_calendar_id: str,
    config: DCMAConfig | None = None,
) -> tuple[float, str]:
    """Resolve the XER's relationship-lag calendar hours/day."""
    config = config or DCMAConfig()

    def _hpd(calendar_id: str) -> float:
        cal = data.calendars.get(calendar_id)
        return (cal.day_hr_cnt if cal is not None and cal.day_hr_cnt > 0
                else config.default_hours_per_day)

    calendar_id, label = relationship_lag_calendar_id(
        data, pred_calendar_id, succ_calendar_id)
    if calendar_id is None:
        return 24.0, label
    return _hpd(calendar_id), label


def relationship_lag_mask(
    data: XerData,
    pred_calendar_id: str,
    succ_calendar_id: str,
    masks: dict[str, tuple] | None = None,
) -> tuple[tuple | None, str]:
    """Working-time mask selected for a relationship lag."""
    calendar_id, label = relationship_lag_calendar_id(
        data, pred_calendar_id, succ_calendar_id)
    if calendar_id is None:
        return None, label
    masks = masks if masks is not None else calendar_masks(data)
    return masks.get(calendar_id), label


def _clock_minutes(value: str) -> int | None:
    try:
        hour, minute = (int(x) for x in value.split(":"))
    except (ValueError, TypeError):
        return None
    if not (0 <= hour <= 24 and 0 <= minute < 60):
        return None
    if hour == 24 and minute:
        return None
    return hour * 60 + minute


def _shift_intervals(text: str) -> tuple[tuple[int, int], ...]:
    """Extract P6 ``s|HH:MM|f|HH:MM`` shifts from one calendar block."""
    intervals: list[tuple[int, int]] = []
    for match in re.finditer(
        r"([sf])\|(\d{1,2}:\d{2})\|([sf])\|(\d{1,2}:\d{2})", text
    ):
        pair = {match.group(1): match.group(2),
                match.group(3): match.group(4)}
        if "s" not in pair or "f" not in pair:
            continue
        start = _clock_minutes(pair["s"])
        finish = _clock_minutes(pair["f"])
        if start is None or finish is None:
            continue
        if finish <= start:
            finish += 24 * 60
        intervals.append((start, finish))
    return tuple(sorted(set(intervals)))


def _section_children(text: str, section: str) -> list[str]:
    """Return immediate child blocks of a P6 calendar-data section.

    Day numbers and shift numbers both use tokens such as ``(0||1()``.
    Regex-scanning every occurrence therefore confuses a day's second shift
    with Sunday. Balanced extraction keeps only the section's direct children.
    """
    marker = section + "()("
    start = text.find(marker)
    if start < 0:
        return []
    source = text[start + len(marker):]
    children: list[str] = []
    depth = 0
    child_start: int | None = None
    for index, char in enumerate(source):
        if char == "(":
            if depth == 0:
                child_start = index
            depth += 1
        elif char == ")":
            if depth == 0:
                break                         # section's own closing paren
            depth -= 1
            if depth == 0 and child_start is not None:
                children.append(source[child_start:index + 1])
                child_start = None
    return children


def calendar_masks(data: XerData) -> dict[str, tuple]:
    """Build date/shift masks for every P6 calendar.

    Tuple positions 0..2 remain ``(weekdays, holidays, extras)`` for
    compatibility.  Positions 3..5 carry hours/day, weekly intervals and
    exception intervals for fractional working-time arithmetic.
    """
    masks: dict[str, tuple] = {}
    for row in data.raw_tables.get("CALENDAR", []):
        cid = (row.get("clndr_id") or "").strip()
        blob = row.get("clndr_data") or ""
        working: set[int] = set()
        weekly_intervals: dict[int, tuple[tuple[int, int], ...]] = {}
        for block in _section_children(blob, "DaysOfWeek"):
            mark = re.match(r"\(0\|\|([1-7])\(\)", block)
            if mark is None:
                continue
            p6_day = int(mark.group(1))
            weekday = (p6_day + 5) % 7
            shifts = _shift_intervals(block)
            if shifts:
                working.add(weekday)
                weekly_intervals[weekday] = shifts

        holidays: set = set()
        extra: set = set()
        exception_intervals: dict = {}
        for block in _section_children(blob, "Exceptions"):
            mark = re.search(r"\(d\|(\d+)\)", block)
            if mark is None:
                continue
            try:
                day = (P6_EPOCH
                       + timedelta(days=int(mark.group(1)))).date()
            except (ValueError, OverflowError):
                continue
            shifts = _shift_intervals(block)
            if shifts:
                extra.add(day)
                exception_intervals[day] = shifts
            else:
                holidays.add(day)

        try:
            hpd = float(row.get("day_hr_cnt") or 0.0)
        except ValueError:
            hpd = 0.0
        if hpd <= 0:
            cal = data.calendars.get(cid)
            hpd = cal.day_hr_cnt if cal is not None else 24.0
        if cid:
            masks[cid] = (
                frozenset(working or range(7)),
                frozenset(holidays),
                frozenset(extra),
                hpd,
                weekly_intervals,
                exception_intervals,
            )
    return masks


def is_working(day: datetime, mask: tuple) -> bool:
    wd, hol, extra = mask[:3]
    value = day.date()
    if value in extra:
        return True
    return day.weekday() in wd and value not in hol


def _mask_hpd(mask: tuple) -> float:
    if len(mask) > 3:
        try:
            value = float(mask[3])
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    return 8.0


def _day_intervals(day: datetime, mask: tuple) -> tuple[tuple[int, int], ...]:
    if not is_working(day, mask):
        return ()
    date_value = day.date()
    if len(mask) > 5:
        exception_intervals = mask[5]
        if date_value in exception_intervals:
            return exception_intervals[date_value]
        weekly_intervals = mask[4]
        if day.weekday() in weekly_intervals:
            return weekly_intervals[day.weekday()]
    hpd = _mask_hpd(mask)
    start = 8 * 60 if hpd < 24 else 0
    return ((start, start + int(round(hpd * 60))),)


def _add_work_hours(start: datetime, hours: float, mask: tuple) -> datetime:
    cur = start
    remaining = max(hours, 0.0) * 60.0
    guard = 0
    while remaining > 1e-9 and guard < 20000:
        base = cur.replace(hour=0, minute=0, second=0, microsecond=0)
        for shift_start, shift_finish in _day_intervals(base, mask):
            lo = base + timedelta(minutes=shift_start)
            hi = base + timedelta(minutes=shift_finish)
            cursor = max(cur, lo)
            if cursor >= hi:
                continue
            available = (hi - cursor).total_seconds() / 60.0
            if remaining <= available + 1e-9:
                return cursor + timedelta(minutes=remaining)
            remaining -= available
            cur = hi
        cur = base + timedelta(days=1)
        guard += 1
    return cur


def _sub_work_hours(start: datetime, hours: float, mask: tuple) -> datetime:
    cur = start
    remaining = max(hours, 0.0) * 60.0
    guard = 0
    while remaining > 1e-9 and guard < 20000:
        base = cur.replace(hour=0, minute=0, second=0, microsecond=0)
        for shift_start, shift_finish in reversed(_day_intervals(base, mask)):
            lo = base + timedelta(minutes=shift_start)
            hi = base + timedelta(minutes=shift_finish)
            cursor = min(cur, hi)
            if cursor <= lo:
                continue
            available = (cursor - lo).total_seconds() / 60.0
            if remaining <= available + 1e-9:
                return cursor - timedelta(minutes=remaining)
            remaining -= available
            cur = lo
        cur = base - timedelta(microseconds=1)
        guard += 1
    return cur


def _working_hours_between(start: datetime, end: datetime,
                           mask: tuple) -> float:
    if end <= start:
        return 0.0
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    final_day = end.replace(hour=0, minute=0, second=0, microsecond=0)
    minutes = 0.0
    guard = 0
    while day <= final_day and guard < 20000:
        for shift_start, shift_finish in _day_intervals(day, mask):
            lo = max(start, day + timedelta(minutes=shift_start))
            hi = min(end, day + timedelta(minutes=shift_finish))
            if hi > lo:
                minutes += (hi - lo).total_seconds() / 60.0
        day += timedelta(days=1)
        guard += 1
    return minutes / 60.0


def add_working_days(start: datetime, days: float,
                     mask: tuple | None) -> datetime:
    if not mask or days == 0:
        return start + timedelta(days=days)
    if days < 0:
        return sub_working_days(start, -days, mask)
    whole, frac = int(days), days - int(days)
    cur = start
    added = 0
    guard = 0
    while added < whole and guard < 20000:
        cur += timedelta(days=1)
        guard += 1
        if is_working(cur, mask):
            added += 1
    return _add_work_hours(cur, frac * _mask_hpd(mask), mask) if frac else cur


def sub_working_days(start: datetime, days: float,
                     mask: tuple | None) -> datetime:
    if not mask or days == 0:
        return start - timedelta(days=days)
    if days < 0:
        return add_working_days(start, -days, mask)
    whole, frac = int(days), days - int(days)
    cur = start
    removed = 0
    guard = 0
    while removed < whole and guard < 20000:
        cur -= timedelta(days=1)
        guard += 1
        if is_working(cur, mask):
            removed += 1
    return _sub_work_hours(cur, frac * _mask_hpd(mask), mask) if frac else cur


def working_days_between(start: datetime, end: datetime,
                         mask: tuple | None) -> float:
    """Distance in the same working-day units used by date arithmetic."""
    if end == start:
        return 0.0
    if end < start:
        return -working_days_between(end, start, mask)
    if not mask:
        return (end - start).total_seconds() / 86400.0
    cur = start
    whole = 0
    guard = 0
    while guard < 20000:
        nxt = add_working_days(cur, 1.0, mask)
        if nxt > end:
            break
        cur = nxt
        whole += 1
        guard += 1
    fraction = _working_hours_between(cur, end, mask) / _mask_hpd(mask)
    return whole + fraction
