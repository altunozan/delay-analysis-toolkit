"""Module 18 — Out-of-Sequence Screening & As-Built Logic Repair.

Standalone OOS module (the screening engine formerly embedded in the
comparison-impact module lives here now):

1. **Screening** — recorded actual dates that contradict the network's
   relationship types (`out_of_sequence_flags`), each flag carrying the
   as-built relation the actuals evidence (`rec_*` fields).
2. **Evolution** — each contradiction attributed to the update window in
   which it first appears (`oos_evolution`); disappearing contradictions
   are flagged as retrospective edits.
3. **Repair** — `build_repair_plan` turns the CONCRETE fits into an
   analyst-editable plan, and `apply_asbuilt_repairs` writes a COPY of
   the source .xer with those TASKPRED rows re-typed and re-lagged so
   the as-built logic is consistent with the recorded dates. The source
   file is never modified; 'review'-class flags (reversed as-built
   order, thin actuals) are NEVER auto-applied.

Pure engines: XerData / raw text in, structured results out. No LLM.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from dcma.config import DCMAConfig
from dcma.xer_parser import XerData, parse_xer

OOS_CAVEATS = [
    "Out-of-sequence screening compares recorded actual dates against "
    "the relationship type only; relationship lags and calendars are "
    "not applied, so small overlaps within a lag allowance may be "
    "legitimate. Flags are prompts for enquiry, not findings.",
    "Recommended as-built relations are mechanical fits to the recorded "
    "actual dates, expressed in CALENDAR days. They are offered for "
    "constructing an as-built / logic-repair model only — never as "
    "corrections to the contemporaneous files, which must not be "
    "altered — and every recommendation requires analyst confirmation. "
    "Where the as-built order is REVERSED relative to the planned link, "
    "no relation is auto-fitted; the reversed candidate is stated for "
    "the analyst to accept or reject.",
]

OOS_EVOLUTION_CAVEATS = [
    "A flag 'resolved' in a window means the contradiction is no longer "
    "present in the later file — because the logic was changed, the "
    "actual dates were changed, or the activity was removed. Resolution "
    "is therefore itself a change worth cross-checking in the revision "
    "comparison, not automatically good news.",
]

REPAIR_CAVEATS = [
    "The repaired .xer is a COPY of the source with the selected "
    "TASKPRED rows re-typed and re-lagged to match the recorded actual "
    "dates; the source file and its hash are unchanged. The output is "
    "an as-built modelling artefact for path tracing and verification — "
    "it is not, and must never be presented as, a contemporaneous "
    "record.",
    "Only CONCRETE fits are applicable. 'Review'-class flags (as-built "
    "order reversed, or actuals too thin to evidence a relation) are "
    "never applied automatically; adding reversed logic is an analyst "
    "modelling decision outside this repair.",
    "Repair lags are the observed CALENDAR-day offsets converted to "
    "hours at the successor's calendar hours-per-day. Where the "
    "calendar carries non-working periods inside the offset, P6's "
    "effective working-time lag will differ from the observed calendar "
    "offset; reschedule (F9) in P6 to see the native effect.",
]


# --------------------------------------------------------------------------- #
# Screening + as-built recommendation
# --------------------------------------------------------------------------- #

@dataclass
class OutOfSequenceFlag:
    pred_code: str
    pred_name: str
    link_type: str                # FS / SS / FF / SF
    succ_code: str
    succ_name: str
    detail: str
    overlap_days: float | None    # None when the predecessor is still open
    band: str = "off-path"        # criticality of the link (set when the
    #                               flags are produced inside an impact
    #                               assessment; standalone calls keep the
    #                               default)
    rec_link_type: str = ""       # "SS" / "SF" for a concrete as-built
    #                               fit; "review" where the analyst must
    #                               decide (reversed order / thin actuals)
    rec_lag_days: float | None = None   # calendar-day lag of a concrete fit
    rec_link: str = ""            # display form, e.g. "SS +12d" / "review"
    rec_basis: str = ""           # the dates the recommendation rests on


def _recommend_asbuilt(lt: str, pred, succ,
                       interim: bool) -> tuple[str, float | None, str, str]:
    """Fit the relation the recorded actuals evidence for a violated link.

    Returns (rec_link_type, rec_lag_days, rec_link, rec_basis).
    Concrete fits keep the planned direction and a non-negative
    calendar-day lag; reversed as-built order is never auto-fitted —
    it comes back as 'review' with the reversed candidate stated.
    """
    AS_p, AF_p = pred.act_start, pred.act_finish
    AS_s, AF_s = succ.act_start, succ.act_finish

    def days(a, b) -> float:
        return round((a - b).total_seconds() / 86400.0, 1)

    suffix = " (interim — predecessor still open)" if interim else ""

    if lt in ("FS", "SS"):
        if AS_p and AS_s and AS_s >= AS_p:
            lag = days(AS_s, AS_p)
            return ("SS", lag, f"SS {lag:+.0f}d" + suffix,
                    f"{succ.task_code} started {AS_s:%Y-%m-%d}, "
                    f"{lag:.0f}d after {pred.task_code} started "
                    f"{AS_p:%Y-%m-%d}; an SS link fits the record")
        if AS_p and AS_s:
            lead = days(AS_p, AS_s)
            return ("review", None, "review (order reversed)",
                    f"{succ.task_code} started {lead:.0f}d BEFORE "
                    f"{pred.task_code} started — the planned dependency "
                    f"is not evidenced as-built; candidate: SS "
                    f"{succ.task_code} -> {pred.task_code} {lead:+.0f}d, "
                    "analyst to confirm the as-built driver")
        return ("review", None, "review (incomplete actuals)",
                f"{pred.task_code} has no recorded start; the dependency "
                "is not evidenced as-built yet")

    if lt == "FF":
        if AF_p and AF_s:                 # violated => AF_s < AF_p
            lead = days(AF_p, AF_s)
            return ("review", None, "review (order reversed)",
                    f"{succ.task_code} finished {lead:.0f}d BEFORE "
                    f"{pred.task_code} finished — candidate: FF "
                    f"{succ.task_code} -> {pred.task_code} {lead:+.0f}d, "
                    "analyst to confirm the as-built driver")
        if AS_p and AF_s and AF_s >= AS_p:
            lag = days(AF_s, AS_p)
            return ("SF", lag, f"SF {lag:+.0f}d" + suffix,
                    f"{succ.task_code} finished {AF_s:%Y-%m-%d}, "
                    f"{lag:.0f}d after {pred.task_code} started "
                    f"{AS_p:%Y-%m-%d}; only a start-to-finish fit is "
                    "evidenced while the predecessor is open")
        return ("review", None, "review (incomplete actuals)",
                f"{pred.task_code} has no recorded finish; the "
                "dependency is not evidenced as-built yet")

    # SF violated: successor finished before the predecessor started.
    return ("review", None, "review (order reversed)",
            f"{succ.task_code} finished before {pred.task_code} "
            "started — the planned SF link is not evidenced as-built")


def out_of_sequence_flags(
    data: XerData,
    *,
    tolerance_days: float = 0.1,
) -> list[OutOfSequenceFlag]:
    """Recorded progress that contradicts the relationship type.

    FS: successor started before the predecessor finished.
    SS: successor started before the predecessor started.
    FF: successor finished before the predecessor finished.
    SF: successor finished before the predecessor started.
    Lags/calendars are not applied (see OOS_CAVEATS). Each flag carries
    the as-built relation the recorded dates evidence (rec_*)."""
    usable = {t.task_id: t for t in data.tasks if not t.is_loe_or_wbs}
    labels = {"PR_FS": "FS", "PR_SS": "SS", "PR_FF": "FF", "PR_SF": "SF"}
    flags: list[OutOfSequenceFlag] = []
    for rel in data.relationships:
        pred = usable.get(rel.pred_task_id)
        succ = usable.get(rel.task_id)
        if pred is None or succ is None:
            continue
        lt = labels.get(rel.pred_type, "FS")
        p_gate = (pred.act_finish if lt in ("FS", "FF") else pred.act_start)
        s_move = (succ.act_start if lt in ("FS", "SS") else succ.act_finish)
        if s_move is None:
            continue                        # successor not progressed
        verb = "started" if lt in ("FS", "SS") else "finished"
        gate_verb = "finished" if lt in ("FS", "FF") else "started"
        if p_gate is None:
            # Successor progressed while the gating predecessor date is
            # still unrecorded — flag only if the predecessor is open.
            if pred.is_complete:
                continue
            rt, rl, rlink, rbasis = _recommend_asbuilt(
                lt, pred, succ, interim=True)
            flags.append(OutOfSequenceFlag(
                pred_code=pred.task_code, pred_name=pred.name,
                link_type=lt, succ_code=succ.task_code,
                succ_name=succ.name,
                detail=(f"{succ.task_code} {verb} "
                        f"{s_move:%Y-%m-%d} but predecessor has not "
                        f"{gate_verb} (still open)"),
                overlap_days=None,
                rec_link_type=rt, rec_lag_days=rl,
                rec_link=rlink, rec_basis=rbasis))
            continue
        overlap = (p_gate - s_move).total_seconds() / 86400.0
        if overlap > tolerance_days:
            rt, rl, rlink, rbasis = _recommend_asbuilt(
                lt, pred, succ, interim=False)
            flags.append(OutOfSequenceFlag(
                pred_code=pred.task_code, pred_name=pred.name,
                link_type=lt, succ_code=succ.task_code,
                succ_name=succ.name,
                detail=(f"{succ.task_code} {verb} {s_move:%Y-%m-%d}, "
                        f"{overlap:.0f}d before predecessor "
                        f"{gate_verb} {p_gate:%Y-%m-%d}"),
                overlap_days=round(overlap, 1),
                rec_link_type=rt, rec_lag_days=rl,
                rec_link=rlink, rec_basis=rbasis))
    flags.sort(key=lambda f: -(f.overlap_days
                               if f.overlap_days is not None else -1.0))
    return flags


# --------------------------------------------------------------------------- #
# Evolution across the revision set
# --------------------------------------------------------------------------- #

@dataclass
class OOSWindow:
    """One update window's out-of-sequence movement."""

    from_label: str
    to_label: str
    new_flags: list[OutOfSequenceFlag] = field(default_factory=list)
    resolved_count: int = 0
    total_after: int = 0


