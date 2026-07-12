"""Module 12 — As-Built Critical Path (contemporaneous reconstruction).

Two deterministic, mutually reinforcing views of what actually drove the
works, both read from the project's own contemporaneous programmes:

1. **Stitched contemporaneous path** — for each window between data dates,
   the activities that were on the then-forecast longest path AND were
   actually performed during that window. Stitching those segments across
   windows reconstructs the as-built critical path as the contemporaneous
   records saw it (the observational approach; no analyst theory of what
   "should" have been critical is injected).

2. **Criticality persistence index** — for every activity, in how many
   revisions it sat on the forecast longest path while still to be
   performed. Activities critical in revision after revision form the
   empirical spine of the as-built path; activities critical only once are
   flagged as weakly corroborated.

Pure engine: ordered XerData revisions in, structured result out. No LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from dcma.config import DCMAConfig
from dcma.xer_parser import XerData

from .critical_path import extract_longest_path

STANDING_CAVEATS = [
    "The reconstruction reads the project's own contemporaneous programmes: "
    "an activity is on the as-built critical path for a window when the "
    "programme in force at that window's start forecast it critical and the "
    "records show it was performed in that window. It asserts no analyst "
    "theory of what should have been critical.",
    "The quality of the reconstruction is bounded by the update cadence and "
    "the reliability of each update (see the DCMA and revision-comparison "
    "modules); long gaps between data dates coarsen the windows.",
    "Forecast criticality per revision comes from a backward driving-logic "
    "trace from that revision's completion; actual dates are taken from the "
    "revision that closes each window, i.e. as contemporaneously recorded.",
    "Identifying the driving chain is a factual screening; it does not "
    "attribute delay in any window to either party.",
]


@dataclass
class PersistenceEntry:
    task_code: str
    name: str
    times_on_path: int
    times_eligible: int             # revisions where present & incomplete
    act_start: datetime | None      # from the latest revision
    act_finish: datetime | None
    is_complete: bool = False

    @property
    def frequency(self) -> float:
        return (self.times_on_path / self.times_eligible
                if self.times_eligible else 0.0)


@dataclass
class StitchActivity:
    task_code: str
    name: str
    act_start: datetime | None
    act_finish: datetime | None
    forecast_by: str                # revision whose path predicted it


@dataclass
class StitchWindow:
    index: int
    from_label: str
    to_label: str
    start: datetime | None
    end: datetime | None
    activities: list[StitchActivity] = field(default_factory=list)
    forecast_critical_count: int = 0   # path size at window start
    coverage_pct: float | None = None  # window days with driving work active


@dataclass
class AsBuiltPathResult:
    revision_count: int = 0
    persistence: list[PersistenceEntry] = field(default_factory=list)
    windows: list[StitchWindow] = field(default_factory=list)
    core_codes: list[str] = field(default_factory=list)   # persistent core
    remaining_path_count: int = 0    # last revision's path still to perform
    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    @property
    def stitched(self) -> list[StitchActivity]:
        """The full stitched chain across windows, in actual-start order."""
        acts = [a for w in self.windows for a in w.activities]
        acts.sort(key=lambda a: (a.act_start or datetime.max,
                                 a.act_finish or datetime.max))
        return acts


def analyse_asbuilt_path(
    revisions: list[tuple[str, XerData]],
    *,
    core_min_frequency: float = 0.5,
    low_coverage_pct: float = 50.0,
    config: DCMAConfig | None = None,
) -> AsBuiltPathResult:
    """Reconstruct the as-built critical path from ordered revisions.

    ``core_min_frequency`` — an activity belongs to the persistent core when
    it was on the forecast path in at least this fraction of the revisions
    in which it was still to be performed (and in at least two revisions,
    where the revision count allows).
    """
    config = config or DCMAConfig()
    result = AsBuiltPathResult(revision_count=len(revisions))
    result.caveats.extend(STANDING_CAVEATS)

    if len(revisions) < 2:
        result.warnings.append(
            "At least two revisions are required to reconstruct an as-built "
            "path from contemporaneous programmes."
        )
        return result

    # --- longest path + eligibility per revision --------------------------
    paths: list[dict[str, str]] = []          # per revision: code -> name
    eligible: list[set[str]] = []             # incomplete codes per revision
    for label, data in revisions:
        cp = extract_longest_path(data, label, config=config)
        paths.append({a.task_code: a.name for a in cp.critical})
        eligible.append({t.task_code for t in data.tasks
                         if not t.is_loe_or_wbs and t.is_incomplete})

    # --- persistence index -------------------------------------------------
    last_label, last_data = revisions[-1]
    last_by_code = {t.task_code: t for t in last_data.tasks
                    if not t.is_loe_or_wbs}
    ever_on_path: dict[str, str] = {}
    for p in paths:
        ever_on_path.update(p)
    for code, name in ever_on_path.items():
        on = sum(1 for p in paths if code in p)
        elig = sum(1 for e in eligible if code in e)
        t = last_by_code.get(code)
        result.persistence.append(PersistenceEntry(
            task_code=code, name=name,
            times_on_path=on, times_eligible=max(elig, on),
            act_start=t.act_start if t else None,
            act_finish=t.act_finish if t else None,
            is_complete=t.is_complete if t else False,
        ))
    result.persistence.sort(
        key=lambda e: (-e.frequency, e.act_start or datetime.max))
    min_times = 2 if len(revisions) > 2 else 1
    result.core_codes = [
        e.task_code for e in result.persistence
        if e.frequency >= core_min_frequency
        and e.times_on_path >= min_times
    ]

    # --- stitched contemporaneous path --------------------------------------
    for i in range(len(revisions) - 1):
        (l_from, d_from), (l_to, d_to) = revisions[i], revisions[i + 1]
        dd_from = d_from.project.data_date if d_from.project else None
        dd_to = d_to.project.data_date if d_to.project else None
        win = StitchWindow(index=i + 1, from_label=l_from, to_label=l_to,
                           start=dd_from, end=dd_to,
                           forecast_critical_count=len(paths[i]))
        # Actuals as contemporaneously recorded by the closing revision.
        closing = {t.task_code: t for t in d_to.tasks if not t.is_loe_or_wbs}
        intervals = []
        for code, name in paths[i].items():
            t = closing.get(code)
            if t is None or t.act_start is None:
                continue
            a_start, a_finish = t.act_start, t.act_finish
            if dd_from and dd_to:
                # executed during the window?
                started_before_end = a_start < dd_to
                finished_after_start = (a_finish is None
                                        or a_finish > dd_from)
                if not (started_before_end and finished_after_start):
                    continue
                intervals.append((max(a_start, dd_from),
                                  min(a_finish or dd_to, dd_to)))
            win.activities.append(StitchActivity(
                task_code=code, name=name,
                act_start=a_start, act_finish=a_finish,
                forecast_by=l_from))
        win.activities.sort(key=lambda a: (a.act_start or datetime.max))

        # Coverage: share of the window with forecast-critical work active.
        if dd_from and dd_to and dd_to > dd_from:
            merged, total = [], 0.0
            for s, e in sorted(intervals):
                if merged and s <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], e))
                else:
                    merged.append((s, e))
            total = sum((e - s).total_seconds() for s, e in merged)
            win.coverage_pct = round(
                100.0 * total / (dd_to - dd_from).total_seconds(), 1)
        result.windows.append(win)

    # Remaining (not yet as-built) path at the last data date.
    result.remaining_path_count = sum(
        1 for code in paths[-1]
        if (t := last_by_code.get(code)) is not None and t.is_incomplete)

    # --- diagnostics ---------------------------------------------------------
    for w in result.windows:
        if not w.activities:
            result.warnings.append(
                f"Window {w.index} ({w.from_label} -> {w.to_label}): none of "
                f"the {w.forecast_critical_count} activities forecast "
                "critical at the window's start were recorded as performed "
                "in the window — the then-critical work did not progress, "
                "or progress was recorded elsewhere."
            )
        elif (w.coverage_pct is not None
                and w.coverage_pct < low_coverage_pct):
            result.warnings.append(
                f"Window {w.index}: forecast-critical work was active for "
                f"only {w.coverage_pct:.0f}% of the window — the driving "
                "work was idle for substantial periods, or the true driver "
                "sat off the forecast path."
            )
    if result.core_codes:
        share = len(result.core_codes) / max(len(result.persistence), 1)
        result.warnings.append(
            f"Corroboration: {len(result.core_codes)} activities "
            f"({share:.0%} of all ever-critical activities) form the "
            "persistent core — critical in at least "
            f"{core_min_frequency:.0%} of the revisions in which they "
            "remained to be performed."
        )
    if result.remaining_path_count:
        result.warnings.append(
            f"{result.remaining_path_count} activities on the latest "
            "revision's forecast path are still to be performed — the "
            "as-built reconstruction covers the works up to the latest "
            "data date only."
        )
    return result
