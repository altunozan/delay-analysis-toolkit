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
    # the two driving longest paths, for the summary comparison gantt
    lp_old: list[tuple[str, str]] = field(default_factory=list)
    lp_new: list[tuple[str, str]] = field(default_factory=list)
    lp_old_links: list[tuple[str, str]] = field(default_factory=list)
    lp_new_links: list[tuple[str, str]] = field(default_factory=list)
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
    result.lp_old = [(a.task_code, a.name) for a in _lp_old.critical]
    result.lp_new = [(a.task_code, a.name) for a in _lp_new.critical]
    result.lp_old_links = [(lk.pred_code, lk.succ_code)
                           for lk in _lp_old.links]
    result.lp_new_links = [(lk.pred_code, lk.succ_code)
                           for lk in _lp_new.links]

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
    "Revertible categories: lag changes, logic added / removed, and "
    "duration changes (remaining-duration approximation for "
    "in-progress work). Constraint, calendar, scope (added / deleted) "
    "and retrospective actual-date changes are ranked by the screening "
    "but are NOT re-scheduled here — their influence is screened, not "
    "measured.",
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
    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    @property
    def tested_changes(self) -> list[AttributedChange]:
        return [c for c in self.changes if c.tested]


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
    from .cpm import build_network, forward_pass

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
        if end_task_code and end_task_code in EF:
            return EF[end_task_code]
        return max(EF.values()) if EF else None

    result.anchor_code = (end_task_code
                          if end_task_code and end_task_code in nodes
                          else None)
    _, EF0, _, _ = forward_pass(nodes, preds, dd_new, started)
    base = completion(EF0)
    result.kernel_completion_new = base

    o_inc, o_nodes, o_preds, o_started, _m, _w = build_network(
        old, config, dd_old)
    if o_nodes:
        _, o_EF, _, _ = forward_pass(o_nodes, o_preds, dd_old, o_started)
        result.kernel_completion_old = completion(o_EF)
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
        result.changes.append(ac)

    result.changes.sort(
        key=lambda a: -abs(a.contribution_days or 0.0))

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
