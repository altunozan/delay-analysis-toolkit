"""DCMA traceback layer — networked, causal detail behind the scorecard.

Turns the 14-point assessment's flat findings into traceback a reader can
follow: the ordered driving chain behind Check 12, negative-float traces
to the constraint that governs them (the Check 5 -> Check 7 causal link),
path-position banding of every flagged activity, and a cross-check
offender index ("this activity trips checks 1, 5 and 8").

DELIBERATE DESIGN RULE — stored values only. Everything in this module
reads the file's own stored dates, stored total float and logic exactly
as submitted; nothing is recomputed by our CPM. The DCMA assessment is
an audit of the programme *as the contractor's scheduler produced it*;
recomputing would quietly change its meaning from "audit of their file"
to "audit of our recomputation". The TIA engine is kept out on purpose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .checks import CheckResult
from .config import DCMAConfig
from .models import Task
from .xer_parser import XerData

STANDING_CAVEATS = [
    "All traceback below is derived from the file's own stored dates, "
    "stored total float and logic as submitted — nothing is recomputed. "
    "It describes what the programme itself asserts, not what an "
    "independent reschedule would produce.",
    "The driving chain is a single ordered walk following, at each "
    "activity, the predecessor whose relationship most tightly governs "
    "its early dates. Where two links tie within 1 hour, one branch is "
    "followed and the tie is disclosed — parallel driving branches are "
    "not shown.",
    "A negative-float trace identifies the nearest governing constraint "
    "or project-level date, which is a mechanical cause within the "
    "schedule model — not a statement of responsibility for delay.",
]

CONSTRAINT_LABELS = {
    "CS_MSO": "Must Start On",
    "CS_MSOA": "Start On or After",
    "CS_MSOB": "Start On or Before",
    "CS_MEO": "Must Finish On",
    "CS_MEOA": "Finish On or After",
    "CS_MEOB": "Finish On or Before",
    "CS_ALAP": "As Late As Possible",
    "CS_MANDSTART": "Mandatory Start",
    "CS_MANDFIN": "Mandatory Finish",
}

# Constraint types that impose a LATE-date ceiling and can therefore
# manufacture negative float. One-sided "on or after" types only push
# early dates and cannot.
_LATE_DRIVERS = {"CS_MSO", "CS_MSOB", "CS_MEO", "CS_MEOB",
                 "CS_MANDSTART", "CS_MANDFIN"}

_LINK_LABELS = {"PR_FS": "FS", "PR_SS": "SS", "PR_FF": "FF", "PR_SF": "SF"}

_BAND_ORDER = ["driving", "critical", "near-critical", "off-path"]


def _cstr_text(t: Task) -> str:
    parts = []
    for ct, cd in ((t.cstr_type, t.cstr_date), (t.cstr_type2, t.cstr_date2)):
        if ct:
            label = CONSTRAINT_LABELS.get(ct, ct)
            parts.append(f"{label} {cd:%Y-%m-%d}" if cd else label)
    return "; ".join(parts)


@dataclass
class ChainStep:
    """One activity on the driving chain, in data-date -> terminal order."""

    seq: int
    task_code: str
    name: str
    is_milestone: bool
    early_start: datetime | None
    early_finish: datetime | None
    total_float_days: float | None
    link_from_prev: str = ""        # e.g. "FS +5.0d (gap 0.0d)"
    constraint: str = ""


@dataclass
class DrivingChain:
    terminal_code: str = ""
    terminal_name: str = ""
    steps: list[ChainStep] = field(default_factory=list)
    reaches_data_date: bool = False
    break_code: str | None = None    # first activity where the trace broke
    break_reason: str | None = None
    tie_count: int = 0               # driving-link ties (one branch taken)


@dataclass
class FloatTrace:
    """Forward walk from a negative-float activity to its governing driver."""

    origin_code: str
    origin_name: str
    origin_tf_days: float
    via_codes: list[str] = field(default_factory=list)
    driver_kind: str = "unidentified"   # "activity constraint" |
    #                                     "project must-finish" | "unidentified"
    driver_code: str = ""
    driver_detail: str = ""


@dataclass
class FloatDriverGroup:
    driver_detail: str
    driver_kind: str
    driver_code: str
    count: int = 0
    worst_tf_days: float = 0.0
    example: FloatTrace | None = None


@dataclass
class OffenderRow:
    task_code: str
    name: str
    band: str
    checks: list[int] = field(default_factory=list)

    @property
    def checks_label(self) -> str:
        return ", ".join(str(n) for n in self.checks)


@dataclass
class DCMATrace:
    chain: DrivingChain | None = None
    float_traces: list[FloatTrace] = field(default_factory=list)
    float_driver_groups: list[FloatDriverGroup] = field(default_factory=list)
    band_map: dict[str, str] = field(default_factory=dict)  # code -> band
    offenders: list[OffenderRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Driving chain — backward min-slack walk on stored dates (Check 12)
# --------------------------------------------------------------------------- #

def _build_chain(data: XerData, config: DCMAConfig,
                 warnings: list[str]) -> DrivingChain | None:
    eligible = {t.task_id: t for t in data.tasks
                if not t.is_loe_or_wbs and t.is_incomplete}
    if not eligible:
        return None

    terminal = max(
        (t for t in eligible.values() if t.early_finish or t.early_start),
        key=lambda t: ((t.early_finish or t.early_start), t.is_milestone),
        default=None,
    )
    if terminal is None:
        return None
    chain = DrivingChain(terminal_code=terminal.task_code,
                         terminal_name=terminal.name)

    preds_by_succ: dict[str, list] = {}
    for rel in data.relationships:
        if rel.task_id in eligible:
            preds_by_succ.setdefault(rel.task_id, []).append(rel)

    all_by_id = data.tasks_by_id

    def link_slack_hours(rel) -> float | None:
        """Slack of one relationship at the successor, from stored dates."""
        pred = all_by_id.get(rel.pred_task_id)
        succ = eligible[rel.task_id]
        if pred is None:
            return None
        hpd = data.hours_per_day(pred, config)
        lag_days = (rel.lag_hr / hpd) if rel.lag_hr else 0.0
        if rel.pred_type in ("PR_FS", "PR_FF"):
            p_date = pred.early_finish or pred.act_finish
        else:
            p_date = pred.early_start or pred.act_start
        target = (succ.early_finish
                  if rel.pred_type in ("PR_FF", "PR_SF")
                  else succ.early_start)
        if p_date is None or target is None:
            return None
        implied = p_date + timedelta(days=lag_days)
        return (target - implied).total_seconds() / 3600.0

    TIE_TOL_H = 1.0
    dd = data.project.data_date if data.project else None

    walked: list[tuple[Task, str]] = []      # (task, link_from_prev text)
    visited: set[str] = set()
    cur = terminal
    link_text = ""
    stopped_at_complete: str | None = None
    while len(walked) < 600:
        if cur.task_id in visited:
            warnings.append(
                f"Driving-chain walk revisited {cur.task_code} — circular "
                "stored logic; chain truncated there.")
            break
        visited.add(cur.task_id)
        walked.append((cur, link_text))

        scored = []
        for rel in preds_by_succ.get(cur.task_id, []):
            s = link_slack_hours(rel)
            if s is not None:
                scored.append((s, rel))
        if not scored:
            break
        min_slack = min(s for s, _ in scored)
        ties = [(s, rel) for s, rel in scored if s <= min_slack + TIE_TOL_H]
        chain.tie_count += len(ties) - 1
        # Deterministic branch choice: earliest predecessor date, then code.
        def _tiekey(item):
            _, rel = item
            p = all_by_id.get(rel.pred_task_id)
            return ((p.early_start or p.act_start or datetime.max),
                    p.task_code) if p else (datetime.max, "")
        s, rel = min(ties, key=_tiekey)
        pred = all_by_id.get(rel.pred_task_id)
        if pred is None:
            break
        hpd = data.hours_per_day(pred, config)
        lag = round(rel.lag_hr / hpd, 1) if rel.lag_hr else 0.0
        link_text = (f"{_LINK_LABELS.get(rel.pred_type, rel.pred_type)}"
                     f" {lag:+.1f}d (gap {s / 24.0:.1f}d)")
        if pred.task_id not in eligible:      # complete — chain reaches works
            stopped_at_complete = pred.task_code
            break
        cur = pred

    walked.reverse()
    for i, (t, lt) in enumerate(walked, start=1):
        hpd = data.hours_per_day(t, config)
        tf = t.total_float_days(hpd)
        chain.steps.append(ChainStep(
            seq=i,
            task_code=t.task_code,
            name=t.name,
            is_milestone=t.is_milestone,
            early_start=t.early_start or t.act_start,
            early_finish=t.early_finish,
            total_float_days=round(tf, 1) if tf is not None else None,
            constraint=_cstr_text(t),
        ))
    # The stored link text was captured while walking backward: it belongs
    # to the SUCCESSOR of each chosen link, i.e. the next step forward.
    for i in range(len(walked) - 1, 0, -1):
        chain.steps[i].link_from_prev = walked[i - 1][1] or ""
    if chain.steps:
        chain.steps[0].link_from_prev = (
            f"driven by completed {stopped_at_complete}"
            if stopped_at_complete else "")

    first = walked[0][0] if walked else None
    if stopped_at_complete or (first is not None and first.act_start):
        chain.reaches_data_date = True
    elif (first is not None and dd is not None and first.early_start
          and first.early_start <= dd + timedelta(days=2)):
        chain.reaches_data_date = True
    elif first is not None:
        chain.break_code = first.task_code
        cstr = _cstr_text(first)
        chain.break_reason = (
            f"no driving predecessor — early dates governed by "
            f"{'constraint ' + cstr if cstr else 'calendar or data date'}, "
            "not logic")
    return chain


# --------------------------------------------------------------------------- #
# Negative float -> governing constraint (Check 5 -> Check 7 causation)
# --------------------------------------------------------------------------- #

def _trace_float_drivers(data: XerData, config: DCMAConfig,
                         warnings: list[str]
                         ) -> tuple[list[FloatTrace], list[FloatDriverGroup]]:
    eligible = {t.task_id: t for t in data.tasks
                if not t.is_loe_or_wbs and t.is_incomplete}

    def tf_days(t: Task) -> float | None:
        return t.total_float_days(data.hours_per_day(t, config))

    negatives = [t for t in eligible.values()
                 if (tf := tf_days(t)) is not None and tf < 0]
    if not negatives:
        return [], []

    succs_by_pred: dict[str, list[str]] = {}
    for rel in data.relationships:
        if rel.pred_task_id in eligible and rel.task_id in eligible:
            succs_by_pred.setdefault(rel.pred_task_id, []).append(rel.task_id)

    proj = data.project
    memo: dict[str, tuple[str, str, str, list[str]]] = {}

    def driver_of(tid: str, seen: set[str]) -> tuple[str, str, str, list[str]]:
        """(kind, code, detail, via_codes) for the activity's late-date driver."""
        if tid in memo:
            return memo[tid]
        t = eligible[tid]
        if t.cstr_type in _LATE_DRIVERS or t.cstr_type2 in _LATE_DRIVERS:
            res = ("activity constraint", t.task_code,
                   f"{_cstr_text(t)} on {t.task_code} '{t.name}'", [])
            memo[tid] = res
            return res
        if tid in seen:
            return ("unidentified", "", "circular stored logic", [])
        seen = seen | {tid}
        my_tf = tf_days(t)
        cands = []
        for sid in succs_by_pred.get(tid, []):
            s_tf = tf_days(eligible[sid])
            if s_tf is not None and my_tf is not None and s_tf <= my_tf + 1.0:
                cands.append((s_tf, sid))
        if not cands:
            if proj and proj.must_finish:
                res = ("project must-finish", "",
                       f"Project Must Finish By {proj.must_finish:%Y-%m-%d} "
                       "(PROJECT table)", [])
            else:
                res = ("unidentified", "",
                       "no downstream constraint found — late dates set at "
                       "project level", [])
            memo[tid] = res
            return res
        _, nxt = min(cands)
        kind, code, detail, via = driver_of(nxt, seen)
        res = (kind, code, detail, [eligible[nxt].task_code] + via)
        memo[tid] = res
        return res

    traces: list[FloatTrace] = []
    groups: dict[str, FloatDriverGroup] = {}
    for t in sorted(negatives, key=lambda x: tf_days(x)):
        tf = tf_days(t)
        kind, code, detail, via = driver_of(t.task_id, set())
        tr = FloatTrace(
            origin_code=t.task_code, origin_name=t.name,
            origin_tf_days=round(tf, 1),
            via_codes=via[:12], driver_kind=kind,
            driver_code=code, driver_detail=detail,
        )
        traces.append(tr)
        g = groups.get(detail)
        if g is None:
            g = groups[detail] = FloatDriverGroup(
                driver_detail=detail, driver_kind=kind, driver_code=code,
                worst_tf_days=tr.origin_tf_days, example=tr)
        g.count += 1
        g.worst_tf_days = min(g.worst_tf_days, tr.origin_tf_days)

    grouped = sorted(groups.values(), key=lambda g: (-g.count,
                                                     g.worst_tf_days))
    return traces, grouped