@dataclass
class OOSEvolution:
    per_revision: list[tuple[str, int]] = field(default_factory=list)
    windows: list[OOSWindow] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def oos_evolution(
    ordered: list[tuple[str, XerData]],
    *,
    tolerance_days: float = 0.1,
) -> OOSEvolution:
    """Attribute each out-of-sequence record to the update window in
    which it first appears. ``ordered`` — (label, data) pairs, earliest
    first (same shape as the windows engine input)."""
    result = OOSEvolution()
    result.caveats.extend(OOS_CAVEATS + OOS_EVOLUTION_CAVEATS)

    def key(f: OutOfSequenceFlag):
        return (f.pred_code, f.succ_code, f.link_type)

    prev_keys: set | None = None
    prev_label = ""
    for label, data in ordered:
        flags = out_of_sequence_flags(data, tolerance_days=tolerance_days)
        keys = {key(f) for f in flags}
        result.per_revision.append((label, len(flags)))
        if prev_keys is not None:
            result.windows.append(OOSWindow(
                from_label=prev_label, to_label=label,
                new_flags=[f for f in flags if key(f) not in prev_keys],
                resolved_count=len(prev_keys - keys),
                total_after=len(flags)))
        prev_keys, prev_label = keys, label

    resolved_total = sum(w.resolved_count for w in result.windows)
    if resolved_total:
        result.warnings.append(
            f"{resolved_total} out-of-sequence contradiction(s) "
            "disappeared between revisions — logic or recorded actuals "
            "were changed after the fact; cross-check those links in the "
            "revision comparison's change log.")
    return result


