"""Comparison Impact & Materiality Screening.

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
from .oos import OOS_CAVEATS, OutOfSequenceFlag, out_of_sequence_flags

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
                   "Calendar definitions changed": 40.0,
                   "Scheduling options changed": 40.0,
                   "Constraint changes": 15.0,
                   "Calendar reassignments": 15.0}
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
):
    """(code -> band, code -> total float, lp result) for one revision."""
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
    return bands, floats, lp


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

    bands_old, _fl_old, _lp_old = _bands(
        old, old_label, end_task_code=end_task_code,
        near_critical_days=near_critical_days, config=config)
    bands_new, floats_new, _lp_new = _bands(
        new, new_label, end_task_code=end_task_code,
        near_critical_days=near_critical_days, config=config)
    result.end_old, result.end_new = _lp_old.end_choice, _lp_new.end_choice
    # the longest-path extraction warns when it falls back from the
    # elected terminal — those warnings must reach the reader, or a
    # fallback path is silently presented as target-anchored
    for _lbl, _lp in ((old_label, _lp_old), (new_label, _lp_new)):
        for _w in _lp.warnings:
            result.warnings.append(f"{_lbl}: {_w}")

    if end_task_code:
        # the headline answers the ELECTED obligation: that activity's
        # stored finish in each revision — never the PROJECT scheduled
        # finish, which can describe a different endpoint entirely
        def _stored_fin(d):
            t = next((x for x in d.tasks
                      if x.task_code == end_task_code), None)
            return (t.act_finish or t.early_finish) if t else None

        _f_old, _f_new = _stored_fin(old), _stored_fin(new)
        if _f_old and _f_new:
            result.completion_moved_days = round(
                (_f_new - _f_old).total_seconds() / 86400, 1)
        else:
            _side = "earlier" if not _f_old else "later"
            result.warnings.append(
                f"HEADLINE GATED: elected milestone '{end_task_code}' "
                f"has no stored finish in the {_side} revision — "
                "completion movement is not reported (the project "
                "scheduled finish is a different obligation and is not "
                "substituted).")
    elif cmp.old_finish and cmp.new_finish:
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
    # Calendar-definition edits are programme-level (the ref is a calendar,
    # not an activity): no path band applies, but the red-flag bonus alone
    # pushes them up the rank where they belong.
    for c in cmp.calendar_def_changes:
        add("Calendar definitions changed", c.task_code, c.name,
            f"{c.old_value} -> {c.new_value}", None, "absent", "absent")
    for c in cmp.sched_options_changes:
        add("Scheduling options changed", c.task_code, c.name,
            f"{c.old_value} -> {c.new_value}", None, "absent", "absent")
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


# --------------------------------------------------------------------------- #
# Completion impact attribution — one change at a time, re-scheduled
# --------------------------------------------------------------------------- #

ATTRIBUTION_CAVEATS = [
    "Each change is tested ONE AT A TIME: the later revision is "
    "re-scheduled by the toolkit's simplified CPM kernel with that "
    "single change reverted, and the completion delta is that change's "
    "contribution. Every OTHER change stays in place during the test, "
    "so contributions interact and need not sum to the total movement.",
    "Contributions are KERNEL-vs-KERNEL deltas (the same simplified "
    "engine schedules both runs). Never compare a kernel date with a "
    "P6 file date — the kernel's own baseline completion is disclosed "
    "so every figure is a like-for-like delta.",
    "Revertible categories: lag changes, logic added / removed, "
    "duration changes, START-side constraint changes (the kernel "
    "models start floors; finish-side and late constraints are "
    "reported, not modelled), calendar reassignments, and scope "
    "(activities added — removed from the network; activities deleted "
    "— reinstated with their former duration, calendar and logic where "
    "they were incomplete in the earlier revision). Calendar-definition "
    "edits, scheduling-option changes and retrospective actual-date "
    "changes are ranked by the screening but NOT re-scheduled — their "
    "influence is screened, not measured.",
    "Alongside the one-at-a-time tests, ALL revertible changes are "
    "reverted TOGETHER in a single run: that combined figure is the "
    "measured effect of programme editing, and the remainder of the "
    "completion movement is progress performance plus the categories "
    "listed above as not re-scheduled.",
    "Completion is measured at the elected contractual milestone where "
    "it exists in the remaining network, otherwise at the network's "
    "latest early finish.",
]


@dataclass
class AttributedChange:
    """One change with its measured completion contribution."""

    category: str
    ref: str
    name: str
    detail: str
    band: str
    screen_score: float | None
    completion_with: datetime | None      # kernel, change in place
    completion_without: datetime | None   # kernel, change reverted
    contribution_days: float | None       # with - without; +ve = pushed later
    tested: bool = True
    note: str = ""


@dataclass
class CompletionAttribution:
    old_label: str
    new_label: str
    anchor_code: str | None = None
    kernel_completion_old: datetime | None = None
    kernel_completion_new: datetime | None = None
    kernel_moved_days: float | None = None
    changes: list[AttributedChange] = field(default_factory=list)
    # all revertible changes undone TOGETHER — the measured effect of
    # programme editing, as distinct from progress performance
    completion_no_edits: datetime | None = None
    editing_effect_days: float | None = None
    # the chain that actually governs completion in the later revision
    driving_chain: list[dict] = field(default_factory=list)
    chain_root_at_data_date: bool = False
    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    @property
    def tested_changes(self) -> list[AttributedChange]:
        return [c for c in self.changes if c.tested]

    @property
    def residual_days(self) -> float | None:
        """Movement NOT explained by programme editing: progress
        performance plus the categories the kernel cannot re-schedule."""
        if (self.kernel_moved_days is None
                or self.editing_effect_days is None):
            return None
        return round(self.kernel_moved_days - self.editing_effect_days, 1)


def attribute_completion_impact(
    old: XerData,
    new: XerData,
    old_label: str,
    new_label: str,
    *,
    comparison: ComparisonResult | None = None,
    impact: ComparisonImpact | None = None,
    end_task_code: str | None = None,
    max_tests: int = 25,
    config: DCMAConfig | None = None,
) -> CompletionAttribution:
    """Which changes actually moved completion, measured by reversion.

    For each revertible change the later revision's remaining network is
    re-scheduled with that single change undone; the completion delta is
    the change's contribution (+ve = the change pushed completion later,
    -ve = it pulled completion earlier). Candidates are taken in the
    screening's materiality order and capped at ``max_tests``.
    """
    from .cpm import (REL_TO_SHORT, START_FLOOR_CSTR, build_network,
                      calendar_masks, forward_pass, parse_xer_date)

    config = config or DCMAConfig()
    cmp = comparison or compare_revisions(old, new, old_label, new_label,
                                          config=config)
    result = CompletionAttribution(old_label=old_label,
                                   new_label=new_label)
    result.caveats.extend(ATTRIBUTION_CAVEATS)

    dd_new = (new.project.data_date if new.project
              and new.project.data_date else datetime.now())
    dd_old = (old.project.data_date if old.project
              and old.project.data_date else dd_new)
    inc, nodes, preds, started, _masks, warns = build_network(
        new, config, dd_new)
    result.warnings.extend(warns)
    if not nodes:
        result.warnings.append(
            "No remaining (incomplete) activities in the later revision "
            "— nothing to re-schedule.")
        return result

    def completion(EF: dict) -> datetime | None:
        """The measured endpoint of ONE run.

        When a contractual target is elected, it is the ONLY endpoint —
        a run where it cannot be measured returns None and the affected
        quantum is BLOCKED with a warning, never silently substituted
        with the network maximum (which would subtract two different
        obligations and report the difference as completion movement).
        """
        if end_task_code:
            return EF.get(end_task_code)
        return max(EF.values()) if EF else None

    result.anchor_code = (end_task_code
                          if end_task_code and end_task_code in nodes
                          else None)
    ES0, EF0, _, driver0 = forward_pass(nodes, preds, dd_new, started)
    base = completion(EF0)
    result.kernel_completion_new = base
    if end_task_code and base is None:
        result.warnings.append(
            f"ATTRIBUTION GATED: the elected completion milestone "
            f"'{end_task_code}' is not in the later revision's remaining "
            "network (complete, absent, or disconnected) — kernel "
            "attribution is not measured rather than re-anchored to the "
            "latest finisher.")
        return result

    o_inc, o_nodes, o_preds, o_started, _m, _w = build_network(
        old, config, dd_old)
    if o_nodes:
        _, o_EF, _, _ = forward_pass(o_nodes, o_preds, dd_old, o_started)
        result.kernel_completion_old = completion(o_EF)
        if end_task_code and result.kernel_completion_old is None:
            result.warnings.append(
                f"Kernel movement not reported: elected milestone "
                f"'{end_task_code}' is not in the earlier revision's "
                "remaining network — the two runs would measure "
                "different obligations.")
    if result.kernel_completion_old and base:
        result.kernel_moved_days = round(
            (base - result.kernel_completion_old).total_seconds() / 86400,
            1)

    # screening order decides which changes are worth a kernel run
    score_of: dict[tuple[str, str], float] = {}
    band_of: dict[tuple[str, str], str] = {}
    for rc in (impact.ranked if impact is not None else []):
        score_of[(rc.category, rc.ref)] = rc.score
        band_of[(rc.category, rc.ref)] = rc.band

    # ---- candidate build: (category, ref, name, detail, apply, undo) --
    cands: list[tuple] = []

    def _find_pred(succ: str, pred: str) -> int | None:
        for i, (p, _lt, _lg) in enumerate(preds.get(succ, [])):
            if p == pred:
                return i
        return None

    for c in cmp.lag_changes:
        pair = _split_lag_ref(c.task_code)
        if not pair or c.delta_days is None:
            continue
        s_, p_ = pair[1], pair[0]

        def mk_lag(s=s_, p=p_, delta=c.delta_days):
            idx = _find_pred(s, p)
            if idx is None:
                return None
            cur = preds[s][idx]
            old_t = cur
            preds[s][idx] = (cur[0], cur[1], cur[2] - delta)

            def undo():
                preds[s][idx] = old_t
            return undo
        cands.append(("Lag changes", c.task_code, c.name,
                      f"{c.old_value} -> {c.new_value}", mk_lag))

    for lk in cmp.logic_added:
        ref = f"{lk.pred_code} -{lk.link_type}-> {lk.succ_code}"

        def mk_del(s=lk.succ_code, p=lk.pred_code):
            idx = _find_pred(s, p)
            if idx is None:
                return None
            old_t = preds[s][idx]
            del preds[s][idx]

            def undo():
                preds[s].insert(idx, old_t)
            return undo
        cands.append(("Logic added", ref, lk.succ_name,
                      f"revert = remove the new {lk.link_type} link",
                      mk_del))

    for lk in cmp.logic_removed:
        ref = f"{lk.pred_code} -{lk.link_type}-> {lk.succ_code}"

        def mk_add(s=lk.succ_code, p=lk.pred_code, lt=lk.link_type,
                   lg=lk.lag_days):
            if s not in preds or p not in nodes:
                return None
            preds[s].append((p, lt, lg))

            def undo():
                preds[s].pop()
            return undo
        cands.append(("Logic removed", ref, lk.succ_name,
                      f"revert = reinstate the {lk.link_type} link",
                      mk_add))

    for c in cmp.duration_changes:
        if c.delta_days is None:
            continue

        def mk_dur(code=c.task_code, delta=c.delta_days):
            if code not in nodes:
                return None
            old_t = nodes[code]
            nodes[code] = (max(old_t[0] - delta, 0.0), old_t[1])

            def undo():
                nodes[code] = old_t
            return undo
        cands.append(("Duration changes", c.task_code, c.name,
                      f"{c.old_value} -> {c.new_value}", mk_dur))

    # ---- constraint changes: the kernel models START floors --------
    old_by_code = {t.task_code: t for t in old.tasks if not t.is_loe_or_wbs}
    new_by_code = {t.task_code: t for t in new.tasks if not t.is_loe_or_wbs}

    def _floor_from(t) -> datetime | None:
        """Early-start floor a task's own constraints would impose."""
        best = None
        for ctype, cdate in ((t.cstr_type, t.cstr_date),
                             (t.cstr_type2, t.cstr_date2)):
            if (ctype or "").strip() in START_FLOOR_CSTR and cdate:
                best = cdate if best is None else max(best, cdate)
        return best

    for c in cmp.constraint_changes:
        def mk_cstr(code=c.task_code):
            if code not in nodes:
                return None
            o_t = old_by_code.get(code)
            if o_t is None:
                return None
            had = code in started
            prev = started.get(code)
            # in-progress work is floored at the data date regardless
            base = dd_new if (new_by_code.get(code) is not None
                              and new_by_code[code].act_start
                              is not None) else None
            old_floor = _floor_from(o_t)
            reverted = max([d for d in (base, old_floor)
                            if d is not None], default=None)
            if reverted is None:
                started.pop(code, None)
            else:
                started[code] = reverted

            def undo():
                if had:
                    started[code] = prev
                else:
                    started.pop(code, None)
            return undo
        cands.append(("Constraint changes", c.task_code, c.name,
                      f"{c.old_value} -> {c.new_value}", mk_cstr))

    # ---- calendar reassignments: swap the working mask back --------
    old_masks = calendar_masks(old)
    for c in cmp.calendar_changes:
        def mk_cal(code=c.task_code):
            if code not in nodes:
                return None
            o_t = old_by_code.get(code)
            if o_t is None:
                return None
            prev = nodes[code]
            nodes[code] = (prev[0], old_masks.get(o_t.clndr_id))

            def undo():
                nodes[code] = prev
            return undo
        cands.append(("Calendar reassignments", c.task_code, c.name,
                      f"{c.old_value} -> {c.new_value}", mk_cal))

    # ---- scope: added activities are REMOVED from the network ------
    for a in cmp.added:
        def mk_added(code=a.task_code):
            if code not in nodes:
                return None
            node_prev = nodes.pop(code)
            own_preds = preds.pop(code, None)
            start_prev = started.pop(code, None)
            touched = []
            for s, plist in preds.items():
                keep = [p for p in plist if p[0] != code]
                if len(keep) != len(plist):
                    touched.append((s, plist))
                    preds[s] = keep

            def undo():
                nodes[code] = node_prev
                if own_preds is not None:
                    preds[code] = own_preds
                if start_prev is not None:
                    started[code] = start_prev
                for s, plist in touched:
                    preds[s] = plist
            return undo
        cands.append(("Activities added", a.task_code, a.name,
                      f"revert = remove ({a.duration_days or 0:.0f}d) "
                      "from the network", mk_added))

    # ---- scope: deleted activities are REINSTATED ------------------
    o_code_of = {t.task_id: t.task_code for t in old.tasks}
    o_rels_by_succ: dict[str, list] = {}
    o_rels_by_pred: dict[str, list] = {}
    for r in old.relationships:
        p, s = o_code_of.get(r.pred_task_id), o_code_of.get(r.task_id)
        if p and s:
            o_rels_by_succ.setdefault(s, []).append((p, r))
            o_rels_by_pred.setdefault(p, []).append((s, r))

    for a in cmp.deleted:
        def mk_deleted(code=a.task_code):
            o_t = old_by_code.get(code)
            # only work that was still OUTSTANDING can be reinstated
            # into the remaining network; completed work was done
            if o_t is None or code in nodes or not o_t.is_incomplete:
                return None
            hpd = old.hours_per_day(o_t, config)
            rem = o_t.remaining_duration_days(hpd)
            if rem is None:
                rem = o_t.original_duration_days(hpd) or 0.0
            nodes[code] = (max(rem, 0.0), old_masks.get(o_t.clndr_id))
            mine = []
            for p, r in o_rels_by_succ.get(code, []):
                if p in nodes:
                    lag = (r.lag_hr / hpd) if r.lag_hr else 0.0
                    mine.append((p, REL_TO_SHORT.get(r.pred_type, "FS"),
                                 lag))
            preds[code] = mine
            added_to = []
            for s, r in o_rels_by_pred.get(code, []):
                if s in preds:
                    lag = (r.lag_hr / hpd) if r.lag_hr else 0.0
                    preds[s].append(
                        (code, REL_TO_SHORT.get(r.pred_type, "FS"), lag))
                    added_to.append(s)

            def undo():
                nodes.pop(code, None)
                preds.pop(code, None)
                for s in added_to:
                    preds[s] = [p for p in preds[s] if p[0] != code]
            return undo
        cands.append(("Activities deleted", a.task_code, a.name,
                      f"revert = reinstate "
                      f"({a.duration_days or 0:.0f}d) into the network",
                      mk_deleted))

    cands.sort(key=lambda x: -(score_of.get((x[0], x[1]), 0.0)))

    tested = 0
    for category, ref, name, detail, mk in cands:
        key = (category, ref)
        ac = AttributedChange(
            category=category, ref=ref, name=name, detail=detail,
            band=band_of.get(key, "?"),
            screen_score=score_of.get(key),
            completion_with=base, completion_without=None,
            contribution_days=None)
        if tested >= max_tests:
            ac.tested = False
            ac.note = f"beyond the {max_tests}-test cap (raise it to test)"
            result.changes.append(ac)
            continue
        undo = mk()
        if undo is None:
            ac.tested = False
            ac.note = ("not in the remaining network (completed side or "
                       "absent) — no re-schedule possible")
            result.changes.append(ac)
            continue
        try:
            _, EF1, _, _ = forward_pass(nodes, preds, dd_new, started)
            comp1 = completion(EF1)
        finally:
            undo()
        tested += 1
        ac.completion_without = comp1
        if base and comp1:
            ac.contribution_days = round(
                (base - comp1).total_seconds() / 86400, 1)
        elif end_task_code and comp1 is None:
            ac.note = (f"reverting this change removes '{end_task_code}' "
                       "from the remaining network — contribution gated, "
                       "not re-anchored")
        result.changes.append(ac)

    # ---- ALL revertible changes undone together -------------------
    # One-at-a-time contributions interact and cannot be summed; this
    # single run measures what programme EDITING did, leaving the
    # remainder to progress performance and the un-modelled categories.
    undos = []
    for category, ref, name, detail, mk in cands:
        u = mk()
        if u is not None:
            undos.append(u)
    if undos:
        try:
            _, EFa, _, _ = forward_pass(nodes, preds, dd_new, started)
            result.completion_no_edits = completion(EFa)
        finally:
            for u in reversed(undos):
                u()
        if base and result.completion_no_edits:
            result.editing_effect_days = round(
                (base - result.completion_no_edits).total_seconds()
                / 86400, 1)
        elif end_task_code and result.completion_no_edits is None:
            result.warnings.append(
                f"Editing effect gated: with every revertible change "
                f"undone, '{end_task_code}' leaves the remaining network "
                "— no editing-effect figure is reported.")

    result.changes.sort(
        key=lambda a: -abs(a.contribution_days or 0.0))

    # ---- what actually governs completion, and did it move? --------
    # Walking the kernel's own driving predecessors back from the
    # anchor answers "what pushes it later" directly: if the chain is
    # unchanged and rooted at the data date, nothing was EDITED into
    # the delay — the chain simply failed to progress and translated
    # forward by the window.
    anchor = (end_task_code if end_task_code and end_task_code in EF0
              else (max(EF0, key=lambda k: EF0[k]) if EF0 else None))
    o_dur = {c.task_code: c.delta_days for c in cmp.duration_changes}
    changed_links = {p for lk in (cmp.logic_added + cmp.logic_removed)
                     for p in (lk.pred_code, lk.succ_code)}
    changed_links |= {pair[1] for pair in
                      (_split_lag_ref(c.task_code)
                       for c in cmp.lag_changes) if pair}
    cur, seen_c, chain = anchor, set(), []
    while cur is not None and cur not in seen_c and len(chain) < 40:
        seen_c.add(cur)
        t = new_by_code.get(cur)
        chain.append({
            "code": cur,
            "name": (t.name if t is not None else ""),
            "duration_days": round(nodes[cur][0], 1) if cur in nodes
            else None,
            "at_data_date": cur in started,
            "duration_changed": cur in o_dur,
            "logic_changed": cur in changed_links,
        })
        cur = driver0.get(cur)
    result.driving_chain = chain
    result.chain_root_at_data_date = bool(chain
                                          and chain[-1]["at_data_date"])
    n_touched = sum(1 for c in chain
                    if c["duration_changed"] or c["logic_changed"])

    if result.editing_effect_days is not None:
        resid = result.residual_days
        result.warnings.append(
            f"Programme EDITING accounts for "
            f"{result.editing_effect_days:+.0f} calendar day(s) of the "
            f"movement (all {len(undos)} revertible changes undone "
            "together in one run)"
            + (f"; the remaining {resid:+.0f} day(s) are progress "
               "performance and the categories the kernel does not "
               "re-schedule (calendar definitions, scheduling options, "
               "retrospective actuals)." if resid is not None else "."))
    if chain:
        head = "; ".join(f"{c['code']} ({c['duration_days']:.0f}d)"
                         for c in chain[:5]
                         if c["duration_days"] is not None)
        if n_touched == 0 and result.chain_root_at_data_date:
            result.warnings.append(
                f"The chain governing {anchor} is UNCHANGED between "
                f"the revisions ({len(chain)} activities, none edited) "
                f"and is rooted at '{chain[-1]['code']}' sitting on the "
                "data date: the whole chain simply translated forward "
                "by the window. On this evidence the movement is "
                "non-progress on the driving chain, not programme "
                f"editing. Chain head: {head}.")
        else:
            result.warnings.append(
                f"The chain governing {anchor} runs {len(chain)} "
                f"activities deep; {n_touched} of them were edited "
                "between the revisions (duration or logic) — those are "
                f"where an edit could bite. Chain head: {head}.")

    movers = [a for a in result.tested_changes
              if abs(a.contribution_days or 0) >= 0.5]
    if movers:
        top = movers[0]
        result.warnings.append(
            f"{len(movers)} of {tested} tested change(s) move the "
            "kernel completion when individually reverted. Largest: "
            f"{top.ref} ({top.category.lower()}, {top.detail}) — "
            f"completion {top.completion_with:%d %b %Y} with the "
            f"change vs {top.completion_without:%d %b %Y} without it "
            f"({top.contribution_days:+.0f}d contribution).")
    elif tested:
        result.warnings.append(
            f"None of the {tested} tested change(s) moves the kernel "
            "completion by half a day or more when individually "
            "reverted — the movement this window is likely progress "
            "slippage or untested categories (constraints, calendars, "
            "scope), not the tested edits.")
    return result