# --------------------------------------------------------------------------- #
# Assembly, banding, annotation, offender index
# --------------------------------------------------------------------------- #

def build_dcma_trace(
    data: XerData,
    config: DCMAConfig | None = None,
    results: list[CheckResult] | None = None,
    *,
    near_critical_days: float = 10.0,
) -> DCMATrace:
    """Build the full traceback layer from stored values."""
    config = config or DCMAConfig()
    trace = DCMATrace()
    trace.caveats.extend(STANDING_CAVEATS)

    trace.chain = _build_chain(data, config, trace.warnings)
    trace.float_traces, trace.float_driver_groups = _trace_float_drivers(
        data, config, trace.warnings)

    on_chain = ({s.task_code for s in trace.chain.steps}
                if trace.chain else set())
    tol = config.critical_float_tolerance_days
    for t in data.tasks:
        if t.is_loe_or_wbs or t.is_complete:
            continue
        tf = t.total_float_days(data.hours_per_day(t, config))
        if t.task_code in on_chain:
            band = "driving"
        elif tf is not None and tf <= tol:
            band = "critical"
        elif tf is not None and tf <= near_critical_days:
            band = "near-critical"
        else:
            band = "off-path"
        trace.band_map[t.task_code] = band

    if results:
        by_code = {t.task_code: t for t in data.tasks}
        hits: dict[str, list[int]] = {}
        for r in results:
            if r.number in (12, 13, 14):
                # 12 is not an offence; 13/14 are project-level indices.
                # Supplementary activity-level checks (15-17) DO count.
                continue
            for code in set(r.affected_ids):
                hits.setdefault(code, []).append(r.number)
        for code, nums in hits.items():
            if len(nums) < 2:
                continue
            t = by_code.get(code)
            trace.offenders.append(OffenderRow(
                task_code=code,
                name=t.name if t else "",
                band=trace.band_map.get(code, "off-path"),
                checks=sorted(nums),
            ))
        trace.offenders.sort(
            key=lambda o: (_BAND_ORDER.index(o.band)
                           if o.band in _BAND_ORDER else 9,
                           -len(o.checks)))

    if trace.chain and trace.chain.tie_count:
        trace.warnings.append(
            f"{trace.chain.tie_count} driving-link tie(s) within 1 hour "
            "were resolved to a single branch — parallel driving paths "
            "exist and are not shown.")
    if trace.chain and not trace.chain.reaches_data_date:
        trace.warnings.append(
            f"The driving chain does NOT trace back to the data date: it "
            f"breaks at {trace.chain.break_code} ({trace.chain.break_reason})"
            ". Check 12's requirement of a continuous critical path is not "
            "met by logic alone.")
    return trace


def annotate_path_position(results: list[CheckResult],
                           trace: DCMATrace) -> None:
    """Prepend a 'Path position' column to each check's detail rows and
    sort them driving-path first. In-place, idempotent."""
    def rank(band: str) -> int:
        return _BAND_ORDER.index(band) if band in _BAND_ORDER else 9

    for r in results:
        if not r.detail_rows or r.number in (12, 13, 14):
            continue
        new_rows = []
        for row in r.detail_rows:
            if "Path position" in row:
                new_rows.append(row)
                continue
            code = row.get("Activity ID") or row.get("Successor") or ""
            band = trace.band_map.get(code, "—")
            new_rows.append({"Path position": band, **row})
        new_rows.sort(key=lambda row: rank(row.get("Path position", "—")))
        r.detail_rows = new_rows
