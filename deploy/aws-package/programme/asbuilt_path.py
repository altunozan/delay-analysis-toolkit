"""As-Built Critical Path — backward trace from a chosen milestone.

ONE method, the way a delay analyst actually works:

    pick the milestone -> walk backwards, activity by activity, to the
    start of the works.

At each step the predecessor is the activity whose recorded dates most
tightly precede it. Where a programmed relationship exists between the
pair it corroborates the hand-off; where none does, the chain continues
on SEQUENCE alone and says so, because a real as-built path does not
stop just because the contractor never drew the link.

The milestone may be one the works never reached. Then the path is a
disclosed HYBRID: as-built up to the data date, forecast beyond it,
every activity labelled with its basis.

Pure engine. No LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from dcma.config import DCMAConfig
from dcma.xer_parser import XerData


@dataclass
class PathActivity:
    """One activity on the traced as-built path."""
    task_code: str
    name: str
    act_start: datetime | None
    act_finish: datetime | None
    forecast_by: str = "actual-date trace"
    # "as-built" (actual finish recorded) | "in-progress" (started, not
    # finished) | "forecast" (neither — the file's remaining early dates)
    basis: str = "as-built"



TRACE_CAVEATS = [
    "The trace walks backward from the elected completion milestone (or, "
    "where none is elected, the latest actualised activity), at each step "
    "following the candidate predecessor whose recorded dates most tightly "
    "precede the activity (smallest hand-off gap), strengthened where a "
    "logic relationship between the pair existed in any programme "
    "revision. It is independent of any revision's forecast criticality.",
    "Each link carries a confidence score (temporal tightness + logic "
    "evidence). Links flagged weak — a large gap or no logic in any "
    "revision — mark hand-offs where the true driver may be a resource, "
    "access, or off-programme constraint; these call for analyst review.",
    "By default the chain CONTINUES through the tightest temporal "
    "neighbour where no programmed relationship exists, so the path runs "
    "unbroken from the terminal back to project start. Every such hop is "
    "recorded as un-evidenced by logic and listed for review: a "
    "date-adjacent hand-off is a sequential observation, not proof that "
    "one activity drove the other.",
]

HYBRID_CAVEAT = (
    "HYBRID PATH — the elected completion milestone has not been achieved "
    "at the latest data date. Activities up to the data date are as-built "
    "(recorded actual dates); the tail from the data date to the milestone "
    "is FORECAST (the programme's own remaining early dates). Every "
    "activity is labelled with its basis, and the forecast portion is not "
    "evidence of what happened — it is what the file predicts will happen."
)


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
    activities: list[PathActivity] = field(default_factory=list)  # chain
    links: list[TraceLink] = field(default_factory=list)
    hybrid: bool = False             # chain includes a forecast tail
    data_date: datetime | None = None
    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    @property
    def codes(self) -> set[str]:
        return {a.task_code for a in self.activities}

    @property
    def asbuilt_count(self) -> int:
        return sum(1 for a in self.activities if a.basis == "as-built")

    @property
    def forecast_count(self) -> int:
        return sum(1 for a in self.activities if a.basis == "forecast")

    @property
    def in_progress_count(self) -> int:
        return sum(1 for a in self.activities if a.basis == "in-progress")


def _basis(t) -> str:
    """Evidential basis of an activity's dates."""
    if t.act_finish is not None:
        return "as-built"
    if t.act_start is not None:
        return "in-progress"
    return "forecast"


def _eff_start(t) -> datetime | None:
    return t.act_start or t.early_start


def _eff_finish(t) -> datetime | None:
    return t.act_finish or t.early_finish


