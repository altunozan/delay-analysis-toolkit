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

# --------------------------------------------------------------------------- #
# Independent check — backward trace on ACTUAL dates, with scored links
# --------------------------------------------------------------------------- #

TRACE_CAVEATS = [
    "The actual-date trace walks backward from the latest actualised "
    "activity, at each step following the candidate predecessor whose "
    "recorded dates most tightly precede the activity (smallest hand-off "
    "gap), strengthened where a logic relationship between the pair existed "
    "in any programme revision. It is independent of any revision's "
    "forecast criticality.",
    "Each link carries a confidence score (temporal tightness + logic "
    "evidence). Links flagged weak — a large gap or no logic in any "
    "revision — mark hand-offs where the true driver may be a resource, "
    "access, or off-programme constraint; these call for analyst review.",
]


@dataclass
class TraceLink:
    pred_code: str
    pred_name: str
    succ_code: str
    succ_name: str
    kind: str                   # "finish-start" | "parallel"
    gap_days: float             # succ act_start - pred act_finish
    had_logic: bool             # relationship existed in any revision
    score: float                # 0..1 composite confidence
    alternatives: int           # other candidates within the gap window


@dataclass
class ActualTraceResult:
    terminal_code: str | None = None
    activities: list[StitchActivity] = field(default_factory=list)  # chain
    links: list[TraceLink] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    @property
    def codes(self) -> set[str]:
        return {a.task_code for a in self.activities}


def extract_actual_trace(
    revisions: list[tuple[str, XerData]],
    *,
    end_task_code: str | None = None,
    max_gap_days: float = 15.0,
    overlap_tolerance_days: float = 2.0,
    weak_score: float = 0.5,
    allow_temporal_fallback: bool = False,
    config: DCMAConfig | None = None,
) -> ActualTraceResult:
    """Backward trace through ACTUAL dates in the latest revision.

    Candidate drivers of an activity: predecessors whose actual finish sits
    within ``max_gap_days`` before its actual start (finish-start hand-off,
    small overlaps tolerated), or which were running when it started
    (parallel), scored by temporal tightness + logic evidence.

    By default only candidates with a programmed relationship (in any
    revision) may continue the chain — where none exists within the gap
    window, the trace STOPS and reports the break rather than inventing a
    hand-off from date coincidence. Set ``allow_temporal_fallback=True`` to
    continue through the tightest temporal neighbour instead; such links
    are flagged weak.
    """
    result = ActualTraceResult()
    result.caveats.extend(TRACE_CAVEATS)
    if not revisions:
        result.warnings.append("No revisions supplied.")
        return result

    _, latest = revisions[-1]
    acts = {t.task_code: t for t in latest.tasks
            if not t.is_loe_or_wbs and t.act_start is not None}
    if not acts:
        result.warnings.append(
            "The latest revision records no actualised activities — "
            "nothing to trace."
        )
        return result

    # Logic evidence: relationship code-pairs seen in ANY revision.
    logic_pairs: set[tuple[str, str]] = set()
    for _, data in revisions:
        id_to_code = {t.task_id: t.task_code for t in data.tasks}
        for r in data.relationships:
            p, s = id_to_code.get(r.pred_task_id), id_to_code.get(r.task_id)
            if p and s:
                logic_pairs.add((p, s))

    # Terminal: latest actual finish; a finish milestone within a week of
    # the latest date is preferred over an ordinary activity.
    if end_task_code and end_task_code in acts:
        terminal = acts[end_task_code]
    else:
        if end_task_code:
            result.warnings.append(
                f"End activity '{end_task_code}' has no actual dates in the "
                "latest revision — using the latest actual finisher."
            )
        finished = [t for t in acts.values() if t.act_finish]
        if not finished:
            result.warnings.append("No actually finished activities.")
            return result
        latest_fin = max(t.act_finish for t in finished)
        tail = [t for t in finished
                if (latest_fin - t.act_finish).days <= 7]
        milestones = [t for t in tail if t.is_milestone]
        terminal = max(milestones or tail, key=lambda t: t.act_finish)
    result.terminal_code = terminal.task_code

    def candidates(succ):
        out = []
        for p in acts.values():
            if p.task_code == succ.task_code or p.act_finish is None:
                continue
            gap = (succ.act_start - p.act_finish).total_seconds() / 86400.0
            if -overlap_tolerance_days <= gap <= max_gap_days:
                kind = "finish-start"
            elif (p.act_start <= succ.act_start
                    and p.act_finish >= succ.act_start):
                kind, gap = "parallel", 0.0
            else:
                continue
            t_score = max(0.0, 1.0 - max(gap, 0.0) / max_gap_days)
            if kind == "parallel":
                t_score *= 0.6            # weaker evidence than a hand-off
            logic = (p.task_code, succ.task_code) in logic_pairs
            score = 0.6 * t_score + 0.4 * (1.0 if logic else 0.0)
            out.append((score, gap, kind, logic, p))
        out.sort(key=lambda c: -c[0])
        return out

    chain: list = []
    seen: set[str] = set()
    cur = terminal
    while cur is not None and cur.task_code not in seen and len(chain) < 500:
        seen.add(cur.task_code)
        chain.append(cur)
        cands = candidates(cur)
        if not cands:
            break
        # Logic-first: if any candidate follows a programmed relationship,
        # only those compete. Without logic evidence the chain BREAKS
        # unless the analyst opted into the temporal fallback.
        with_logic = [c for c in cands if c[3]]
        if not with_logic and not allow_temporal_fallback:
            result.warnings.append(
                f"Trace stopped at {cur.task_code} '{cur.name}': "
                f"{len(cands)} activities finished nearby in time but none "
                "carries a programmed relationship to it in any revision — "
                "the records alone cannot evidence the driving hand-off "
                "here (analyst input required to extend the chain)."
            )
            break
        pool = with_logic or cands
        score, gap, kind, logic, best = pool[0]
        result.links.append(TraceLink(
            pred_code=best.task_code, pred_name=best.name,
            succ_code=cur.task_code, succ_name=cur.name,
            kind=kind, gap_days=round(gap, 1), had_logic=logic,
            score=round(score, 2), alternatives=len(cands) - 1))
        cur = best if best.task_code not in seen else None

    chain.reverse()
    result.activities = [StitchActivity(
        task_code=t.task_code, name=t.name,
        act_start=t.act_start, act_finish=t.act_finish,
        forecast_by="actual-date trace") for t in chain]

    weak = [lk for lk in result.links if lk.score < weak_score]
    if weak:
        worst = sorted(weak, key=lambda lk: lk.score)[:6]
        result.warnings.append(
            f"{len(weak)} of {len(result.links)} traced hand-offs are "
            f"weakly evidenced (score < {weak_score:.1f}): "
            + "; ".join(f"{lk.pred_code}->{lk.succ_code} (gap "
                        f"{lk.gap_days:+.0f}d, "
                        f"{'logic' if lk.had_logic else 'NO logic'})"
                        for lk in worst)
            + " — analyst review recommended at these points."
        )
    no_logic = sum(1 for lk in result.links if not lk.had_logic)
    if result.links:
        result.warnings.append(
            f"Logic corroboration: {len(result.links) - no_logic} of "
            f"{len(result.links)} traced hand-offs follow a relationship "
            "that existed in at least one programme revision."
        )
    return result