# --------------------------------------------------------------------------- #
# Appendix tables — the complete record, for the Word report
# --------------------------------------------------------------------------- #

def comparison_appendix(
    cmp: ComparisonResult,
    impact: ComparisonImpact | None = None,
    attribution: CompletionAttribution | None = None,
    provenance: ProvenanceResult | None = None,
) -> list[tuple[str, list[dict]]]:
    """(title, rows) per table — every change in full.

    The narrative body carries only the top few rows per category, by
    materiality; this is the complete record appended to the same
    document so the reader never has to open a second file. Table
    shapes match the Excel workbook exactly.
    """
    def acts(refs):
        return [{"Activity ID": a.task_code, "Activity": a.name,
                 "Type": "Milestone" if a.is_milestone else "Task",
                 "Start": _d(a.start), "Finish": _d(a.finish),
                 "Duration (d)": a.duration_days} for a in refs]

    def fields(changes):
        return [{"Activity / Link": c.task_code, "Name": c.name,
                 "Was": c.old_value, "Now": c.new_value,
                 "Delta (d)": c.delta_days} for c in changes]

    def links(ls):
        return [{"Predecessor": lk.pred_code, "Pred name": lk.pred_name,
                 "Type": lk.link_type, "Successor": lk.succ_code,
                 "Succ name": lk.succ_name, "Lag (d)": lk.lag_days}
                for lk in ls]

    def _d(x):
        return f"{x:%Y-%m-%d}" if x else "—"

    out: list[tuple[str, list[dict]]] = []

    def add(title: str, rows: list[dict]) -> None:
        if rows:
            out.append((title, rows))

    # the forensic category leads the appendix, complete and untruncated
    add("Retrospective changes to actual dates (complete)",
        fields(cmp.actual_date_changes))
    add("Activities added", acts(cmp.added))
    add("Activities deleted", acts(cmp.deleted))
    add("Duration changes", fields(cmp.duration_changes))
    add("Logic added", links(cmp.logic_added))
    add("Logic removed", links(cmp.logic_removed))
    add("Lag changes", fields(cmp.lag_changes))
    add("Constraint changes", fields(cmp.constraint_changes))
    add("Calendar reassignments", fields(cmp.calendar_changes))
    add("Calendar definitions changed", fields(cmp.calendar_def_changes))
    add("Scheduling options changed", fields(cmp.sched_options_changes))
    add("Renamed activities", fields(cmp.renamed))

    if impact is not None:
        add("Materiality screening — full ranked list", [{
            "Score": rc.score, "Path position": rc.band,
            "Category": rc.category, "Activity / Link": rc.ref,
            "Name": rc.name, "Change": rc.detail,
            "Delta (d)": rc.delta_days, "TF now (d)": rc.total_float_new,
            "Red flag": "YES" if rc.red_flag else "",
        } for rc in impact.ranked])

    if attribution is not None:
        add("Completion attribution — every change tested", [{
            "Category": a.category, "Change": a.ref, "Name": a.name,
            "Detail": a.detail, "Band": a.band,
            "Completion WITH change": _d(a.completion_with),
            "Completion WITHOUT": _d(a.completion_without),
            "Contribution (d)": a.contribution_days,
            "Tested": "yes" if a.tested else "no", "Note": a.note,
        } for a in attribution.changes])
        add("Driving chain to completion", [{
            "#": i, "Activity ID": c["code"], "Activity": c["name"],
            "Remaining (d)": c["duration_days"],
            "Edited this window": ("duration" if c["duration_changed"]
                                   else "logic" if c["logic_changed"]
                                   else ""),
            "On the data date": "YES" if c["at_data_date"] else "",
        } for i, c in enumerate(attribution.driving_chain, start=1)])

    if provenance is not None and provenance.windows:
        add("Change provenance by update window", [
            {"Window": f"{w.old_label} -> {w.new_label}",
             "Completion moved (d)": w.completion_moved_days,
             "Retro actual changes": w.red_flag_count}
            | {cat: w.counts.get(cat, 0) for cat in provenance.categories}
            for w in provenance.windows])
    return out
