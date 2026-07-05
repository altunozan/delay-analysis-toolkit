"""Module 5 — Baseline Planned Critical Path.

Extracts the planned critical path from a single programme (typically the
baseline): the set of activities at or below a total-float tolerance, the
driving links between them, and whether they form a continuous chain from
the earliest critical activity to programme completion.

Identification is float-based (the standard screening approach): an activity
is critical when its total float <= tolerance (default 0, negative float
included). A near-critical band is reported alongside for context. Standing
caveats note the limits of float-based identification — multi-calendar
programmes can distort total float relative to a true longest-path trace.

Pure engine: XerData in, structured result out. No LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from dcma.config import DCMAConfig
from dcma.models import Task
from dcma.xer_parser import XerData

FLOAT_CAVEATS = [
    "Critical activities are identified by total float, the standard "
    "screening approach; where multiple calendars are in use, total float "
    "can differ from a longest-path trace and the driving chain should be "
    "confirmed in P6 before being relied on.",
]
LONGEST_PATH_CAVEATS = [
    "The path is identified by a backward driving-logic trace from the "
    "selected end activity: at each step the predecessor(s) imposing the "
    "tightest constraint on the activity's early dates are followed. "
    "Relationship lags are converted at the activity calendar and treated "
    "as elapsed days for comparison, which is an approximation where large "
    "lags meet non-standard calendars.",
    "Links flagged with a gap indicate points where even the tightest "
    "predecessor does not drive the activity's dates — a constraint, "
    "calendar non-work period, or the data date is controlling there.",
]
SHARED_CAVEATS = [
    "This is the PLANNED critical path as scheduled in the selected "
    "programme at its data date; it says nothing about which path actually "
    "drove completion.",
]

# Backwards-compatible alias (float-method caveats + shared).
STANDING_CAVEATS = FLOAT_CAVEATS + SHARED_CAVEATS


@dataclass
class PathActivity:
    task_code: str
    name: str
    task_type: str
    early_start: datetime | None
    early_finish: datetime | None
    duration_days: float | None
    total_float_days: float | None
    is_milestone: bool
    band: str                       # "critical" | "near-critical"


@dataclass
class PathLink:
    """A driving relationship between two path activities."""

    pred_code: str
    succ_code: str
    link_type: str                  # FS / SS / FF / SF
    lag_days: float
    gap_days: float = 0.0           # slack of this link at the successor


@dataclass
class CriticalPathResult:
    programme_label: str
    float_tolerance_days: float
    near_critical_days: float
    method: str = "float"            # "float" | "longest_path"
    end_choice: str | None = None    # trace terminal (longest-path method)
    activities: list[PathActivity] = field(default_factory=list)  # ES order
    links: list[PathLink] = field(default_factory=list)
    chain_segments: int = 0          # connected components among critical acts
    is_continuous: bool = False
    start_activity: str | None = None
    end_activity: str | None = None
    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    @property
    def critical(self) -> list[PathActivity]:
        return [a for a in self.activities if a.band == "critical"]

    @property
    def near_critical(self) -> list[PathActivity]:
        return [a for a in self.activities if a.band == "near-critical"]


_LINK_LABELS = {"PR_FS": "FS", "PR_SS": "SS", "PR_FF": "FF", "PR_SF": "SF"}


def extract_critical_path(
    data: XerData,
    programme_label: str,
    *,
    float_tolerance_days: float = 0.0,
    near_critical_days: float = 10.0,
    config: DCMAConfig | None = None,
) -> CriticalPathResult:
    """Identify the planned critical (and near-critical) path.

    ``float_tolerance_days`` — activities with total float at or below this
    are critical (negative float always qualifies).
    ``near_critical_days`` — activities above the tolerance but at or below
    this float are reported as the near-critical band.
    """
    config = config or DCMAConfig()
    result = CriticalPathResult(
        programme_label=programme_label,
        float_tolerance_days=float_tolerance_days,
        near_critical_days=near_critical_days,
        method="float",
    )
    result.caveats.extend(FLOAT_CAVEATS + SHARED_CAVEATS)

    # --- classify activities by float band -----------------------------
    by_id: dict[str, Task] = {}
    band_by_id: dict[str, str] = {}
    for t in data.tasks:
        if t.is_loe_or_wbs or t.is_complete:
            continue
        hpd = data.hours_per_day(t, config)
        tf = t.total_float_days(hpd)
        if tf is None:
            continue
        if tf <= float_tolerance_days:
            band = "critical"
        elif tf <= near_critical_days:
            band = "near-critical"
        else:
            continue
        by_id[t.task_id] = t
        band_by_id[t.task_id] = band
        result.activities.append(PathActivity(
            task_code=t.task_code,
            name=t.name,
            task_type=t.task_type,
            early_start=t.early_start or t.act_start,
            early_finish=t.early_finish,
            duration_days=t.original_duration_days(hpd),
            total_float_days=round(tf, 1),
            is_milestone=t.is_milestone,
            band=band,
        ))

    result.activities.sort(
        key=lambda a: (a.early_start or datetime.max,
                       a.early_finish or datetime.max)
    )

    if not any(a.band == "critical" for a in result.activities):
        result.warnings.append(
            f"No activities at or below {float_tolerance_days:.0f}d total "
            "float — the programme has no critical path at this tolerance "
            "(possible open ends, constraints, or an unlevelled schedule)."
        )
        return result

    # --- driving links: relationships between CRITICAL activities ------
    critical_ids = {tid for tid, b in band_by_id.items() if b == "critical"}
    adjacency: dict[str, set[str]] = {tid: set() for tid in critical_ids}
    for rel in data.relationships:
        if rel.pred_task_id in critical_ids and rel.task_id in critical_ids:
            pred = by_id[rel.pred_task_id]
            succ = by_id[rel.task_id]
            hpd = data.hours_per_day(pred, config)
            result.links.append(PathLink(
                pred_code=pred.task_code,
                succ_code=succ.task_code,
                link_type=_LINK_LABELS.get(rel.pred_type, rel.pred_type),
                lag_days=round(rel.lag_hr / hpd, 1) if rel.lag_hr else 0.0,
            ))
            adjacency[rel.pred_task_id].add(rel.task_id)
            adjacency[rel.task_id].add(rel.pred_task_id)

    # --- continuity: connected components of the critical subnetwork ---
    seen: set[str] = set()
    segments = 0
    for tid in critical_ids:
        if tid in seen:
            continue
        segments += 1
        stack = [tid]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(adjacency.get(cur, ()))
    result.chain_segments = segments
    result.is_continuous = segments == 1

    crit_sorted = [a for a in result.activities if a.band == "critical"]
    if crit_sorted:
        result.start_activity = crit_sorted[0].task_code
        result.end_activity = crit_sorted[-1].task_code

    if not result.is_continuous:
        result.warnings.append(
            f"The critical activities form {segments} separate chain "
            "segments, not one continuous path — missing logic or "
            "constraints are likely breaking the path (see DCMA checks "
            "1 and 5)."
        )
    isolated = [by_id[tid].task_code for tid in critical_ids
                if not adjacency.get(tid)]
    if isolated:
        result.warnings.append(
            f"{len(isolated)} critical activities have no logic link to any "
            f"other critical activity: {', '.join(sorted(isolated)[:10])}"
            + (" …" if len(isolated) > 10 else "")
        )

    return result

# --------------------------------------------------------------------------- #
# Longest path — backward driving-logic trace
# --------------------------------------------------------------------------- #

def end_activity_candidates(
    data: XerData, limit: int = 40
) -> list[tuple[str, str, datetime | None]]:
    """Candidate trace terminals: incomplete activities, latest finish first.

    Returns (task_code, name, early_finish); finish milestones are listed
    ahead of ordinary activities finishing on the same date.
    """
    cands = [
        t for t in data.tasks
        if not t.is_loe_or_wbs and t.is_incomplete
        and (t.early_finish or t.early_start)
    ]
    cands.sort(
        key=lambda t: ((t.early_finish or t.early_start), t.is_milestone),
        reverse=True,
    )
    return [(t.task_code, t.name, t.early_finish or t.early_start)
            for t in cands[:limit]]


def extract_longest_path(
    data: XerData,
    programme_label: str,
    *,
    end_task_code: str | None = None,
    near_critical_days: float = 10.0,
    gap_flag_days: float = 5.0,
    config: DCMAConfig | None = None,
) -> CriticalPathResult:
    """Backward driving-logic trace from the end activity/milestone.

    At each activity the trace follows the predecessor(s) whose relationship
    imposes the tightest constraint on its early dates (minimum slack; ties
    within 1 hour are all followed). ``end_task_code`` defaults to the
    incomplete activity with the latest early finish.
    """
    config = config or DCMAConfig()
    result = CriticalPathResult(
        programme_label=programme_label,
        float_tolerance_days=0.0,
        near_critical_days=near_critical_days,
        method="longest_path",
    )
    result.caveats.extend(LONGEST_PATH_CAVEATS + SHARED_CAVEATS)

    eligible = {
        t.task_id: t for t in data.tasks
        if not t.is_loe_or_wbs and t.is_incomplete
    }
    by_code = {t.task_code: t for t in eligible.values()}

    # --- terminal -------------------------------------------------------
    if end_task_code and end_task_code in by_code:
        terminal = by_code[end_task_code]
    else:
        if end_task_code:
            result.warnings.append(
                f"End activity '{end_task_code}' not found among incomplete "
                "activities — using the latest finisher instead."
            )
        # Prefer a finish milestone among the latest finishers.
        terminal = max(
            (t for t in eligible.values() if t.early_finish or t.early_start),
            key=lambda t: ((t.early_finish or t.early_start), t.is_milestone),
            default=None,
        )
    if terminal is None:
        result.warnings.append("No incomplete activities with early dates — "
                               "nothing to trace.")
        return result
    result.end_choice = terminal.task_code

    # --- predecessor slack per relationship ------------------------------
    preds_by_succ: dict[str, list] = {}
    for rel in data.relationships:
        if rel.task_id in eligible:
            preds_by_succ.setdefault(rel.task_id, []).append(rel)

    def _link_slack_hours(rel) -> float | None:
        """Slack of one relationship at the successor (clock hours)."""
        pred = eligible.get(rel.pred_task_id) or next(
            (t for t in data.tasks if t.task_id == rel.pred_task_id), None)
        succ = eligible[rel.task_id]
        if pred is None:
            return None
        hpd = data.hours_per_day(pred, config)
        lag_days = (rel.lag_hr / hpd) if rel.lag_hr else 0.0
        if rel.pred_type in ("PR_FS", "PR_FF"):
            p_date = pred.early_finish or pred.act_finish
        else:                                   # SS / SF use pred start
            p_date = pred.early_start or pred.act_start
        target = (eligible[rel.task_id].early_finish
                  if rel.pred_type in ("PR_FF", "PR_SF")
                  else succ.early_start)
        if p_date is None or target is None:
            return None
        implied = p_date + timedelta(days=lag_days)
        return (target - implied).total_seconds() / 3600.0

    TIE_TOL_H = 1.0

    # --- backward walk ----------------------------------------------------
    on_path: set[str] = set()
    stack = [terminal.task_id]
    stopped_at_complete: list[str] = []
    while stack and len(on_path) < 3000:
        cur = stack.pop()
        if cur in on_path:
            continue
        on_path.add(cur)
        rels = preds_by_succ.get(cur, [])
        scored = []
        for rel in rels:
            s = _link_slack_hours(rel)
            if s is not None:
                scored.append((s, rel))
        if not scored:
            continue                     # chain start (or no usable preds)
        min_slack = min(s for s, _ in scored)
        for s, rel in scored:
            if s <= min_slack + TIE_TOL_H:
                pred_task = eligible.get(rel.pred_task_id)
                gap_days = round(s / 24.0, 1)
                if pred_task is None:
                    # Driving pred already complete — trace stops here.
                    done = next((t for t in data.tasks
                                 if t.task_id == rel.pred_task_id), None)
                    if done is not None:
                        stopped_at_complete.append(done.task_code)
                    continue
                hpd = data.hours_per_day(pred_task, config)
                result.links.append(PathLink(
                    pred_code=pred_task.task_code,
                    succ_code=eligible[cur].task_code,
                    link_type=_LINK_LABELS.get(rel.pred_type, rel.pred_type),
                    lag_days=round(rel.lag_hr / hpd, 1) if rel.lag_hr else 0.0,
                    gap_days=gap_days,
                ))
                stack.append(rel.pred_task_id)

    # --- build activity list (path members; near-critical for context) ---
    for t in data.tasks:
        if t.is_loe_or_wbs or t.is_complete:
            continue
        hpd = data.hours_per_day(t, config)
        tf = t.total_float_days(hpd)
        if t.task_id in on_path:
            band = "critical"
        elif tf is not None and tf <= near_critical_days:
            band = "near-critical"
        else:
            continue
        result.activities.append(PathActivity(
            task_code=t.task_code,
            name=t.name,
            task_type=t.task_type,
            early_start=t.early_start or t.act_start,
            early_finish=t.early_finish,
            duration_days=t.original_duration_days(hpd),
            total_float_days=round(tf, 1) if tf is not None else None,
            is_milestone=t.is_milestone,
            band=band,
        ))
    result.activities.sort(
        key=lambda a: (a.early_start or datetime.max,
                       a.early_finish or datetime.max)
    )

    result.chain_segments = 1
    result.is_continuous = True          # by construction of the trace
    crit = result.critical
    if crit:
        result.start_activity = crit[0].task_code
        result.end_activity = terminal.task_code

    # --- diagnostics ------------------------------------------------------
    weak = [lk for lk in result.links if lk.gap_days > gap_flag_days]
    if weak:
        worst = sorted(weak, key=lambda lk: -lk.gap_days)[:8]
        result.warnings.append(
            f"{len(weak)} driving links carry a gap greater than "
            f"{gap_flag_days:.0f} days (largest: "
            + "; ".join(f"{lk.pred_code}->{lk.succ_code} "
                        f"({lk.gap_days:.0f}d)" for lk in worst)
            + ") — at these points a constraint, calendar, or the data date "
            "is controlling rather than logic."
        )
    if stopped_at_complete:
        uniq = sorted(set(stopped_at_complete))
        result.warnings.append(
            f"Trace stopped at {len(uniq)} completed predecessor(s): "
            + ", ".join(uniq[:8]) + (" …" if len(uniq) > 8 else "")
            + " — the remaining path begins at the data date."
        )
    return result