# --------------------------------------------------------------------------- #
# Method triangulation — agreement between the two reconstructions
# --------------------------------------------------------------------------- #

@dataclass
class TriangulationResult:
    agreement_pct: float | None = None    # Jaccard of the two methods
    both: list[str] = field(default_factory=list)
    stitched_only: list[str] = field(default_factory=list)
    trace_only: list[str] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


def triangulate(stitched: AsBuiltPathResult,
                trace: ActualTraceResult) -> TriangulationResult:
    """Where do the two independent reconstructions agree?"""
    tri = TriangulationResult()
    tri.caveats.append(
        "The two reconstructions are methodologically independent: the "
        "stitched path reads contemporaneous forecast criticality; the "
        "trace reads only recorded actual dates (with logic as secondary "
        "evidence). Activities identified by both are method-invariant "
        "findings; divergences localise where analyst judgement is needed."
    )
    a = {x.task_code: x.name for x in stitched.stitched}
    b = {x.task_code: x.name for x in trace.activities}
    tri.names = {**a, **b}
    both = a.keys() & b.keys()
    union = a.keys() | b.keys()
    tri.both = sorted(both)
    tri.stitched_only = sorted(a.keys() - b.keys())
    tri.trace_only = sorted(b.keys() - a.keys())
    if union:
        tri.agreement_pct = round(100.0 * len(both) / len(union), 1)
    if tri.agreement_pct is not None:
        trace_share = (100.0 * len(both) / len(b)) if b else 0.0
        tri.warnings.append(
            f"Method agreement: {len(both)} activities identified by BOTH "
            f"reconstructions ({tri.agreement_pct:.0f}% of the union; "
            f"{trace_share:.0f}% of the traced chain is corroborated by "
            "the contemporaneous method)."
        )
    if tri.trace_only:
        tri.warnings.append(
            f"{len(tri.trace_only)} activities appear only in the "
            "actual-date trace — candidates for driving work that sat off "
            "the forecast critical path: "
            + ", ".join(tri.trace_only[:8])
            + (" …" if len(tri.trace_only) > 8 else "")
        )
    return tri


def trace_end_candidates(
    revisions: list[tuple[str, XerData]], limit: int = 40
) -> list[tuple[str, str, datetime | None]]:
    """Candidate trace terminals: actually finished, latest first."""
    if not revisions:
        return []
    _, latest = revisions[-1]
    done = [t for t in latest.tasks
            if not t.is_loe_or_wbs and t.act_finish is not None]
    done.sort(key=lambda t: (t.act_finish, t.is_milestone), reverse=True)
    return [(t.task_code, t.name, t.act_finish) for t in done[:limit]]
