"""Shared CPM scheduling kernel.

THE calendar-exact simplified scheduling engine for the whole toolkit.
Owns P6 calendar parsing (weekly working masks + exceptions from
``clndr_data``), working-day date arithmetic, network construction from
a parsed XER (retained-logic statusing at the data date), and the
forward / backward passes.

Consumers: TIA, Progress Transfer, Impacted As-Planned, Collapsed
As-Built and the concurrency screening all schedule through this one
module, so a correction here propagates to every method identically —
and the engine's ownership is unambiguous: this file is the
litigation-sensitive core, test-covered by test_qa layers A/B/E/I/J.

Method caveats (disclosed by every consumer): simplified engine, not
P6 — judge DELTAS between two runs of this engine, never absolute
dates; per-run calibration against the file's own P6 forecast is
reported by the consumers.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from dcma.config import DCMAConfig
from dcma.xer_parser import XerData

REL_TO_SHORT = {"PR_FS": "FS", "PR_SS": "SS", "PR_FF": "FF", "PR_SF": "SF"}
P6_EPOCH = datetime(1899, 12, 30)      # P6 stores exception dates as ordinals
CSTR_LABEL = {
    "CS_MSOB": "start on or before", "CS_MEO": "finish on",
    "CS_MEOA": "finish on or after", "CS_MEOB": "finish on or before",
    "CS_MANDFIN": "mandatory finish", "CS_ALAP": "as late as possible",
}
START_FLOOR_CSTR = {"CS_MSO", "CS_MSOA", "CS_MANDSTART"}


# --------------------------------------------------------------------- #
# Calendar arithmetic DELEGATES to dcma.calendar — ONE implementation
# (ported from the parallel QA tree, 2026-07-31) shared with the DCMA
# layer so the two layers can never convert the same lag or holiday
# differently. The mask is a 6-tuple: positions 0..2 keep the original
# (weekdays, holidays, extras) contract; 3..5 add hours/day and shift
# intervals, making FRACTIONAL working-day arithmetic shift-aware
# (Monday 08:00 + 0.5wd on an 8h shift = Monday 12:00, not 20:00) and
# working_days_between the exact inverse of the date arithmetic.
# Whole-day behaviour is unchanged.
# --------------------------------------------------------------------- #
from dcma.calendar import (                                    # noqa: E402
    add_working_days,
    calendar_masks,
    is_working,
    relationship_lag_hours_per_day,
    sub_working_days,
    working_days_between,
)

__all_calendar__ = ["add_working_days", "calendar_masks", "is_working",
                    "relationship_lag_hours_per_day", "sub_working_days",
                    "working_days_between"]


def cyclic_nodes(
    nodes: dict[str, tuple],
    preds: dict[str, list[tuple[str, str, float]]],
) -> set[str]:
    """Nodes trapped in circular logic (Kahn residue).

    (M2) The forward pass schedules these from the data date so a
    diagnostic view never crashes — but their dates are order-dependent,
    so quantum consumers must GATE when a cycle touches the measured
    path rather than present a warned arbitrary number.
    """
    indeg = {n: 0 for n in nodes}
    succs: dict[str, list[str]] = {n: [] for n in nodes}
    for n, plist in preds.items():
        for p, _, _ in plist:
            if p in nodes and n in nodes:
                succs[p].append(n)
                indeg[n] += 1
    queue = [n for n, d in indeg.items() if d == 0]
    done = 0
    while queue:
        u = queue.pop()
        done += 1
        for v in succs[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                queue.append(v)
    return {n for n, d in indeg.items() if d > 0}


def forward_pass(
    nodes: dict[str, tuple],   # id -> (remaining days, working mask|None)
    preds: dict[str, list[tuple[str, str, float]]],  # id -> (pred, type, lag)
    start: datetime,
    started_at: dict[str, datetime],
) -> tuple[dict[str, datetime], dict[str, datetime], list[str],
           dict[str, str]]:
    """Kahn-ordered forward pass.

    Returns (ES, EF, warnings, driver) — ``driver`` maps each node to
    the predecessor whose relationship governed its early start, the
    map the driving-chain walk in comparison attribution rests on. The
    annotation lied about this fourth element for a while; every caller
    already unpacks four.
    """
    warnings: list[str] = []
    succs: dict[str, list[str]] = {n: [] for n in nodes}
    indeg = {n: 0 for n in nodes}
    for n, plist in preds.items():
        for p, _, _ in plist:
            if p in nodes:
                succs[p].append(n)
                indeg[n] += 1
    queue = [n for n, d in indeg.items() if d == 0]
    order: list[str] = []
    while queue:
        u = queue.pop()
        order.append(u)
        for v in succs[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                queue.append(v)
    if len(order) < len(nodes):
        warnings.append(
            f"{len(nodes) - len(order)} activities sit in circular logic "
            "and were scheduled from the data date."
        )
        order += [n for n in nodes if n not in set(order)]

    ES: dict[str, datetime] = {}
    EF: dict[str, datetime] = {}
    driver: dict[str, str] = {}
    for n in order:
        n_days, n_mask = nodes[n]
        es = started_at.get(n, start)
        ef_c = None
        drv_start = None            # predecessor driving the start (FS/SS)
        drv_fin = None              # predecessor driving the finish (FF/SF)
        for p, ltype, lag in preds.get(n, []):
            if p not in EF:
                continue
            p_mask = nodes[p][1] if p in nodes else None
            if ltype in ("FS", "SS"):
                base = EF[p] if ltype == "FS" else ES[p]
                c = add_working_days(base, lag, p_mask)
                if c > es:
                    es, drv_start = c, p
            else:                                   # FF / SF
                base = EF[p] if ltype == "FF" else ES[p]
                c = add_working_days(base, lag, p_mask)
                if ef_c is None or c > ef_c:
                    ef_c, drv_fin = c, p
        ef = add_working_days(es, max(n_days, 0.0), n_mask)
        drv = drv_start
        if ef_c is not None and ef_c > ef:
            # (C2) an FF/SF bound governs the finish: back-compute the
            # start on the activity's own calendar so the duration is
            # PRESERVED, not stretched — downstream SS logic then reads
            # the true ES. The FS/SS floor still holds (max), so an
            # in-progress pin or an earlier-start constraint is never
            # violated; in that corner the finish bound stretches the
            # bar, which is the constraint case, not the default.
            ef, drv = ef_c, drv_fin
            es = max(es, sub_working_days(ef_c, max(n_days, 0.0),
                                          n_mask))
        ES[n], EF[n] = es, ef
        if drv is not None:
            driver[n] = drv
    return ES, EF, warnings, driver


def backward_pass(
    nodes: dict[str, tuple],
    preds: dict[str, list[tuple[str, str, float]]],
    EF: dict[str, datetime],
) -> dict[str, float]:
    """Total float (days) per activity against latest early finish.

    Screening-level mirror of the forward pass: late dates pulled back
    from the network's completion through the same links and calendars;
    TF = late finish - early finish in days.
    """
    if not EF or not nodes:
        return {}
    completion = max(EF.values())
    succs: dict[str, list[str]] = {n: [] for n in nodes}
    indeg = {n: 0 for n in nodes}
    for n, plist in preds.items():
        for p, _, _ in plist:
            if p in nodes and n in nodes:
                succs[p].append(n)
                indeg[n] += 1
    queue = [n for n, d in indeg.items() if d == 0]
    order: list[str] = []
    while queue:
        u = queue.pop()
        order.append(u)
        for v in succs[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                queue.append(v)
    order += [n for n in nodes if n not in set(order)]     # cycles: best effort

    cap_lf = {n: completion for n in nodes}
    cap_ls: dict[str, datetime | None] = {n: None for n in nodes}
    LF: dict[str, datetime] = {}
    LS: dict[str, datetime] = {}
    for s in reversed(order):
        s_days, s_mask = nodes[s]
        lf = cap_lf[s]
        ls = sub_working_days(lf, max(s_days, 0.0), s_mask)
        if cap_ls[s] is not None and cap_ls[s] < ls:
            ls = cap_ls[s]
            lf = min(lf, add_working_days(ls, max(s_days, 0.0), s_mask))
        LF[s], LS[s] = lf, ls
        for p, ltype, lag in preds.get(s, []):
            if p not in cap_lf:
                continue
            p_mask = nodes[p][1]
            if ltype == "FS":
                c = sub_working_days(ls, lag, p_mask)
                if c < cap_lf[p]:
                    cap_lf[p] = c
            elif ltype == "FF":
                c = sub_working_days(lf, lag, p_mask)
                if c < cap_lf[p]:
                    cap_lf[p] = c
            elif ltype == "SS":
                c = sub_working_days(ls, lag, p_mask)
                if cap_ls[p] is None or c < cap_ls[p]:
                    cap_ls[p] = c
            elif ltype == "SF":
                c = sub_working_days(lf, lag, p_mask)
                if cap_ls[p] is None or c < cap_ls[p]:
                    cap_ls[p] = c
    # total float in WORKING-day units on each activity's own calendar —
    # working_days_between is the exact inverse of the date arithmetic
    # above, so TF is in the same units the durations were scheduled in
    return {n: round(working_days_between(EF[n], LF[n], nodes[n][1]), 1)
            for n in nodes if n in EF}


# ES floors: the activity cannot start before the constraint date


def parse_xer_date(s: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def build_network(data: XerData, config, dd):
    """Incomplete-activity network with per-activity working-day masks.

    Returns (inc, nodes, preds, started, masks, warnings). ``started``
    doubles as the early-start floor: data date for in-progress work,
    constraint date for start-on(-or-after)/mandatory-start constraints.
    Finish-side and late constraints are reported, not modelled.
    """
    masks = calendar_masks(data)
    warnings: list[str] = []
    inc = {t.task_id: t for t in data.tasks
           if not t.is_loe_or_wbs and t.is_incomplete}
    code_of = {tid: t.task_code for tid, t in inc.items()}
    nodes: dict[str, tuple] = {}
    started: dict[str, datetime] = {}
    for t in inc.values():
        hpd = data.hours_per_day(t, config)
        rem = t.remaining_duration_days(hpd)
        if rem is None:
            rem = t.original_duration_days(hpd) or 0.0
        nodes[t.task_code] = (max(rem, 0.0), masks.get(t.clndr_id))
        if t.act_start is not None:
            started[t.task_code] = dd

    unmodelled: dict[str, int] = {}
    floored = 0
    for row in data.raw_tables.get("TASK", []):
        code = (row.get("task_code") or "").strip()
        if code not in nodes:
            continue
        for tkey, dkey in (("cstr_type", "cstr_date"),
                           ("cstr_type2", "cstr_date2")):
            ctype = (row.get(tkey) or "").strip()
            if not ctype:
                continue
            if ctype in START_FLOOR_CSTR:
                cdate = parse_xer_date(row.get(dkey) or "")
                if cdate is not None and code not in started:
                    started[code] = max(started.get(code, cdate), cdate)
                    floored += 1
            else:
                unmodelled[ctype] = unmodelled.get(ctype, 0) + 1
    if floored:
        warnings.append(
            f"{floored} start constraint(s) (Must Start On / Start On or "
            "After / mandatory start) applied as early-start floors."
        )
    if unmodelled:
        detail = ", ".join(
            f"{n}× {CSTR_LABEL.get(c, c)}"
            for c, n in sorted(unmodelled.items(), key=lambda x: -x[1]))
        warnings.append(
            f"Constraints present but NOT modelled by this simplified pass "
            f"({detail}) — where these govern in P6, the calibration "
            "figure will absorb the difference; confirm in P6."
        )

    preds: dict[str, list] = {n: [] for n in nodes}
    for rel in data.relationships:
        s = code_of.get(rel.task_id)
        p = code_of.get(rel.pred_task_id)
        if s is None or p is None:
            continue
        # lag basis = the file's own SCHEDOPTIONS election
        # (sched_calendar_on_relationship_lag; P6 default: predecessor)
        if rel.lag_hr:
            hpd, _basis = relationship_lag_hours_per_day(
                data, inc[rel.pred_task_id].clndr_id,
                inc[rel.task_id].clndr_id, config)
            lag = rel.lag_hr / hpd
        else:
            lag = 0.0
        preds[s].append((p, REL_TO_SHORT.get(rel.pred_type, "FS"), lag))
    return inc, nodes, preds, started, masks, warnings
