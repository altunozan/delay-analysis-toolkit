"""Explain This Delay — milestone-focused assembly across revisions.

Answers "why is this milestone late?" by assembling, per analysis window
between data dates:

- FACT: the milestone's forecast (or actual) date as recorded by each
  revision, and its movement per window;
- INFERENCE: the driving path to that milestone per revision (backward
  driving-logic trace terminating at the milestone), and how that path
  changed in the window — the activities that joined it are the candidate
  drivers of the movement.

The separation is structural: recorded dates and movement are facts from
the files; driver attribution is inference from forecast logic, flagged
as such and weakened explicitly where the path switched substantially.

Pure engine: ordered XerData revisions in, structured result out. No LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from dcma.config import DCMAConfig
from dcma.xer_parser import XerData

from .critical_path import extract_longest_path

STANDING_CAVEATS = [
    "FACTS in this analysis are the milestone dates as recorded by each "
    "programme revision and the movement between them. DRIVER attribution "
    "is INFERENCE from each revision's forecast driving logic — it "
    "identifies candidates, not proven causes, and must be corroborated "
    "against contemporaneous records (instructions, correspondence, "
    "progress reports) before reliance.",
    "Where the driving path to the milestone changed substantially within "
    "a window, attribution inside that window is correspondingly "
    "uncertain — alternative explanations should be considered and are "
    "flagged.",
    "Movement reflects everything that happened in a window — progress, "
    "re-logic, and re-planning combined; the revision-comparison module "
    "separates those mechanisms.",
    "This analysis does not attribute responsibility to any party.",
]


@dataclass
class ForecastPoint:
    label: str
    data_date: datetime | None
    forecast: datetime | None
    is_actual: bool = False


@dataclass
class DriverShift:
    task_code: str
    name: str
    direction: str            # "joined" | "left"


@dataclass
class ExplainWindow:
    index: int
    from_label: str
    to_label: str
    start: datetime | None
    end: datetime | None
    pre: datetime | None          # milestone forecast at window start
    post: datetime | None         # at window end
    movement_days: float | None = None
    path_similarity: float | None = None
    attribution_reliable: bool = True
    shifts: list[DriverShift] = field(default_factory=list)

    @property
    def joined(self) -> list[DriverShift]:
        return [s for s in self.shifts if s.direction == "joined"]

    @property
    def left(self) -> list[DriverShift]:
        return [s for s in self.shifts if s.direction == "left"]


@dataclass
class ExplainResult:
    target_code: str
    target_name: str = ""
    achieved: bool = False
    total_movement_days: float | None = None
    points: list[ForecastPoint] = field(default_factory=list)
    windows: list[ExplainWindow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


def explain_delay(
    revisions: list[tuple[str, XerData]],
    target_code: str,
    *,
    switch_threshold: float = 0.5,
    config: DCMAConfig | None = None,
) -> ExplainResult:
    """Movement + inferred drivers for one milestone across revisions."""
    config = config or DCMAConfig()
    result = ExplainResult(target_code=target_code)
    result.caveats.extend(STANDING_CAVEATS)
    if len(revisions) < 2:
        result.warnings.append(
            "At least two revisions are required to explain movement."
        )
        return result

    # --- FACTS: the milestone's recorded date per revision ----------------
    paths: list[dict[str, str] | None] = []
    for label, data in revisions:
        t = next((x for x in data.tasks if x.task_code == target_code), None)
        dd = data.project.data_date if data.project else None
        if t is None:
            result.points.append(ForecastPoint(label, dd, None))
            paths.append(None)
            continue
        result.target_name = t.name
        if t.act_finish is not None:
            result.points.append(ForecastPoint(label, dd, t.act_finish,
                                               is_actual=True))
            result.achieved = True
            paths.append(None)          # achieved: no forward path
            continue
        result.points.append(ForecastPoint(
            label, dd, t.early_finish or t.early_start))
        # INFERENCE base: the driving path TO this milestone, per revision
        cp = extract_longest_path(data, label, end_task_code=target_code,
                                  config=config)
        paths.append({a.task_code: a.name for a in cp.critical
                      if a.task_code != target_code})

    dated = [p for p in result.points if p.forecast]
    if len(dated) >= 2:
        result.total_movement_days = round(
            (dated[-1].forecast - dated[0].forecast).total_seconds()
            / 86400, 1)

    # --- per-window movement + driver shifts ------------------------------
    for i in range(len(revisions) - 1):
        p0, p1 = result.points[i], result.points[i + 1]
        win = ExplainWindow(
            index=i + 1, from_label=p0.label, to_label=p1.label,
            start=p0.data_date, end=p1.data_date,
            pre=p0.forecast, post=p1.forecast)
        if p0.forecast and p1.forecast:
            win.movement_days = round(
                (p1.forecast - p0.forecast).total_seconds() / 86400, 1)
        a, b = paths[i], paths[i + 1]
        if a is not None and b is not None:
            union = a.keys() | b.keys()
            if union:
                win.path_similarity = round(
                    100.0 * len(a.keys() & b.keys()) / len(union), 1)
                win.attribution_reliable = (
                    win.path_similarity >= switch_threshold * 100)
            for code in sorted(b.keys() - a.keys()):
                win.shifts.append(DriverShift(code, b[code], "joined"))
            for code in sorted(a.keys() - b.keys()):
                win.shifts.append(DriverShift(code, a[code], "left"))
        result.windows.append(win)

    # --- diagnostics -------------------------------------------------------
    moved = [w for w in result.windows
             if w.movement_days is not None and abs(w.movement_days) > 1]
    if moved:
        worst = max(moved, key=lambda w: abs(w.movement_days))
        result.warnings.append(
            f"Largest movement: {worst.movement_days:+.0f} days in window "
            f"{worst.index} ({worst.from_label} -> {worst.to_label})."
        )
    for w in result.windows:
        if (w.movement_days is not None and abs(w.movement_days) > 1
                and not w.attribution_reliable):
            result.warnings.append(
                f"Window {w.index}: the driving path to the milestone "
                f"changed substantially (similarity "
                f"{w.path_similarity:.0f}%) — driver attribution in this "
                "window is uncertain; consider alternative explanations."
            )
    stable = [w for w in result.windows
              if w.movement_days is not None and abs(w.movement_days) <= 1]
    if stable:
        result.warnings.append(
            f"Favourable: the milestone held within ±1 day in "
            f"{len(stable)} of {len(result.windows)} window(s)."
        )
    if result.achieved:
        last_actual = next((p for p in reversed(result.points)
                            if p.is_actual), None)
        if last_actual:
            result.warnings.append(
                f"The milestone is ACHIEVED (actual "
                f"{last_actual.forecast:%Y-%m-%d} per "
                f"'{last_actual.label}'); the analysis explains how its "
                "forecast moved before achievement."
            )
    return result
