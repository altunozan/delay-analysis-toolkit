"""Module 3 — Milestone Shift Tracker.

Tracks how the forecast (or actual) date of key milestones drifts across a set
of programme revisions. The forensic view is: x-axis = data date of each
revision, y-axis = the milestone's forecast/actual date in that revision. A
milestone whose line climbs is slipping.

The hard part is *matching* the same milestone across revisions, because
milestones get renamed, re-IDed, split or deleted between updates. Matching is
therefore two-stage and never silent:

    1. exact match on Activity ID (task_code) — high confidence, auto-linked;
    2. fuzzy fallback on milestone name for the leftovers — surfaced to the
       analyst as ``needs_confirmation`` proposals, never auto-merged.

Pure engine: dates in, structured series out. An optional narrative layer can
describe the plotted deltas, but must not invent shifts not in the series.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from datetime import datetime

from dcma.models import Task
from dcma.xer_parser import XerData

# A fuzzy name match at or above this ratio is *proposed* (not auto-applied).
NAME_MATCH_THRESHOLD = 0.82


@dataclass
class ShiftPoint:
    """A milestone's value in one revision."""

    data_date: datetime
    revision_label: str
    value_date: datetime | None      # forecast, or actual once achieved
    is_actual: bool                  # True once the milestone is complete
    task_code: str
    task_name: str


@dataclass
class MilestoneSeries:
    """One milestone tracked across all revisions in which it appears."""

    key: str                         # canonical Activity ID (or synthetic key)
    name: str                        # representative name
    points: list[ShiftPoint] = field(default_factory=list)

    @property
    def dated_points(self) -> list[ShiftPoint]:
        return [p for p in self.points if p.value_date is not None]

    @property
    def first_value(self) -> datetime | None:
        pts = self.dated_points
        return pts[0].value_date if pts else None

    @property
    def last_value(self) -> datetime | None:
        pts = self.dated_points
        return pts[-1].value_date if pts else None

    @property
    def total_shift_days(self) -> float | None:
        """Signed drift from first to last revision (positive = later = slip)."""
        first, last = self.first_value, self.last_value
        if first is None or last is None:
            return None
        return (last - first).total_seconds() / 86400.0

    @property
    def is_achieved(self) -> bool:
        return any(p.is_actual for p in self.points)


@dataclass
class MilestoneMatch:
    """A proposed fuzzy link between milestones for analyst confirmation."""

    revision_label: str
    task_code: str
    task_name: str
    matched_to_key: str
    matched_to_name: str
    similarity: float


@dataclass
class MilestoneShiftResult:
    series: list[MilestoneSeries] = field(default_factory=list)
    needs_confirmation: list[MilestoneMatch] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def series_by_key(self, keys: list[str]) -> list[MilestoneSeries]:
        wanted = set(keys)
        return [s for s in self.series if s.key in wanted]


def _milestone_value_date(t: Task) -> tuple[datetime | None, bool]:
    """Return (value_date, is_actual) for a milestone task.

    Finish milestones are keyed on their finish; start milestones on their
    start. Once achieved, the actual date supersedes the forecast.
    """
    if t.task_type == "TT_FinMile":
        if t.act_finish:
            return t.act_finish, True
        return t.early_finish, False
    # Start milestone (TT_Mile).
    if t.act_start:
        return t.act_start, True
    return t.early_start, False


def match_milestones(
    revisions: list[tuple[str, datetime, XerData]],
) -> MilestoneShiftResult:
    """Build milestone series across revisions, ordered by data date.

    ``revisions`` is a list of ``(revision_label, data_date, XerData)``; it is
    sorted by data date internally so callers may pass any order.
    """
    result = MilestoneShiftResult()
    ordered = sorted(revisions, key=lambda r: r[1])

    # Stage 1 — group milestones by exact Activity ID across revisions.
    series_by_code: dict[str, MilestoneSeries] = {}
    for label, data_date, data in ordered:
        for t in data.tasks:
            if not t.is_milestone or not t.task_code:
                continue
            value_date, is_actual = _milestone_value_date(t)
            point = ShiftPoint(
                data_date=data_date,
                revision_label=label,
                value_date=value_date,
                is_actual=is_actual,
                task_code=t.task_code,
                task_name=t.name,
            )
            ser = series_by_code.get(t.task_code)
            if ser is None:
                ser = MilestoneSeries(key=t.task_code, name=t.name)
                series_by_code[t.task_code] = ser
            ser.points.append(point)
            # Keep the most recent non-empty name as representative.
            if t.name:
                ser.name = t.name

    # Stage 2 — fuzzy-match single-revision milestones against multi-revision
    # ones (likely renames/re-IDs). Propose, don't merge.
    multi = [s for s in series_by_code.values() if _distinct_revisions(s) > 1]
    singles = [s for s in series_by_code.values() if _distinct_revisions(s) == 1]
    for single in singles:
        best, ratio = _best_name_match(single.name, multi)
        if best is not None and ratio >= NAME_MATCH_THRESHOLD and best.key != single.key:
            p = single.points[0]
            result.needs_confirmation.append(
                MilestoneMatch(
                    revision_label=p.revision_label,
                    task_code=single.key,
                    task_name=single.name,
                    matched_to_key=best.key,
                    matched_to_name=best.name,
                    similarity=round(ratio, 3),
                )
            )

    # Sort each series' points by data date (already ordered, but be explicit).
    for ser in series_by_code.values():
        ser.points.sort(key=lambda p: p.data_date)

    # Present multi-revision series first (they carry an actual shift signal).
    result.series = sorted(
        series_by_code.values(),
        key=lambda s: (-_distinct_revisions(s), s.key),
    )

    if len(ordered) < 2:
        result.warnings.append(
            "Fewer than two revisions supplied — no shift can be computed."
        )
    return result


def track_milestone_shifts(
    revisions: list[tuple[str, datetime, XerData]],
) -> MilestoneShiftResult:
    """Alias with the public-API verb; see :func:`match_milestones`."""
    return match_milestones(revisions)


def _distinct_revisions(series: MilestoneSeries) -> int:
    return len({p.data_date for p in series.points})


def _best_name_match(
    name: str, candidates: list[MilestoneSeries]
) -> tuple[MilestoneSeries | None, float]:
    best: MilestoneSeries | None = None
    best_ratio = 0.0
    for cand in candidates:
        ratio = difflib.SequenceMatcher(
            None, name.lower(), cand.name.lower()
        ).ratio()
        if ratio > best_ratio:
            best, best_ratio = cand, ratio
    return best, best_ratio