# --------------------------------------------------------------------------- #
# As-built logic repair -> revised .xer
# --------------------------------------------------------------------------- #

@dataclass
class RepairItem:
    """One TASKPRED edit the recorded actuals evidence."""

    pred_code: str
    succ_code: str
    old_link: str                 # e.g. "FS +0.0d"
    new_type: str                 # "PR_SS" / "PR_SF"
    new_lag_days_cal: float       # observed calendar-day offset
    new_lag_hr: float             # converted at the successor's calendar
    basis: str
    apply: bool = True
    blocked: str = ""             # non-empty = cannot be applied (e.g. the
    #                               pair already carries a link of the
    #                               target type — P6 bars duplicates)


@dataclass
class RepairReport:
    source_sha256: str = ""
    output_sha256: str = ""
    applied: list[RepairItem] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)   # "P -FS-> S"
    rel_count_before: int = 0
    rel_count_after: int = 0
    qa_passed: bool = False
    qa_notes: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


_TYPE_CODE = {"FS": "PR_FS", "SS": "PR_SS", "FF": "PR_FF", "SF": "PR_SF"}


def build_repair_plan(
    data: XerData,
    flags: list[OutOfSequenceFlag] | None = None,
    *,
    config: DCMAConfig | None = None,
) -> list[RepairItem]:
    """Concrete as-built fits as an analyst-editable repair plan.

    'Review'-class flags are excluded by design (see REPAIR_CAVEATS)."""
    config = config or DCMAConfig()
    if flags is None:
        flags = out_of_sequence_flags(data)
    by_code = {t.task_code: t for t in data.tasks if not t.is_loe_or_wbs}
    existing = {(r.pred_task_id, r.task_id, r.pred_type)
                for r in data.relationships}
    plan: list[RepairItem] = []
    for f in flags:
        if f.rec_link_type in ("", "review") or f.rec_lag_days is None:
            continue
        succ = by_code.get(f.succ_code)
        pred = by_code.get(f.pred_code)
        if succ is None or pred is None:
            continue
        # the existing relationship, for the old-link display
        old_lag = 0.0
        for rel in data.relationships:
            if (rel.pred_task_id == pred.task_id
                    and rel.task_id == succ.task_id
                    and rel.pred_type == _TYPE_CODE.get(f.link_type)):
                hpd_p = data.hours_per_day(pred, config)
                old_lag = round(rel.lag_hr / hpd_p, 1) if rel.lag_hr else 0.0
                break
        hpd = data.hours_per_day(succ, config)
        new_type = _TYPE_CODE[f.rec_link_type]
        blocked = ""
        if (pred.task_id, succ.task_id, new_type) in existing:
            blocked = (f"the pair already carries a {f.rec_link_type} "
                       "link — converting would duplicate it, which P6 "
                       "bars; analyst to resolve (e.g. delete the "
                       "contradicted link in P6)")
        plan.append(RepairItem(
            pred_code=f.pred_code,
            succ_code=f.succ_code,
            old_link=f"{f.link_type} {old_lag:+.1f}d",
            new_type=new_type,
            new_lag_days_cal=f.rec_lag_days,
            new_lag_hr=round(f.rec_lag_days * hpd, 1),
            basis=f.rec_basis,
            apply=not blocked,
            blocked=blocked,
        ))
    return plan


