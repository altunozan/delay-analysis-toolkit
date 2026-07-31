"""Windows / Period Movement Analysis.

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
    "Driver rows trace each window's movement to the later revision's "
    "driving-path activities using STORED dates only (actual finish where "
    "recorded, else the stored early finish) — they show which path "
    "activities moved and by how much, which is attribution of movement "
    "within the schedule model, not a statement of responsibility.",
]


@dataclass
class PathShift:
    task_code: str
    name: str
    direction: str          # "joined" | "left"


@dataclass
class WindowDriver:
    """One driving-path activity's movement across a window — the row-
    level trace behind the window's movement figure. STORED dates only:
    each side is the finish that revision itself asserts (actual finish
    if recorded, else the stored early finish), never a recomputation."""
    task_code: str
    name: str
    membership: str                  # "retained" | "joined"
    finish_old: datetime | None      # prior revision's stored finish
    finish_new: datetime | None      # later revision's stored finish
    slip_days: float | None          # + = moved later within the window
    basis_new: str = ""              # "actual" | "forecast" (later rev)


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
    # --- bifurcation (AACE MIP 3.3/3.4 territory): the prior schedule
    # re-run with the later update's PROGRESS ONLY splits the window's
    # movement into what performance did vs what replanning did --------
    performance_days: float | None = None    # progress-only vs prior own
    replanning_days: float | None = None     # later own vs progress-only
    replan_logic_days: float | None = None   # ..of which logic/duration
    replan_scope_days: float | None = None   # ..of which scope add/drop
    engine_window_days: float | None = None  # perf + replan (engine)
    # --- traceback: the later revision's driving-path activities with
    # their stored finishes on both sides of the window ----------------
    drivers: list[WindowDriver] = field(default_factory=list)

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
    end_task_code: str | None = None,
    branch_tolerance_hours: float = 1.0,
    bifurcate: bool = True,
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
    tasks_by_code: dict[str, dict] = {}            # label -> {code: Task}
    for label, data in revisions:
        cp = extract_longest_path(data, label, config=config,
                     end_task_code=end_task_code,
                     branch_tolerance_hours=branch_tolerance_hours)
        paths[label] = {a.task_code: a.name for a in cp.critical}
        tasks_by_code[label] = {t.task_code: t for t in data.tasks}

    for i in range(len(revisions) - 1):
        (l_old, d_old), (l_new, d_new) = revisions[i], revisions[i + 1]
        dd_old = d_old.project.data_date if d_old.project else None
        dd_new = d_new.project.data_date if d_new.project else None
        f_old = d_old.project.scheduled_finish if d_old.project else None
        f_new = d_new.project.scheduled_finish if d_new.project else None

        row = WindowRow(
            index=i + 1, from_label=l_old, to_label=l_new,
            start=dd_old, end=dd_new,
            # total_seconds/86400, NOT .days — timedelta.days truncates
            # toward whole days, so two +12h movements report [0, 0]
            # and windows stop telescoping to the true overall change
            window_days=(round((dd_new - dd_old).total_seconds() / 86400,
                               1) if dd_old and dd_new else None),
            finish_old=f_old, finish_new=f_new,
            movement_days=(round((f_new - f_old).total_seconds() / 86400,
                                 1) if f_old and f_new else None),
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

        # --- traceback: per-activity movement on the incoming driving
        # path, from each revision's OWN stored dates. The window's
        # movement figure is only defensible when the reader can see
        # which path activities slipped inside the window and by how
        # much — this is that row set, not a recomputation.
        t_old = tasks_by_code[l_old]
        t_new = tasks_by_code[l_new]
        for code, name in new_cp.items():
            tn = t_new.get(code)
            if tn is None:
                continue
            to = t_old.get(code)
            fin_new = tn.act_finish or tn.early_finish
            fin_old = (to.act_finish or to.early_finish) if to else None
            slip = (round((fin_new - fin_old).total_seconds() / 86400, 1)
                    if fin_new and fin_old else None)
            row.drivers.append(WindowDriver(
                task_code=code, name=name,
                membership="retained" if code in old_cp else "joined",
                finish_old=fin_old, finish_new=fin_new,
                slip_days=slip,
                basis_new="actual" if tn.act_finish else "forecast"))
        # biggest movers first; incomparable rows (new activities) last
        row.drivers.sort(
            key=lambda d: (d.slip_days is None,
                           -(d.slip_days or 0.0), d.task_code))

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

    # --- bifurcation: performance vs replanning per window ------------
    if bifurcate and len(revisions) >= 2:
        from .progress_transfer import run_progress_transfer
        by_label = dict(revisions)
        own_completion: dict[str, "datetime | None"] = {}

        def _own(label: str):
            if label not in own_completion:
                d = by_label[label]
                own_completion[label] = run_progress_transfer(
                    d, d, label, label,
                    config=config).completion_reference
            return own_completion[label]

        for row in result.windows:
            try:
                tr = run_progress_transfer(
                    by_label[row.from_label], by_label[row.to_label],
                    row.from_label, row.to_label, config=config)
                prev_own = _own(row.from_label)
                if tr.completion_transferred and prev_own:
                    row.performance_days = round(
                        (tr.completion_transferred - prev_own
                         ).total_seconds() / 86400.0, 1)
                if (tr.completion_reference
                        and tr.completion_transferred):
                    row.replanning_days = round(
                        (tr.completion_reference
                         - tr.completion_transferred
                         ).total_seconds() / 86400.0, 1)
                if tr.network_effect_days is not None:
                    row.replan_logic_days = round(
                        -tr.network_effect_days, 1)
                if tr.scope_effect_days is not None:
                    row.replan_scope_days = round(
                        -tr.scope_effect_days, 1)
                if (row.performance_days is not None
                        and row.replanning_days is not None):
                    row.engine_window_days = round(
                        row.performance_days + row.replanning_days, 1)
            except Exception as exc:               # noqa: BLE001
                result.warnings.append(
                    f"Window {row.index}: bifurcation failed "
                    f"({type(exc).__name__}) — movement reported "
                    "undecomposed.")
        result.caveats.append(
            "Bifurcation: each window's PRIOR schedule is re-run with "
            "the LATER update's progress only (no revisions), splitting "
            "the window movement into a PERFORMANCE component (what "
            "execution did to the prior plan) and a REPLANNING "
            "component (what the update's logic/duration/scope edits "
            "did), the latter decomposed further into logic/duration "
            "vs scope. All four figures come from the toolkit's own "
            "engine run identically on both files, so the SPLIT is "
            "method-consistent; its total can differ from the "
            "file-scheduled movement by the engines' disclosed "
            "calibration. A large replanning share is the signature of "
            "recovery/re-baselining inside the window, not of "
            "performance.")

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
