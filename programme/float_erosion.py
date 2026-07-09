"""Module 9 — Float Erosion Tracker.

Tracks total float across programme revisions: the float profile of each
revision (how much of the incomplete work is critical, near-critical, or
negative) and, per window between revisions, which activities consumed the
most float. Float consumption without completion movement often precedes
visible slippage — this module makes that erosion measurable.

Pure engine: ordered XerData revisions in, structured result out. No LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from statistics import median

from dcma.config import DCMAConfig
from dcma.xer_parser import XerData

STANDING_CAVEATS = [
    "Total float is read from each revision as scheduled; it reflects that "
    "revision's own logic, constraints, and calendars. Changes in float can "
    "arise from progress, re-logic, or re-planning alike — the revision "
    "comparison module separates those causes.",
    "Erosion is measured on activities that are present and incomplete in "
    "both revisions of a window, matched by Activity ID.",
    "Float describes scheduling flexibility within the programme; its "
    "ownership is a contractual question outside this module's scope.",
]


@dataclass
class FloatSnapshot:
    label: str
    data_date: datetime | None
    incomplete_count: int = 0
    negative_count: int = 0
    critical_count: int = 0        # TF <= 0
    near_count: int = 0            # 0 < TF <= near_days
    median_float: float | None = None
    min_float: float | None = None


@dataclass
class FloatDelta:
    task_code: str
    name: str
    old_tf: float
    new_tf: float

    @property
    def delta(self) -> float:
        return self.new_tf - self.old_tf


@dataclass
class WindowErosion:
    index: int
    from_label: str
    to_label: str
    matched: int = 0
    median_delta: float | None = None
    eroded_count: int = 0          # delta < -1d
    gained_count: int = 0          # delta > +1d
    top_eroders: list[FloatDelta] = field(default_factory=list)
    top_gainers: list[FloatDelta] = field(default_factory=list)


@dataclass
class FloatErosionResult:
    near_days: float
    snapshots: list[FloatSnapshot] = field(default_factory=list)
    windows: list[WindowErosion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


def _floats(data: XerData, config: DCMAConfig) -> dict[str, tuple[str, float]]:
    """task_code -> (name, TF days) for incomplete, non-LOE/WBS activities."""
    out = {}
    for t in data.tasks:
        if t.is_loe_or_wbs or t.is_complete:
            continue
        tf = t.total_float_days(data.hours_per_day(t, config))
        if tf is not None:
            out[t.task_code] = (t.name, round(tf, 1))
    return out


def analyse_float_erosion(
    revisions: list[tuple[str, XerData]],
    *,
    near_days: float = 10.0,
    top_n: int = 15,
    config: DCMAConfig | None = None,
) -> FloatErosionResult:
    """Float profile per revision + float consumption per window."""
    config = config or DCMAConfig()
    result = FloatErosionResult(near_days=near_days)
    result.caveats.extend(STANDING_CAVEATS)

    floats_by_label: dict[str, dict[str, tuple[str, float]]] = {}
    for label, data in revisions:
        fl = _floats(data, config)
        floats_by_label[label] = fl
        values = [tf for _, tf in fl.values()]
        snap = FloatSnapshot(
            label=label,
            data_date=data.project.data_date if data.project else None,
            incomplete_count=len(values),
        )
        if values:
            snap.negative_count = sum(1 for v in values if v < 0)
            snap.critical_count = sum(1 for v in values if v <= 0)
            snap.near_count = sum(1 for v in values if 0 < v <= near_days)
            snap.median_float = round(median(values), 1)
            snap.min_float = round(min(values), 1)
        result.snapshots.append(snap)

    for i in range(len(revisions) - 1):
        l_old, l_new = revisions[i][0], revisions[i + 1][0]
        old_fl, new_fl = floats_by_label[l_old], floats_by_label[l_new]
        deltas = [
            FloatDelta(code, new_fl[code][0], old_fl[code][1],
                       new_fl[code][1])
            for code in old_fl.keys() & new_fl.keys()
        ]
        win = WindowErosion(index=i + 1, from_label=l_old, to_label=l_new,
                            matched=len(deltas))
        if deltas:
            win.median_delta = round(median(d.delta for d in deltas), 1)
            win.eroded_count = sum(1 for d in deltas if d.delta < -1)
            win.gained_count = sum(1 for d in deltas if d.delta > 1)
            by_delta = sorted(deltas, key=lambda d: d.delta)
            win.top_eroders = [d for d in by_delta[:top_n] if d.delta < -1]
            win.top_gainers = [d for d in reversed(by_delta[-top_n:])
                               if d.delta > 1]
        result.windows.append(win)

    # --- diagnostics -----------------------------------------------------
    for a, b in zip(result.snapshots, result.snapshots[1:]):
        if (a.median_float is not None and b.median_float is not None
                and b.median_float < a.median_float - 1):
            result.warnings.append(
                f"Median total float fell from {a.median_float:.0f}d "
                f"('{a.label}') to {b.median_float:.0f}d ('{b.label}') — "
                "the programme's overall flexibility eroded in this window."
            )
    last = result.snapshots[-1] if result.snapshots else None
    if last and last.negative_count:
        result.warnings.append(
            f"'{last.label}' carries {last.negative_count} incomplete "
            f"activities with NEGATIVE float (minimum "
            f"{last.min_float:.0f}d) — the programme cannot meet its "
            "completion as scheduled without acceleration or re-planning."
        )
    stable = [w for w in result.windows
              if w.median_delta is not None and w.median_delta >= -1]
    if stable and len(stable) == len(result.windows):
        result.warnings.append(
            "Favourable: median float held stable (or improved) in every "
            "window — no general erosion of programme flexibility."
        )
    return result