def apply_asbuilt_repairs(
    raw_text: str | bytes,
    data: XerData,
    repairs: list[RepairItem],
) -> tuple[str, RepairReport]:
    """Write a repaired COPY of the .xer with the selected TASKPRED rows
    re-typed and re-lagged. Rows are edited in place; every other byte
    of the file is preserved (bytes input is decoded latin-1, a lossless
    byte<->str mapping, so re-encoding latin-1 reproduces the source
    byte-for-byte outside the edited fields). Round-trip QA re-parses
    the output."""
    report = RepairReport(caveats=list(REPAIR_CAVEATS + OOS_CAVEATS))
    if isinstance(raw_text, (bytes, bytearray)):
        report.source_sha256 = hashlib.sha256(raw_text).hexdigest()
        raw_text = bytes(raw_text).decode("latin-1")
    else:
        # Hash the source with the SAME lossless latin-1 encoding used for
        # the output, so an all-unselected repair round-trips byte-exact.
        report.source_sha256 = hashlib.sha256(
            raw_text.encode("latin-1", "replace")).hexdigest()
    report.rel_count_before = len(data.relationships)

    selected = [r for r in repairs if r.apply and not r.blocked]
    code_to_id = {t.task_code: t.task_id for t in data.tasks}
    # (pred_task_id, succ_task_id, old_pred_type) -> RepairItem
    wanted: dict[tuple, RepairItem] = {}
    for r in selected:
        old_type = _TYPE_CODE.get(r.old_link.split()[0], "PR_FS")
        key = (code_to_id.get(r.pred_code, ""),
               code_to_id.get(r.succ_code, ""), old_type)
        wanted[key] = r

    lines = raw_text.split("\n")
    in_pred = False
    fields: list[str] = []
    idx_pred = idx_task = idx_type = idx_lag = -1
    applied_keys: set = set()
    for i, line in enumerate(lines):
        if line.startswith("%T\t"):
            in_pred = line.split("\t")[1].strip() == "TASKPRED"
            continue
        if in_pred and line.startswith("%F\t"):
            fields = [x.strip() for x in line.split("\t")[1:]]
            def _ix(name: str) -> int:
                return fields.index(name) if name in fields else -1
            idx_pred = _ix("pred_task_id")
            idx_task = _ix("task_id")
            idx_type = _ix("pred_type")
            idx_lag = _ix("lag_hr_cnt")
            continue
        if not (in_pred and line.startswith("%R\t")):
            continue
        vals = line.split("\t")[1:]
        if min(idx_pred, idx_task, idx_type) < 0:
            break
        if len(vals) <= max(idx_pred, idx_task, idx_type):
            continue
        key = (vals[idx_pred].strip(), vals[idx_task].strip(),
               vals[idx_type].strip())
        r = wanted.get(key)
        if r is None or key in applied_keys:
            continue
        vals[idx_type] = r.new_type
        if 0 <= idx_lag < len(vals):
            vals[idx_lag] = f"{r.new_lag_hr:g}"
        lines[i] = "%R\t" + "\t".join(vals)
        applied_keys.add(key)
        report.applied.append(r)

    for r in selected:
        old_type = _TYPE_CODE.get(r.old_link.split()[0], "PR_FS")
        key = (code_to_id.get(r.pred_code, ""),
               code_to_id.get(r.succ_code, ""), old_type)
        if key not in applied_keys:
            report.not_found.append(
                f"{r.pred_code} -{r.old_link.split()[0]}-> {r.succ_code}")

    out_text = "\n".join(lines)
    report.output_sha256 = hashlib.sha256(
        out_text.encode("latin-1", "replace")).hexdigest()

    # --- round-trip QA ---------------------------------------------------
    try:
        reparsed = parse_xer(out_text)
        report.rel_count_after = len(reparsed.relationships)
        id_pairs: dict[tuple, list] = {}
        for rel in reparsed.relationships:
            id_pairs.setdefault(
                (rel.pred_task_id, rel.task_id, rel.pred_type),
                []).append(rel)
        ok = report.rel_count_after == report.rel_count_before
        if not ok:
            report.qa_notes.append(
                f"relationship count changed: {report.rel_count_before} "
                f"-> {report.rel_count_after}")
        for r in report.applied:
            key = (code_to_id.get(r.pred_code, ""),
                   code_to_id.get(r.succ_code, ""), r.new_type)
            cands = id_pairs.get(key, [])
            if not cands:
                ok = False
                report.qa_notes.append(
                    f"repaired link {r.pred_code} -> {r.succ_code} not "
                    f"found as {r.new_type} after re-parse")
            elif not any(abs((c.lag_hr or 0.0) - r.new_lag_hr) <= 0.51
                         for c in cands):
                ok = False
                report.qa_notes.append(
                    f"lag mismatch on {r.pred_code} -> {r.succ_code}: "
                    f"{[c.lag_hr for c in cands]} vs {r.new_lag_hr}")
        if len(reparsed.tasks) != len(data.tasks):
            ok = False
            report.qa_notes.append("task count changed")
        report.qa_passed = ok
    except Exception as exc:                      # noqa: BLE001
        report.qa_passed = False
        report.qa_notes.append(f"re-parse failed: {exc}")
    return out_text, report
