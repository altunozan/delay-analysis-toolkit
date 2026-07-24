"""Module 6b — Comparison Impact & Materiality Screening.

Elevates the descriptive revision diff (Module 6) from "what changed" to
"which changes deserve attention". Three layers, all deterministic:

1. **Criticality tagging** — every change is placed relative to the
   driving longest path of each revision (critical / near-critical /
   off-path / completed / absent), with the activity's total float in the
   later revision alongside.
2. **Materiality ranking** — one cross-category ranked list under a
   disclosed screening score (path position + magnitude + forensic
   red-flag bonus). The rank orders changes for analyst attention; it is
   a SCREENING, not a causation finding.
3. **Out-of-sequence screening** — actualised progress in the later
   revision that contradicts the network logic (work recorded as started
   or finished before its predecessor allowed).

`build_provenance` runs the pairwise diff across a whole revision set so
each category of change is attributed to the update window that
introduced it — the forensic timeline of programme change.

Pure engines: XerData in, structured results out. No LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from dcma.config import DCMAConfig
from dcma.xer_parser import XerData

from .comparison import ComparisonResult, compare_revisions
from .critical_path import extract_longest_path

IMPACT_CAVEATS = [
    "The materiality rank is a deterministic SCREENING: changes are "
    "ordered by path position (critical / near-critical / off-path), "
    "magnitude in days, and a red-flag bonus for retrospective actual-"
    "date changes and constraint changes. It prioritises analyst "
    "attention; it does not assert that any single change caused the "
    "completion movement.",
    "Path position comes from a backward driving-logic (longest path) "
    "trace of each revision from its latest incomplete finisher (or the "
    "selected end activity); completed activities cannot carry a path "
    "band and are tagged 'completed'.",
    "Completion movement between the revisions is reported in calendar "
    "days between the two files' scheduled finish dates as submitted.",
]

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

PROVENANCE_CAVEATS = [
    "Provenance attributes each change to the update window (pair of "
    "consecutive revisions by data date) in which it first appears. A "
    "change made and reversed within one window is invisible to this "
    "screening.",
]

# Screening weights — disclosed in IMPACT_CAVEATS and kept simple on
# purpose: the score must be explainable in one sentence under
# cross-examination.
_BAND_WEIGHT = {"critical": 100.0, "near-critical": 50.0, "off-path": 10.0,
                "completed": 0.0, "absent": 0.0}
_RED_FLAG_BONUS = {"Actual dates changed retrospectively": 40.0,
                   "Constraint changes": 15.0}
_MAGNITUDE_CAP_DAYS = 60.0


@dataclass
class RankedChange:
    """One change from the revision diff, tagged and scored."""

    category: str
    ref: str                      # activity ID or "P -FS-> S"
    name: str
    detail: str                   # "old -> new"
    delta_days: float | None
    band_old: str                 # critical | near-critical | off-path |
    band_new: str                 # completed | absent
    total_float_new: float | None
    score: float
    red_flag: bool = False

    @property
    def band(self) -> str:
        """Worst (most critical) band across the two revisions."""
        order = ["critical", "near-critical", "off-path", "completed",
                 "absent"]
        for b in order:
            if self.band_old == b or self.band_new == b:
                return b
        return "absent"


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
    rec_link_type: str = ""       # "SS" / "FF" for a concrete as-built
    #                               fit; "review" where the analyst must
    #                               decide (reversed order / thin actuals)
    rec_lag_days: float | None = None   # calendar-day lag of a concrete fit
    rec_link: str = ""            # display form, e.g. "SS +12d" / "review"
    rec_basis: str = ""           # the dates the recommendation rests on


@dataclass
class ComparisonImpact:
    old_label: str
    new_label: str
    end_old: str | None = None    # longest-path trace terminals
    end_new: str | None = None
    completion_moved_days: float | None = None
    ranked: list[RankedChange] = field(default_factory=list)
    oos_flags: list[OutOfSequenceFlag] = field(default_factory=list)
    band_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    @property
    def critical_changes(self) -> list[RankedChange]:
        return [c for c in self.ranked if c.band == "critical"]


@dataclass
class ProvenanceWindow:
    """One consecutive revision pair in the set."""

    old_label: str
    new_label: str
    old_data_date: datetime | None
    new_data_date: datetime | None
    completion_moved_days: float | None
    counts: dict[str, int]                # category -> count
    red_flag_count: int                   # retrospective actual changes
    comparison: ComparisonResult


@dataclass
class ProvenanceResult:
    windows: list[ProvenanceWindow] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Criticality bands per revision
# --------------------------------------------------------------------------- #

def _bands(
    data: XerData,
    label: str,
    *,
    end_task_code: str | None,
    near_critical_days: float,
    config: DCMAConfig,
) -> tuple[dict[str, str], dict[str, float], str | None]:
    """code -> band, code -> total float, trace terminal for one revision."""
    lp = extract_longest_path(
        data, label, end_task_code=end_task_code,
        near_critical_days=near_critical_days, config=config)
    bands: dict[str, str] = {}
    floats: dict[str, float] = {}
    for a in lp.activities:
        bands[a.task_code] = a.band       # critical | near-critical
        if a.total_float_days is not None:
            floats[a.task_code] = a.total_float_days
    for t in data.tasks:
        if t.is_loe_or_wbs or t.task_code in bands:
            continue
        bands[t.task_code] = "completed" if t.is_complete else "off-path"
    return bands, floats, lp.end_choice


def _band_of(code: str, bands: dict[str, str]) -> str:
    return bands.get(code, "absent")


def _link_band(pred: str, succ: str, bands: dict[str, str]) -> str:
    order = ["critical", "near-critical", "off-path", "completed", "absent"]
    bp, bs = _band_of(pred, bands), _band_of(succ, bands)
    return bp if order.index(bp) <= order.index(bs) else bs


def _split_lag_ref(ref: str) -> tuple[str, str] | None:
    """Parse 'P -FS-> S' back into (P, S); None if the shape is off."""
    if " -" in ref and "-> " in ref:
        pred = ref.split(" -")[0].strip()
        succ = ref.rsplit("-> ", 1)[1].strip()
        if pred and succ:
            return pred, succ
    return None


# --------------------------------------------------------------------------- #
# Out-of-sequence screening (single revision)
# --------------------------------------------------------------------------- #

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
# Out-of-sequence evolution across the revision set
# --------------------------------------------------------------------------- #

OOS_EVOLUTION_CAVEATS = [
    "A flag 'resolved' in a window means the contradiction is no longer "
    "present in the later file — because the logic was changed, the "
    "actual dates were changed, or the activity was removed. Resolution "
    "is therefore itself a change worth cross-checking in the revision "
    "comparison, not automatically good news.",
]


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
# Impact assessment
# --------------------------------------------------------------------------- #

def assess_comparison_impact(
    old: XerData,
    new: XerData,
    old_label: str,
    new_label: str,
    *,
    comparison: ComparisonResult | None = None,
    end_task_code: str | None = None,
    near_critical_days: float = 10.0,
    config: DCMAConfig | None = None,
) -> ComparisonImpact:
    """Tag, score and rank the changes between two revisions."""
    config = config or DCMAConfig()
    cmp = comparison or compare_revisions(old, new, old_label, new_label,
                                          config=config)
    result = ComparisonImpact(old_label=old_label, new_label=new_label)
    result.caveats.extend(IMPACT_CAVEATS + OOS_CAVEATS)

    bands_old, _fl_old, result.end_old = _bands(
        old, old_label, end_task_code=end_task_code,
        near_critical_days=near_critical_days, config=config)
    bands_new, floats_new, result.end_new = _bands(
        new, new_label, end_task_code=end_task_code,
        near_critical_days=near_critical_days, config=config)

    if cmp.old_finish and cmp.new_finish:
        result.completion_moved_days = round(
            (cmp.new_finish - cmp.old_finish).total_seconds() / 86400, 1)

    def score(category: str, band_old: str, band_new: str,
              delta: float | None) -> tuple[float, bool]:
        band_w = max(_BAND_WEIGHT.get(band_old, 0.0),
                     _BAND_WEIGHT.get(band_new, 0.0))
        mag = min(abs(delta or 0.0), _MAGNITUDE_CAP_DAYS)
        bonus = _RED_FLAG_BONUS.get(category, 0.0)
        return band_w + mag + bonus, bonus > 0 or category.startswith(
            "Actual")

    def add(category: str, ref: str, name: str, detail: str,
            delta: float | None, band_old: str, band_new: str) -> None:
        s, flag = score(category, band_old, band_new, delta)
        result.ranked.append(RankedChange(
            category=category, ref=ref, name=name, detail=detail,
            delta_days=delta, band_old=band_old, band_new=band_new,
            total_float_new=floats_new.get(ref), score=round(s, 1),
            red_flag=flag))

    # --- per-activity field changes --------------------------------------
    field_cats = [
        ("Duration changes", cmp.duration_changes),
        ("Constraint changes", cmp.constraint_changes),
        ("Calendar reassignments", cmp.calendar_changes),
        ("Actual dates changed retrospectively", cmp.actual_date_changes),
    ]
    for cat, changes in field_cats:
        for c in changes:
            add(cat, c.task_code, c.name,
                f"{c.old_value} -> {c.new_value}", c.delta_days,
                _band_of(c.task_code, bands_old),
                _band_of(c.task_code, bands_new))

    # --- lag changes (ref is "P -FS-> S") --------------------------------
    for c in cmp.lag_changes:
        pair = _split_lag_ref(c.task_code)
        if pair:
            bo = _link_band(pair[0], pair[1], bands_old)
            bn = _link_band(pair[0], pair[1], bands_new)
        else:
            bo = bn = "off-path"
        add("Lag changes", c.task_code, c.name,
            f"{c.old_value} -> {c.new_value}", c.delta_days, bo, bn)

    # --- logic add / remove ----------------------------------------------
    for lk in cmp.logic_added:
        add("Logic added", f"{lk.pred_code} -{lk.link_type}-> {lk.succ_code}",
            lk.succ_name, f"new {lk.link_type} link ({lk.lag_days:+.1f}d lag)",
            None, _link_band(lk.pred_code, lk.succ_code, bands_old),
            _link_band(lk.pred_code, lk.succ_code, bands_new))
    for lk in cmp.logic_removed:
        add("Logic removed",
            f"{lk.pred_code} -{lk.link_type}-> {lk.succ_code}",
            lk.succ_name, f"{lk.link_type} link removed", None,
            _link_band(lk.pred_code, lk.succ_code, bands_old),
            _link_band(lk.pred_code, lk.succ_code, bands_new))

    # --- added / deleted activities --------------------------------------
    for a in cmp.added:
        add("Activities added", a.task_code, a.name,
            f"added ({a.duration_days or 0:.0f}d)", None,
            "absent", _band_of(a.task_code, bands_new))
    for a in cmp.deleted:
        add("Activities deleted", a.task_code, a.name,
            f"deleted ({a.duration_days or 0:.0f}d)", None,
            _band_of(a.task_code, bands_old), "absent")

    result.ranked.sort(key=lambda c: -c.score)

    # --- band counts + out-of-sequence -----------------------------------
    for c in result.ranked:
        result.band_counts[c.band] = result.band_counts.get(c.band, 0) + 1
    result.oos_flags = out_of_sequence_flags(new)
    # Rank the flags by criticality of the link in the later revision,
    # then by overlap size — 1,000 raw flags are unusable; the handful on
    # the driving path are what the analyst screens first.
    _order = ["critical", "near-critical", "off-path", "completed",
              "absent"]
    for f in result.oos_flags:
        f.band = _link_band(f.pred_code, f.succ_code, bands_new)
    result.oos_flags.sort(
        key=lambda f: (_order.index(f.band),
                       -(f.overlap_days
                         if f.overlap_days is not None else -1.0)))

    # --- diagnostics ------------------------------------------------------
    crit = result.critical_changes
    if crit and result.completion_moved_days is not None:
        top = crit[:5]
        result.warnings.append(
            f"{len(crit)} change(s) sit on or beside the driving path "
            f"while scheduled completion moved "
            f"{result.completion_moved_days:+.0f} calendar days this "
            "window. Highest-ranked: "
            + "; ".join(f"{c.ref} ({c.category.lower()}: {c.detail})"
                        for c in top) + ".")
    elif not crit and (result.completion_moved_days or 0) > 0:
        result.warnings.append(
            "Completion moved without any detected change on the driving "
            "path — the movement is likely pure progress slippage rather "
            "than programme editing (confirm with the windows module).")
    if result.oos_flags:
        n_path = sum(1 for f in result.oos_flags
                     if f.band in ("critical", "near-critical"))
        result.warnings.append(
            f"{len(result.oos_flags)} out-of-sequence progress record(s) "
            f"in '{new_label}' — recorded actuals contradict the network "
            "logic at these links; the as-recorded sequence, not the "
            "planned logic, governed there."
            + (f" {n_path} sit on or near the driving path — screen "
               "those first; the flags are ranked accordingly."
               if n_path else ""))
    return result


# --------------------------------------------------------------------------- #
# Multi-revision provenance
# --------------------------------------------------------------------------- #

def build_provenance(
    files: list[tuple[str, XerData]],
    *,
    config: DCMAConfig | None = None,
) -> ProvenanceResult:
    """Attribute change to the update window that introduced it.

    ``files`` — (label, XerData) pairs; sorted here by data date so the
    caller may pass them in any order.
    """
    config = config or DCMAConfig()
    result = ProvenanceResult()
    result.caveats.extend(PROVENANCE_CAVEATS)

    def dd(item: tuple[str, XerData]) -> datetime:
        proj = item[1].project
        return (proj.data_date if proj and proj.data_date
                else datetime.max)

    ordered = sorted(files, key=dd)
    if len(ordered) < 3:
        result.warnings.append(
            "Provenance needs at least three revisions (two windows); "
            "with two, the pairwise comparison already tells the story.")
    if len(ordered) < 2:
        return result

    for (l0, d0), (l1, d1) in zip(ordered, ordered[1:]):
        cmp = compare_revisions(d0, d1, l0, l1, config=config)
        moved = None
        if cmp.old_finish and cmp.new_finish:
            moved = round((cmp.new_finish
                           - cmp.old_finish).total_seconds() / 86400, 1)
        counts = {k: v for k, v in cmp.category_counts.items()}
        result.windows.append(ProvenanceWindow(
            old_label=l0, new_label=l1,
            old_data_date=cmp.old_data_date,
            new_data_date=cmp.new_data_date,
            completion_moved_days=moved,
            counts=counts,
            red_flag_count=len(cmp.actual_date_changes),
            comparison=cmp))
    if result.windows:
        result.categories = list(result.windows[0].counts.keys())

    # --- diagnostics: where did the damage and the editing concentrate? --
    with_move = [w for w in result.windows
                 if w.completion_moved_days is not None]
    if with_move:
        worst = max(with_move, key=lambda w: w.completion_moved_days or 0)
        if (worst.completion_moved_days or 0) > 0:
            result.warnings.append(
                f"Largest completion movement: {worst.old_label} -> "
                f"{worst.new_label} "
                f"({worst.completion_moved_days:+.0f} calendar days).")
    flagged = [w for w in result.windows if w.red_flag_count]
    if flagged:
        result.warnings.append(
            "Retrospective actual-date changes first appear in window "
            f"{flagged[0].old_label} -> {flagged[0].new_label} and occur "
            f"in {len(flagged)} of {len(result.windows)} window(s) — "
            "these windows deserve the closest scrutiny.")
    return result
