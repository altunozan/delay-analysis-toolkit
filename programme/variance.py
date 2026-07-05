"""Module 4 — Preliminary As-Planned vs As-Recorded.

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


def _planned_dates(t: Task) -> tuple[datetime | None, datetime | None]:
    """Baseline planned start/finish (target dates, falling back to early)."""
    start = t.target_start or t.early_start
    finish = t.target_finish or t.early_finish
    return start, finish


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