def extract_actual_trace(
    revisions: list[tuple[str, XerData]],
    *,
    end_task_code: str | None = None,
    max_gap_days: float = 15.0,
    overlap_tolerance_days: float = 2.0,
    weak_score: float = 0.5,
    allow_temporal_fallback: bool = True,
    allow_forecast_tail: bool = True,
    config: DCMAConfig | None = None,
) -> ActualTraceResult:
    """Backward trace from the completion milestone through recorded dates.

    Candidate drivers of an activity: predecessors whose finish sits within
    ``max_gap_days`` before its start (finish-start hand-off, small
    overlaps tolerated), or which were running when it started (parallel),
    scored by temporal tightness + logic evidence.

    By DEFAULT the chain continues through the tightest temporal neighbour
    where no programmed relationship exists, so the path runs unbroken from
    the terminal back to project start; those hops are flagged as
    un-evidenced by logic. Set ``allow_temporal_fallback=False`` for the
    strict reading, where the trace stops at the first hand-off the records
    cannot evidence.

    ``allow_forecast_tail`` lets an elected completion milestone that has
    NOT been achieved anchor the trace anyway: the tail from the data date
    to the milestone is taken from the file's remaining early dates and
    labelled ``forecast``, producing a disclosed hybrid path. Completed
    work is never allowed to be driven by work that has not started.
    """
    result = ActualTraceResult()
    result.caveats.extend(TRACE_CAVEATS)
    if not revisions:
        result.warnings.append("No revisions supplied.")
        return result

    _, latest = revisions[-1]
    result.data_date = latest.project.data_date if latest.project else None
    # Universe: everything schedulable that carries usable dates. Pure
    # forecast rows only ever participate in a hybrid tail (guarded below).
    universe = {t.task_code: t for t in latest.tasks
                if not t.is_loe_or_wbs and _eff_start(t) is not None}
    acts = {c: t for c, t in universe.items() if t.act_start is not None}
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

    # Terminal: the elected completion milestone wherever possible. An
    # elected milestone that has NOT been achieved still anchors the
    # trace (hybrid: as-built spine + forecast tail) rather than being
    # silently swapped for whatever finished last.
    if end_task_code and end_task_code in acts:
        terminal = acts[end_task_code]
    elif (end_task_code and allow_forecast_tail
            and end_task_code in universe):
        terminal = universe[end_task_code]
        result.hybrid = True
        result.caveats.insert(0, HYBRID_CAVEAT)
        dd = f"{result.data_date:%d %b %Y}" if result.data_date else \
            "the latest data date"
        fin = _eff_finish(terminal)
        result.warnings.append(
            f"'{end_task_code}' ({terminal.name}) has NOT been achieved "
            f"at {dd}"
            + (f" — the file forecasts it for {fin:%d %b %Y}." if fin
               else ".")
            + " The path below is a HYBRID: as-built up to the data date, "
              "forecast from there to the milestone. The forecast portion "
              "shows what the programme predicts, not what happened."
        )
    else:
        if end_task_code:
            result.warnings.append(
                f"End activity '{end_task_code}' is not in the latest "
                "revision — using the latest actual finisher instead."
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
        if not end_task_code:
            result.warnings.append(
                f"No contractual completion milestone elected — the trace "
                f"terminates at '{terminal.task_code}' ({terminal.name}), "
                "the latest recorded finish. Elect the completion "
                "milestone in Data Intake to anchor the path to it."
            )
    result.terminal_code = terminal.task_code

    def candidates(succ):
        # Completed work cannot have been driven by work that has not
        # started: a pure-forecast predecessor is only admissible where
        # the successor is itself forecast or still in progress.
        succ_basis = _basis(succ)
        allow_forecast_pred = succ_basis in ("forecast", "in-progress")
        s_start = _eff_start(succ)
        out = []
        for p in universe.values():
            if p.task_code == succ.task_code:
                continue
            p_basis = _basis(p)
            if p_basis == "forecast" and not allow_forecast_pred:
                continue
            p_fin, p_start = _eff_finish(p), _eff_start(p)
            if p_fin is None or p_start is None or s_start is None:
                continue
            gap = (s_start - p_fin).total_seconds() / 86400.0
            if -overlap_tolerance_days <= gap <= max_gap_days:
                kind = "finish-start"
            elif p_start <= s_start <= p_fin:
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
        if best.task_code in seen:
            break        # cycle guard — never link to an off-chain pred
        result.links.append(TraceLink(
            pred_code=best.task_code, pred_name=best.name,
            succ_code=cur.task_code, succ_name=cur.name,
            kind=kind, gap_days=round(gap, 1), had_logic=logic,
            score=round(score, 2), alternatives=len(cands) - 1))
        cur = best

    chain.reverse()
    result.activities = [PathActivity(
        task_code=t.task_code, name=t.name,
        act_start=_eff_start(t), act_finish=_eff_finish(t),
        forecast_by="actual-date trace", basis=_basis(t)) for t in chain]

    _annotate_trace(result, weak_score)
    return result


def _annotate_trace(result: ActualTraceResult, weak_score: float) -> None:
    """Composition / weak-link / corroboration warnings — shared by the
    backward trace and the analyst-election constructor, so an elected
    path is disclosed exactly as sternly as a computed one."""
    if result.forecast_count or result.in_progress_count:
        result.warnings.append(
            f"Path composition: {result.asbuilt_count} as-built, "
            f"{result.in_progress_count} in progress, "
            f"{result.forecast_count} forecast "
            f"(of {len(result.activities)} activities). Only the as-built "
            "portion is a record of what happened."
        )

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
    unevidenced = [lk for lk in result.links if not lk.had_logic]
    if result.links:
        result.warnings.append(
            f"Logic corroboration: {len(result.links) - len(unevidenced)} "
            f"of {len(result.links)} traced hand-offs follow a "
            "relationship that existed in at least one programme revision."
        )
    if unevidenced:
        result.warnings.append(
            f"{len(unevidenced)} hand-off(s) continue the chain on "
            "SEQUENCE ALONE — the activities are date-adjacent but no "
            "programmed relationship between them exists in any revision: "
            + "; ".join(f"{lk.pred_code}→{lk.succ_code} (gap "
                        f"{lk.gap_days:+.0f}d)"
                        for lk in unevidenced[:8])
            + (" …" if len(unevidenced) > 8 else "")
            + ". These are sequential observations, not evidenced "
              "drivers — confirm each against the contemporaneous record."
        )


ASBUILT_LP_CAVEATS = [
    "The longest-path candidate walks BACKWARD from the elected milestone "
    "over the programme's own relationships, at each step following the "
    "predecessor whose effective dates — actual where recorded, the "
    "file's forecast where not — finished last: the relationship that "
    "governed the successor's start. It runs through completed work to "
    "the earliest linked activity; it does not stop at the data date.",
    "Where an activity's linked predecessors carry no usable earlier "
    "dates the walk stops and the stop is disclosed — missing logic at "
    "that point breaks the programmed chain, not the tool.",
]


def extract_asbuilt_longest_path(
    data: XerData,
    *,
    end_task_code: str | None = None,
    max_gap_days: float = 15.0,
    weak_score: float = 0.5,
) -> ActualTraceResult:
    """Longest path of the as-built programme, walked to the earliest
    linked activity.

    Backward walk from the elected milestone over the programme's OWN
    relationships, at each step following the predecessor whose
    effective dates — actual where recorded, the file's early dates
    where not — finished last: the relationship that governed the
    successor's start. Unlike a remaining-works longest path it does
    not stop at the data date; completed work carries the walk back to
    the start of the works. Completed work is never driven by work
    that has not started, and the walk only ever steps to an earlier
    start, so it cannot cycle.
    """
    result = ActualTraceResult()
    result.caveats.extend(ASBUILT_LP_CAVEATS)
    result.data_date = data.project.data_date if data.project else None
    by_id = {t.task_id: t for t in data.tasks if not t.is_loe_or_wbs}
    by_code = {t.task_code: t for t in by_id.values()}
    preds_by_id: dict[str, list[str]] = {}
    for r in data.relationships:
        if r.task_id in by_id and r.pred_task_id in by_id:
            preds_by_id.setdefault(r.task_id, []).append(r.pred_task_id)

    if end_task_code and end_task_code in by_code:
        terminal = by_code[end_task_code]
    else:
        if end_task_code:
            result.warnings.append(
                f"End activity '{end_task_code}' is not in this revision "
                "— using the latest effective finisher instead.")
        cands = [t for t in by_id.values() if _eff_finish(t)]
        if not cands:
            result.warnings.append("No activities with usable dates.")
            return result
        terminal = max(cands,
                       key=lambda t: (_eff_finish(t), t.is_milestone))
    result.terminal_code = terminal.task_code
    if terminal.act_finish is None:
        result.hybrid = True
        result.caveats.insert(0, HYBRID_CAVEAT)

    chain: list = []
    seen: set[str] = set()
    cur = terminal
    while cur is not None and cur.task_code not in seen and len(chain) < 500:
        seen.add(cur.task_code)
        chain.append(cur)
        s_start = _eff_start(cur)
        allow_forecast_pred = _basis(cur) in ("forecast", "in-progress")
        preds = preds_by_id.get(cur.task_id, [])
        pool = []
        for pid in preds:
            p = by_id[pid]
            if p.task_code in seen:
                continue
            if _basis(p) == "forecast" and not allow_forecast_pred:
                continue
            p_fin, p_start = _eff_finish(p), _eff_start(p)
            if p_fin is None or p_start is None:
                continue
            if s_start is not None and p_start >= s_start:
                continue        # backward progress only — cannot cycle
            pool.append(p)
        if not pool:
            if preds:
                result.warnings.append(
                    f"Longest path stopped at {cur.task_code} "
                    f"('{cur.name}'): none of its {len(preds)} linked "
                    "predecessor(s) carries usable earlier dates — the "
                    "programmed chain breaks here.")
            break
        best = max(pool, key=lambda p: (_eff_finish(p), _eff_start(p)))
        p_fin, p_start = _eff_finish(best), _eff_start(best)
        if (s_start is not None and p_start is not None
                and p_start <= s_start <= p_fin):
            kind, gap = "parallel", 0.0
        else:
            kind = "finish-start"
            gap = ((s_start - p_fin).total_seconds() / 86400.0
                   if s_start is not None else 0.0)
        t_score = max(0.0, 1.0 - max(gap, 0.0) / max_gap_days)
        if kind == "parallel":
            t_score *= 0.6
        score = 0.6 * t_score + 0.4        # programmed logic throughout
        result.links.append(TraceLink(
            pred_code=best.task_code, pred_name=best.name,
            succ_code=cur.task_code, succ_name=cur.name,
            kind=kind, gap_days=round(gap, 1), had_logic=True,
            score=round(score, 2), alternatives=len(pool) - 1))
        cur = best

    chain.reverse()
    result.activities = [PathActivity(
        task_code=t.task_code, name=t.name,
        act_start=_eff_start(t), act_finish=_eff_finish(t),
        forecast_by="as-built longest path", basis=_basis(t))
        for t in chain]
    _annotate_trace(result, weak_score)
    return result


ELECTION_CAVEATS = [
    "This as-built critical path is the analyst's ELECTION between "
    "computed candidates — the as-built programme's own longest path and "
    "the actual recorded sequence — possibly hand-edited; the adopted "
    "basis is recorded and disclosed with every figure.",
    "Hand-off evidence is recomputed pair by pair along the adopted "
    "chain: the recorded gap between consecutive activities, and whether "
    "a programmed relationship between the pair existed in any revision. "
    "A date-adjacent hand-off is a sequential observation, not proof "
    "that one activity drove the other.",
]


def trace_from_election(
    revisions: list[tuple[str, XerData]],
    path: list[tuple[str, str]],
    *,
    basis_label: str = "analyst election",
    max_gap_days: float = 15.0,
    overlap_tolerance_days: float = 2.0,
    weak_score: float = 0.5,
) -> ActualTraceResult:
    """ActualTraceResult for an analyst-ADOPTED path (the step-① election).

    ``path`` is the adopted ``[(task_code, name)]`` in execution order —
    whichever candidate the analyst picked, plus any hand edits. The
    evidential annotations (basis per activity, gap/logic/score per
    hand-off, hybrid disclosure) are recomputed with the same rules as
    the backward trace, so an elected path is reported no more
    charitably than a computed one. A pair the records cannot support —
    a successor starting before its predecessor even began — scores
    zero temporal evidence and is flagged weak.
    """
    result = ActualTraceResult()
    result.caveats.extend(ELECTION_CAVEATS)
    result.caveats.append(f"Adopted basis: {basis_label}.")
    if not revisions or not path:
        result.warnings.append("No adopted path to report.")
        return result

    _, latest = revisions[-1]
    result.data_date = latest.project.data_date if latest.project else None
    by_code = {t.task_code: t for t in latest.tasks if not t.is_loe_or_wbs}

    logic_pairs: set[tuple[str, str]] = set()
    for _, data in revisions:
        id_to_code = {t.task_id: t.task_code for t in data.tasks}
        for r in data.relationships:
            p, s = id_to_code.get(r.pred_task_id), id_to_code.get(r.task_id)
            if p and s:
                logic_pairs.add((p, s))

    chain = [by_code[c] for c, _ in path if c in by_code]
    dropped = len(path) - len(chain)
    if dropped:
        result.warnings.append(
            f"{dropped} adopted code(s) are not in the latest revision "
            "and were dropped from the report.")
    result.activities = [PathActivity(
        task_code=t.task_code, name=t.name,
        act_start=_eff_start(t), act_finish=_eff_finish(t),
        forecast_by="analyst election", basis=_basis(t)) for t in chain]
    if result.activities:
        result.terminal_code = result.activities[-1].task_code
    result.hybrid = result.forecast_count > 0
    if result.hybrid:
        result.caveats.insert(0, HYBRID_CAVEAT)

    for pred, succ in zip(chain, chain[1:]):
        p_fin, p_start = _eff_finish(pred), _eff_start(pred)
        s_start = _eff_start(succ)
        if p_fin is None or s_start is None:
            continue
        gap = (s_start - p_fin).total_seconds() / 86400.0
        if p_start is not None and p_start <= s_start <= p_fin:
            kind, gap = "parallel", 0.0
        else:
            kind = "finish-start"
        t_score = max(0.0, 1.0 - max(gap, 0.0) / max_gap_days)
        if kind == "parallel":
            t_score *= 0.6                # weaker evidence than a hand-off
        elif gap < -overlap_tolerance_days:
            t_score = 0.0                 # succ began before pred started
        logic = (pred.task_code, succ.task_code) in logic_pairs
        score = 0.6 * t_score + 0.4 * (1.0 if logic else 0.0)
        result.links.append(TraceLink(
            pred_code=pred.task_code, pred_name=pred.name,
            succ_code=succ.task_code, succ_name=succ.name,
            kind=kind, gap_days=round(gap, 1), had_logic=logic,
            score=round(score, 2), alternatives=0))

    _annotate_trace(result, weak_score)
    return result


def trace_end_candidates(
    revisions: list[tuple[str, XerData]], limit: int = 40,
    contract_ms: str | None = None,
) -> list[tuple[str, str, datetime | None, bool]]:
    """Terminals to trace back from: (code, name, date, achieved).

    EVERY milestone is offered, achieved or not — you pick the milestone
    you are measuring to, and whether the works reached it is a fact the
    tool discloses, not a filter on the list. Milestones come first
    (elected contractual milestone at the very top), then finished
    activities for the cases where the terminal is ordinary work.
    """
    if not revisions:
        return []
    _, latest = revisions[-1]
    out: list[tuple[str, str, datetime | None, bool]] = []
    seen: set[str] = set()

    def _add(t) -> None:
        out.append((t.task_code, t.name, t.act_finish or t.early_finish,
                    t.act_finish is not None))
        seen.add(t.task_code)

    live = [t for t in latest.tasks if not t.is_loe_or_wbs]
    if contract_ms:
        for t in live:
            if t.task_code == contract_ms:
                _add(t)
                break
    # every milestone, latest date first, achieved or not
    ms = [t for t in live if t.is_milestone and t.task_code not in seen]
    ms.sort(key=lambda t: (t.act_finish or t.early_finish or datetime.min),
            reverse=True)
    for t in ms:
        _add(t)
    done = [t for t in live
            if t.act_finish is not None and t.task_code not in seen]
    done.sort(key=lambda t: t.act_finish, reverse=True)
    out.extend((t.task_code, t.name, t.act_finish, True)
               for t in done[:limit])
    return out
