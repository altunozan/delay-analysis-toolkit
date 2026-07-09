"""Module 7 — Windows / Period Movement Analysis.

For each window between consecutive data dates: how much the scheduled
completion moved, and how the driving (longest) path changed — which
activities joined and left the critical path between the two revisions.

This is the deterministic skeleton of a contemporaneous windows review: it
quantifies movement per period and shows where the driving path migrated,
without asserting causes. Pure engine: ordered XerData revisions in,
structured result out. No LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from dcma.config import DCMAConfig
from dcma.xer_parser import XerData

from .critical_path import extract_longest_path

STANDING_CAVEATS = [
    "Completion movement per window is the change in the programme's own "
    "scheduled finish between data dates — a forecast movement, not a "
    "demonstration of what caused it.",
    "The driving path per revision is identified by a backward driving-logic "
    "trace from that revision's latest finisher; path membership is compared "
    "by Activity ID, so re-coded activities appear as one leaver plus one "
    "joiner.",
    "A window's movement reflects everything that happened in it — progress, "
    "logic revisions, and re-planning combined; separating those effects "
    "requires the revision comparison module and analyst review.",
]


@dataclass
class PathShift:
    task_code: str
    name: str
    direction: str          # "joined" | "left"


@dataclass
class WindowRow:
    index: int
    from_label: str
    to_label: str
    start: datetime | None          # earlier data date
    end: datetime | None            # later data date
    window_days: float | None
    finish_old: datetime | None
    finish_new: datetime | None
    movement_days: float | None     # + = completion slipped later
    cp_old_count: int = 0
    cp_new_count: int = 0
    cp_retained: int = 0
    cp_similarity: float | None = None   # retained / union
    shifts: list[PathShift] = field(default_factory=list)

    @property
    def joined(self) -> list[PathShift]:
        return [s for s in self.shifts if s.direction == "joined"]

    @property
    def left(self) -> list[PathShift]:
        return [s for s in self.shifts if s.direction == "left"]


@dataclass
class WindowsResult:
    windows: list[WindowRow] = field(default_factory=list)
    total_movement_days: float | None = None
    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


def analyse_windows(
    revisions: list[tuple[str, XerData]],
    *,
    switch_threshold: float = 0.5,
    config: DCMAConfig | None = None,
) -> WindowsResult:
    """Analyse movement per window across data-date-ordered revisions.

    ``revisions`` — (label, parsed data) pairs, ordered earliest first.
    ``switch_threshold`` — path similarity below this flags a driving-path
    switch in that window.
    """
    config = config or DCMAConfig()
    result = WindowsResult()
    result.caveats.extend(STANDING_CAVEATS)

    if len(revisions) < 2:
        result.warnings.append(
            "At least two revisions with distinct data dates are required "
            "for a windows analysis."
        )
        return result

    # Longest path per revision (default terminal = latest finisher).
    paths: dict[str, dict[str, str]] = {}          # label -> {code: name}
    for label, data in revisions:
        cp = extract_longest_path(data, label, config=config)
        paths[label] = {a.task_code: a.name for a in cp.critical}

    for i in range(len(revisions) - 1):
        (l_old, d_old), (l_new, d_new) = revisions[i], revisions[i + 1]
        dd_old = d_old.project.data_date if d_old.project else None
        dd_new = d_new.project.data_date if d_new.project else None
        f_old = d_old.project.scheduled_finish if d_old.project else None
        f_new = d_new.project.scheduled_finish if d_new.project else None

        row = WindowRow(
            index=i + 1, from_label=l_old, to_label=l_new,
            start=dd_old, end=dd_new,
            window_days=((dd_new - dd_old).days
                         if dd_old and dd_new else None),
            finish_old=f_old, finish_new=f_new,
            movement_days=((f_new - f_old).days
                           if f_old and f_new else None),
        )

        old_cp, new_cp = paths[l_old], paths[l_new]
        retained = old_cp.keys() & new_cp.keys()
        union = old_cp.keys() | new_cp.keys()
        row.cp_old_count, row.cp_new_count = len(old_cp), len(new_cp)
        row.cp_retained = len(retained)
        row.cp_similarity = (len(retained) / len(union)) if union else None
        for code in sorted(new_cp.keys() - old_cp.keys()):
            row.shifts.append(PathShift(code, new_cp[code], "joined"))
        for code in sorted(old_cp.keys() - new_cp.keys()):
            row.shifts.append(PathShift(code, old_cp[code], "left"))

        result.windows.append(row)

        if (row.cp_similarity is not None
                and row.cp_similarity < switch_threshold
                and union):
            result.warnings.append(
                f"Window {row.index} ({l_old} -> {l_new}): only "
                f"{row.cp_similarity:.0%} of the driving path is common to "
                "both revisions — the critical path substantially switched "
                "in this window."
            )
        if row.window_days is not None and row.window_days <= 0:
            result.warnings.append(
                f"Window {row.index}: '{l_new}' does not have a later data "
                f"date than '{l_old}' — check the revision ordering."
            )

    movements = [w.movement_days for w in result.windows
                 if w.movement_days is not None]
    if movements:
        result.total_movement_days = float(sum(movements))

    recovering = [w for w in result.windows
                  if w.movement_days is not None and w.movement_days < 0]
    if recovering:
        result.warnings.append(
            "Favourable: completion moved EARLIER in "
            f"{len(recovering)} window(s): "
            + "; ".join(f"window {w.index} ({w.movement_days:+.0f}d)"
                        for w in recovering)
            + "."
        )
    return result
