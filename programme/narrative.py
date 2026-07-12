"""Narrative prompt builders for the programme modules.

Follows the dcma.narrative contract: the deterministic engines produce the
numbers; these functions serialise them into a constrained prompt; the LLM
(via ``dcma.narrative.stream_narrative``, any provider) narrates ONLY what is
in the prompt. Providers/keys/streaming are reused from dcma.narrative so all
modules share one backend.
"""

from __future__ import annotations

from .asbuilt_path import AsBuiltPathResult
from .comparison import ComparisonResult
from .critical_path import CriticalPathResult
from .inventory import ProgrammeInventory
from .milestones import MilestoneSeries, MilestoneShiftResult
from .variance import VarianceResult
from .float_erosion import FloatErosionResult
from .progress import ProgressResult
from .resources import ResourceLoadingResult
from .windows import WindowsResult

# Non-negotiable rules — always in the prompt, never user-editable, so a
# template edit can't strip the forensic safety rails.
_HARD_RULES = (
    "<rules>\n"
    "These rules override anything in the report template:\n"
    "1. Describe ONLY the figures provided above — never invent dates, "
    "causes, events, or responsibility. This is a preliminary factual "
    "screening, not a cause-linked delay analysis.\n"
    "2. Attribute nothing to either party; describe movement, not blame.\n"
    "3. Reproduce every caveat/limitation provided, verbatim or faithfully "
    "summarised, in the report's Limitations section.\n"
    "4. Where a figure is not computable or was flagged indeterminate, say "
    "so — do not estimate.\n"
    "5. Give a balanced account: report favourable findings with the same "
    "weight as unfavourable ones. Where the figures show achievement on or "
    "ahead of plan, minimal movement, or early completion, state it "
    "explicitly — do not present only the deficiencies.\n"
    "</rules>"
)

# Default report-section templates per module. These mirror how the sections
# would sit in a preliminary delay analysis report and are user-editable in
# the UI before generation (structure only — the rules above still apply).
DEFAULT_TEMPLATES: dict[str, str] = {
    "inventory": """\
## Information Relied Upon

### 1. Programme Revisions Received
For each revision: file, data date, role (baseline/update/current), size, and
what it contains. Present as a short paragraph per revision or a compact list.

### 2. Revision Timeline
One paragraph: the period the revisions span and the update cadence
(regular/irregular, gaps).

### 3. Missing Information & Its Consequences
For each missing input, state which analysis it constrains.

### 4. Limitations
All data-quality warnings and caveats.""",
    "milestones": """\
## Milestone Slippage Analysis

### 1. Executive Summary
2-3 sentences: the overall slippage picture across the tracked milestones,
naming the worst-affected milestone and its total shift.

### 2. Milestones On or Ahead of Programme
Milestones achieved on/before their original forecast, held stable across
revisions, or showing negative (favourable) shift — with figures. If none,
state that.

### 3. Key Milestone Movements
One bullet per milestone: total shift in days, the revisions between which
the largest movement occurred, and whether it is achieved or still forecast.

### 4. Observations on Trajectory
Only what the revision-by-revision dates show: is slippage accelerating,
stabilising, or recovering between data dates?

### 5. Unconfirmed Milestone Matches
List any proposed renamed/re-IDed milestones pending analyst confirmation.

### 6. Limitations
All caveats provided, plus the standing note that shifts describe programme
forecasts, not proven delay causation.""",
    "variance": """\
## Preliminary As-Planned vs As-Recorded Review

### 1. Executive Summary
2-3 sentences: where slippage clusters across the breakdown groups, naming
the worst groups with figures.

### 2. Groups On or Ahead of Plan
Groups whose recorded dates are at or better than planned (zero or negative
deltas) — with figures. If none, state that.

### 3. Group-by-Group Variance
For each group with a computable delta: planned window, recorded window,
start and finish deltas in days. Order by finish delta, worst first.

### 4. Pattern Observations
Only patterns visible in the figures: do delays concentrate in particular
groups, do starts slip more than finishes, is any part of the works
recovering between the two programmes?

### 5. Limitations
Every standing caveat and warning provided, in full.""",
    "asbuilt_path": """\
## As-Built Critical Path (Contemporaneous Reconstruction)

### 1. Executive Summary
2-3 sentences: the period reconstructed, how the as-built critical path was
derived (contemporaneous forecast criticality confirmed by recorded
performance), and how well corroborated it is (persistent core share,
coverage).

### 2. The Driving Chain, Window by Window
Per window: what the then-current programme forecast as critical, which of
that work the records show was performed, and the share of the window with
driving work active. Tell it as a construction story (stages of work), not
an activity list.

### 3. The Persistent Core
The activities critical in revision after revision — the empirical spine of
the as-built path. State the corroboration level plainly. Activities on the
path in only one revision are weakly corroborated; say so.

### 4. Gaps and Counter-Indications
Windows where forecast-critical work did not progress or coverage was low —
periods where the true driver may sit off the forecast path. Report these
with the same weight as the corroborated findings.

### 5. Remaining Path
Work on the latest forecast path still to be performed (the reconstruction
covers only the works to the latest data date).

### 6. Limitations
Every standing caveat and warning provided, in full.""",
    "comparison": """\
## Programme Revision Comparison

### 1. Executive Summary
2-3 sentences: the two revisions compared (with data dates), the movement of
the scheduled completion date between them, and the overall volume and
character of the changes.

### 2. Scope Changes
Activities added and deleted: how many, and what areas of work they sit in
(from the activity names). If scope is unchanged, state that as a point of
programme stability.

### 3. Logic & Sequencing Changes
Relationships added/removed and lag changes between activities present in
both revisions. If the logic is substantially unchanged, state that the
sequencing basis has been maintained.

### 4. Duration & Constraint Changes
The largest original-duration changes (both extensions and reductions) and
the constraint changes, with figures.

### 5. Retrospective Changes to Actual Dates
CRITICAL SECTION: list every actualised date that was changed or removed
between the revisions, exactly as provided. If there are none, state
explicitly that no actualised dates were altered — a positive indicator for
the contemporaneity of the records.

### 6. Limitations
Every standing caveat and warning provided, in full.""",
    "resources": """\
## Planned Resource Loading Review

### 1. Executive Summary
2-3 sentences: which resources the programme is loaded with, the dominant
resources by planned quantity, and the period the loading spans.

### 2. Resource-by-Resource Profile
One bullet per resource: type (labour/equipment/material), total planned
quantity, number of assignments, and when its loading peaks (from the
monthly figures).

### 3. Loading Pattern Observations
Only what the monthly figures show: where loading concentrates, whether
peaks coincide across resources, and any months with little or no planned
loading.

### 4. Coverage
How much of the programme carries no resource assignment, and what that
means for reliance on the histogram.

### 5. Limitations
Every standing caveat and warning provided, in full — including that this
is planned loading, not actual expenditure.""",
    "float_erosion": """\
## Float Erosion Review

### 1. Executive Summary
2-3 sentences: how the programme's float profile changed across the
revisions — median float, and the count of critical/negative-float
activities at the latest revision.

### 2. Float Profile by Revision
One bullet per revision: incomplete activities, how many are critical
(TF <= 0), near-critical, or negative, and the median float. Where the
profile is healthy, say so.

### 3. Float Consumption per Window
Per window: the median float change on matched activities, how many eroded
vs gained, and the worst-affected activities with figures. Report gains with
the same weight as losses.

### 4. Observations
Only what the figures show: is erosion broad-based or concentrated, and
does any revision show recovery of float?

### 5. Limitations
Every standing caveat and warning provided, in full.""",
    "progress": """\
## Progress S-Curve Review (Planned vs As-Recorded)

### 1. Executive Summary
2-3 sentences: recorded progress vs the planned profile as at the latest
data date, in percentage points and in time (days), under the stated
weighting scheme.

### 2. Planned Profile
The shape of the baseline curve: the period it spans and when the plan
expected the works to be substantially complete.

### 3. Recorded Progress
The recorded curve and each revision's as-at point. Where progress tracked
the plan, say so with the same weight as where it fell behind.

### 4. Divergence
When the recorded curve departed from the planned curve, and how the gap
evolved (widening, stable, or narrowing) — only as visible in the figures.

### 5. Limitations
Every standing caveat and warning provided, in full.""",
    "windows": """\
## Windows / Period Movement Analysis

### 1. Executive Summary
2-3 sentences: the period covered, the number of windows, the cumulative
completion movement, and which window contributed the largest movement.

### 2. Window-by-Window Movement
One bullet per window: the two revisions, the period between data dates, and
the completion movement in days (state favourable movements as plainly as
adverse ones).

### 3. Critical Path Evolution
Per window: how much of the driving path carried over, and what areas of
work joined or left it (from the activity names). Flag windows where the
path substantially switched.

### 4. Periods of Stability or Recovery
Windows with little or favourable movement, or a stable driving path —
stated with the same weight as the adverse windows. If none, state that.

### 5. Limitations
Every standing caveat and warning provided, in full.""",
    "critical_path": """\
## Baseline Planned Critical Path Review

### 1. Executive Summary
2-3 sentences: what the planned critical path runs through (from first
critical activity to completion), how many activities sit on it, and whether
it is continuous.

### 2. Path Narrative
Walk the critical chain in early-start order as a readable story: the
sequence of work fronts/disciplines it passes through, naming the key
activities and milestones with their planned dates. Group consecutive
activities into stages rather than listing every activity.

### 3. Path Integrity
Is the path continuous or broken into segments? Note any critical activities
with no logic ties to the rest of the path, and negative-float activities if
present. Where the path is sound, state that its continuity supports reliance
on the programme's critical-path logic.

### 4. Near-Critical Paths
The near-critical band: how many activities, which areas of work, and the
float margin separating them from the critical path — these are the paths
most likely to become critical if the plan moves.

### 5. Limitations
Every standing caveat and warning provided, in full.""",
}


def _instructions(template: str) -> str:
    return (
        f"{_HARD_RULES}\n\n"
        "<report_template>\n"
        "Write the narrative in markdown following this section structure. "
        "The headings and guidance below define WHAT to cover; the rules "
        "above define HOW.\n\n"
        f"{template}\n"
        "</report_template>"
    )


def build_inventory_prompt(
    inv: ProgrammeInventory, template: str | None = None
) -> str:
    lines = ["<context>Data inventory of programme revisions received for a "
             "preliminary delay analysis.</context>\n", "<revisions>"]
    for r in inv.revisions:
        role = "BASELINE" if r.is_baseline else "CURRENT" if r.is_current else "update"
        dd = f"{r.data_date:%Y-%m-%d}" if r.data_date else "no data date"
        fin = f"{r.scheduled_finish:%Y-%m-%d}" if r.scheduled_finish else "—"
        lines.append(
            f"- {r.file_name} [{role}] data date {dd}; {r.activity_count} "
            f"activities, {r.relationship_count} relationships, "
            f"{r.milestone_count} milestones; scheduled finish {fin}; "
            f"activity codes: {'yes' if r.has_activity_codes else 'no'}"
        )
    lines.append("</revisions>\n")
    if inv.missing:
        lines.append("<missing_inputs>")
        lines.extend(f"- {m}" for m in inv.missing)
        lines.append("</missing_inputs>\n")
    if inv.warnings:
        lines.append("<data_quality_warnings>")
        lines.extend(f"- {w}" for w in inv.warnings)
        lines.append("</data_quality_warnings>\n")
    lines.append(_instructions(template or DEFAULT_TEMPLATES["inventory"]))
    return "\n".join(lines)


def build_milestone_prompt(
    result: MilestoneShiftResult,
    series: list[MilestoneSeries],
    template: str | None = None,
) -> str:
    lines = ["<context>Milestone shift tracking across programme revisions. "
             "For each milestone: its forecast (F) or actual (A) date as at "
             "each revision's data date. Positive total shift = slipped "
             "later. The detailed list may show only a selection; the "
             "portfolio summary covers ALL tracked milestones so favourable "
             "performance is visible too.</context>\n"]

    # Portfolio-wide summary — keeps the narrative balanced even when only
    # the worst slippages are detailed below.
    tracked = [s for s in result.series if s.total_shift_days is not None]
    if tracked:
        stable = [s for s in tracked if abs(s.total_shift_days) <= 7]
        improved = [s for s in tracked if s.total_shift_days < -7]
        slipped = [s for s in tracked if s.total_shift_days > 7]
        achieved = [s for s in tracked if s.is_achieved]
        lines.append("<portfolio_summary>")
        lines.append(f"- Milestones tracked across revisions: {len(tracked)}")
        lines.append(f"- Achieved (actualised): {len(achieved)}")
        lines.append(f"- Held stable (shift within ±7 days): {len(stable)}"
                     + (f" — e.g. " + "; ".join(
                        f"{s.key} '{s.name}' ({s.total_shift_days:+.0f}d)"
                        for s in stable[:5]) if stable else ""))
        lines.append(f"- Improved (moved earlier by >7 days): {len(improved)}"
                     + (f" — " + "; ".join(
                        f"{s.key} '{s.name}' ({s.total_shift_days:+.0f}d)"
                        for s in improved[:5]) if improved else ""))
        lines.append(f"- Slipped later by >7 days: {len(slipped)}")
        lines.append("</portfolio_summary>\n")

    lines.append("<milestones>")
    for s in series:
        shift = (f"{s.total_shift_days:+.0f} days"
                 if s.total_shift_days is not None else "not computable")
        lines.append(f"Milestone {s.key} — {s.name} | total shift {shift} | "
                     f"achieved: {'yes' if s.is_achieved else 'no'}")
        for p in s.points:
            if p.value_date is None:
                continue
            kind = "A" if p.is_actual else "F"
            lines.append(f"  as at {p.data_date:%Y-%m-%d}: "
                         f"{p.value_date:%Y-%m-%d} [{kind}]")
    lines.append("</milestones>\n")
    if result.needs_confirmation:
        lines.append("<unconfirmed_matches>")
        for m in result.needs_confirmation:
            lines.append(
                f"- {m.task_code} '{m.task_name}' may be a renamed "
                f"{m.matched_to_key} '{m.matched_to_name}' "
                f"(similarity {m.similarity:.0%}) — NOT merged, pending "
                "analyst confirmation"
            )
        lines.append("</unconfirmed_matches>\n")
    if result.warnings:
        lines.append("<caveats>")
        lines.extend(f"- {w}" for w in result.warnings)
        lines.append("</caveats>\n")
    lines.append(_instructions(template or DEFAULT_TEMPLATES["milestones"]))
    return "\n".join(lines)


def build_variance_prompt(
    var: VarianceResult, template: str | None = None
) -> str:
    lines = ["<context>Preliminary as-planned vs as-recorded screening. The "
             f"programme was re-broken-down by '{var.code_type_name}'; each "
             "group is bracketed by earliest start / latest finish in the "
             "baseline (planned) and the updated programme (as-recorded). "
             "Positive delta = later than planned.</context>\n", "<groups>"]
    for g in var.groups:
        def fmt(d):
            return f"{d:%Y-%m-%d}" if d else "—"
        sd = (f"{g.start_delta_days:+.0f}d"
              if g.start_delta_days is not None else "n/a")
        fd = (f"{g.finish_delta_days:+.0f}d"
              if g.finish_delta_days is not None else "n/a")
        lines.append(
            f"- {g.code_value}: planned {fmt(g.planned.start)} → "
            f"{fmt(g.planned.finish)} ({g.planned.activity_count} acts); "
            f"recorded {fmt(g.recorded.start)} → {fmt(g.recorded.finish)} "
            f"({g.recorded.activity_count} acts); Δstart {sd}, Δfinish {fd}"
        )
    lines.append("</groups>\n")
    lines.append("<caveats>")
    lines.extend(f"- {c}" for c in var.caveats)
    lines.extend(f"- {w}" for w in var.warnings)
    lines.append("</caveats>\n")
    lines.append(_instructions(template or DEFAULT_TEMPLATES["variance"]))
    return "\n".join(lines)

def build_critical_path_prompt(
    cp: CriticalPathResult, template: str | None = None
) -> str:
    if cp.method == "longest_path":
        method_desc = (
            "The path was identified by a BACKWARD DRIVING-LOGIC TRACE from "
            f"the end activity '{cp.end_choice}': at each step the "
            "predecessor(s) imposing the tightest constraint on the "
            "activity's early dates were followed. 'Critical' means on this "
            "driving path (regardless of float value); 'near-critical' is a "
            f"context band of activities with total float <= "
            f"{cp.near_critical_days:.0f}d."
        )
    else:
        method_desc = (
            "'Critical' = total float <= "
            f"{cp.float_tolerance_days:.0f}d; 'near-critical' = float <= "
            f"{cp.near_critical_days:.0f}d."
        )
    lines = ["<context>Planned critical path extracted from a single "
             f"programme ('{cp.programme_label}'). Activities listed in "
             f"early-start order. {method_desc} Links are the driving logic "
             "relationships along the path.</context>\n"]

    lines.append("<path_summary>")
    lines.append(f"- Critical activities: {len(cp.critical)}")
    lines.append(f"- Near-critical activities: {len(cp.near_critical)}")
    lines.append(f"- Chain segments: {cp.chain_segments} "
                 f"({'continuous' if cp.is_continuous else 'BROKEN'})")
    if cp.start_activity and cp.end_activity:
        lines.append(f"- Runs from {cp.start_activity} to {cp.end_activity}")
    neg = [a for a in cp.critical
           if a.total_float_days is not None and a.total_float_days < 0]
    lines.append(f"- Negative-float activities: {len(neg)}")
    lines.append("</path_summary>\n")

    lines.append("<critical_activities>")
    for a in cp.critical:
        es = f"{a.early_start:%Y-%m-%d}" if a.early_start else "—"
        ef = f"{a.early_finish:%Y-%m-%d}" if a.early_finish else "—"
        kind = "MILESTONE" if a.is_milestone else f"{a.duration_days:.0f}d" \
            if a.duration_days is not None else "task"
        lines.append(f"- {a.task_code} '{a.name}' [{kind}] {es} -> {ef} "
                     f"(TF {a.total_float_days:+.0f}d)")
    lines.append("</critical_activities>\n")

    if cp.links:
        lines.append("<driving_links>")
        for lk in cp.links[:150]:
            lag = f" lag {lk.lag_days:+.0f}d" if lk.lag_days else ""
            lines.append(f"- {lk.pred_code} -{lk.link_type}-> "
                         f"{lk.succ_code}{lag}")
        if len(cp.links) > 150:
            lines.append(f"... (+{len(cp.links) - 150} more links)")
        lines.append("</driving_links>\n")

    if cp.near_critical:
        lines.append("<near_critical_band>")
        for a in cp.near_critical[:60]:
            lines.append(f"- {a.task_code} '{a.name}' "
                         f"(TF {a.total_float_days:+.0f}d)")
        if len(cp.near_critical) > 60:
            lines.append(f"... (+{len(cp.near_critical) - 60} more)")
        lines.append("</near_critical_band>\n")

    lines.append("<caveats>")
    lines.extend(f"- {c}" for c in cp.caveats)
    lines.extend(f"- {w}" for w in cp.warnings)
    lines.append("</caveats>\n")
    lines.append(_instructions(template or DEFAULT_TEMPLATES["critical_path"]))
    return "\n".join(lines)

def build_comparison_prompt(
    cmp: ComparisonResult, template: str | None = None
) -> str:
    def fmt(d):
        return f"{d:%Y-%m-%d}" if d else "unknown"
    lines = ["<context>Change log between two programme revisions: "
             f"'{cmp.old_label}' (data date {fmt(cmp.old_data_date)}, "
             f"scheduled finish {fmt(cmp.old_finish)}) and "
             f"'{cmp.new_label}' (data date {fmt(cmp.new_data_date)}, "
             f"scheduled finish {fmt(cmp.new_finish)}). Activities matched "
             "by Activity ID; relationships by (pred, succ, type). Positive "
             "delta = increased/later in the newer revision.</context>\n"]

    lines.append("<change_summary>")
    for k, v in cmp.category_counts.items():
        lines.append(f"- {k}: {v}")
    lines.append("</change_summary>\n")

    def _acts(tag: str, refs, cap: int = 40):
        if not refs:
            return
        lines.append(f"<{tag}>")
        for a in refs[:cap]:
            d = f"{a.duration_days:.0f}d" if a.duration_days is not None else "—"
            kind = "MILESTONE" if a.is_milestone else d
            lines.append(f"- {a.task_code} '{a.name}' [{kind}] "
                         f"{fmt(a.start)} -> {fmt(a.finish)}")
        if len(refs) > cap:
            lines.append(f"... (+{len(refs) - cap} more)")
        lines.append(f"</{tag}>\n")

    _acts("activities_added", cmp.added)
    _acts("activities_deleted", cmp.deleted)

    def _changes(tag: str, changes, cap: int = 40):
        if not changes:
            return
        lines.append(f"<{tag}>")
        for c in changes[:cap]:
            delta = (f" (delta {c.delta_days:+.1f}d)"
                     if c.delta_days is not None else "")
            lines.append(f"- {c.task_code} '{c.name}': {c.old_value} -> "
                         f"{c.new_value}{delta}")
        if len(changes) > cap:
            lines.append(f"... (+{len(changes) - cap} more)")
        lines.append(f"</{tag}>\n")

    _changes("duration_changes", cmp.duration_changes)
    _changes("constraint_changes", cmp.constraint_changes)
    _changes("calendar_reassignments", cmp.calendar_changes)
    _changes("renamed_activities", cmp.renamed, cap=20)
    _changes("lag_changes", cmp.lag_changes)
    # Never truncate the forensic category.
    _changes("retrospective_actual_date_changes",
             cmp.actual_date_changes, cap=10_000)

    def _logic(tag: str, links):
        if not links:
            return
        lines.append(f"<{tag}>")
        for lk in links[:40]:
            lag = f" lag {lk.lag_days:+.1f}d" if lk.lag_days else ""
            lines.append(f"- {lk.pred_code} '{lk.pred_name}' "
                         f"-{lk.link_type}-> {lk.succ_code} "
                         f"'{lk.succ_name}'{lag}")
        if len(links) > 40:
            lines.append(f"... (+{len(links) - 40} more)")
        lines.append(f"</{tag}>\n")

    _logic("logic_added", cmp.logic_added)
    _logic("logic_removed", cmp.logic_removed)

    lines.append("<caveats>")
    lines.extend(f"- {c}" for c in cmp.caveats)
    lines.extend(f"- {w}" for w in cmp.warnings)
    lines.append("</caveats>\n")
    lines.append(_instructions(template or DEFAULT_TEMPLATES["comparison"]))
    return "\n".join(lines)


def build_windows_prompt(
    res: WindowsResult, template: str | None = None
) -> str:
    def fmt(d):
        return f"{d:%Y-%m-%d}" if d else "unknown"
    lines = ["<context>Windows analysis across programme revisions: each "
             "window runs between two consecutive data dates. Movement = "
             "change in the programme's scheduled completion over the "
             "window (positive = slipped later). The driving path per "
             "revision comes from a backward driving-logic trace; joined/"
             "left = activities entering/leaving that path in the window."
             "</context>\n"]
    if res.total_movement_days is not None:
        lines.append(f"<total_completion_movement>"
                     f"{res.total_movement_days:+.0f} days across "
                     f"{len(res.windows)} window(s)"
                     f"</total_completion_movement>\n")
    lines.append("<windows>")
    for w in res.windows:
        mv = (f"{w.movement_days:+.0f}d"
              if w.movement_days is not None else "not computable")
        sim = (f"{w.cp_similarity:.0%}"
               if w.cp_similarity is not None else "n/a")
        lines.append(
            f"Window {w.index}: {w.from_label} -> {w.to_label} | "
            f"{fmt(w.start)} to {fmt(w.end)} ({w.window_days or '?'} days) | "
            f"completion {fmt(w.finish_old)} -> {fmt(w.finish_new)} "
            f"(movement {mv}) | driving path {w.cp_old_count} -> "
            f"{w.cp_new_count} activities, {w.cp_retained} retained "
            f"(similarity {sim})"
        )
        for s in w.joined[:15]:
            lines.append(f"  + joined path: {s.task_code} '{s.name}'")
        if len(w.joined) > 15:
            lines.append(f"  ... (+{len(w.joined) - 15} more joined)")
        for s in w.left[:15]:
            lines.append(f"  - left path: {s.task_code} '{s.name}'")
        if len(w.left) > 15:
            lines.append(f"  ... (+{len(w.left) - 15} more left)")
    lines.append("</windows>\n")
    lines.append("<caveats>")
    lines.extend(f"- {c}" for c in res.caveats)
    lines.extend(f"- {w}" for w in res.warnings)
    lines.append("</caveats>\n")
    lines.append(_instructions(template or DEFAULT_TEMPLATES["windows"]))
    return "\n".join(lines)


def build_progress_prompt(
    res: ProgressResult, template: str | None = None
) -> str:
    from .progress import WEIGHT_OPTIONS
    def fmt(d):
        return f"{d:%Y-%m-%d}" if d else "unknown"
    scheme = WEIGHT_OPTIONS.get(res.weight_scheme, res.weight_scheme)
    lines = ["<context>Progress S-curve comparison. Planned curve = "
             "cumulative profile of the baseline; recorded curve = "
             "cumulative profile built from the update's actual dates and "
             f"physical percent complete. Weighting: {scheme}. Values are "
             "cumulative percent of total weight at each month end."
             "</context>\n"]
    lines.append("<as_at_latest_data_date>")
    lines.append(f"- Planned: {res.planned_pct_at_dd}%")
    lines.append(f"- Recorded: {res.recorded_pct_at_dd}%")
    if res.time_offset_days is not None:
        lines.append(f"- Time offset: {res.time_offset_days:+.0f} days "
                     "(positive = the recorded level of progress was "
                     "planned to be reached that many days earlier)")
    lines.append("</as_at_latest_data_date>\n")
    lines.append("<planned_curve>")
    for p in res.planned_curve:
        lines.append(f"- {fmt(p.date)}: {p.cum_pct:.1f}%")
    lines.append("</planned_curve>\n")
    if res.recorded_curve:
        lines.append(f"<recorded_curve source='{res.recorded_label}'>")
        for p in res.recorded_curve:
            lines.append(f"- {fmt(p.date)}: {p.cum_pct:.1f}%")
        lines.append("</recorded_curve>\n")
    if res.revision_points:
        lines.append("<revision_points>")
        for rp in res.revision_points:
            lines.append(f"- {rp.label}: as at {fmt(rp.data_date)} recorded "
                         f"{rp.recorded_pct}% vs planned {rp.planned_pct}%")
        lines.append("</revision_points>\n")
    lines.append("<caveats>")
    lines.extend(f"- {c}" for c in res.caveats)
    lines.extend(f"- {w}" for w in res.warnings)
    lines.append("</caveats>\n")
    lines.append(_instructions(template or DEFAULT_TEMPLATES["progress"]))
    return "\n".join(lines)


def build_float_erosion_prompt(
    res: FloatErosionResult, template: str | None = None
) -> str:
    def fmt(d):
        return f"{d:%Y-%m-%d}" if d else "unknown"
    lines = ["<context>Float erosion across programme revisions. Total "
             "float in days, per revision (incomplete activities only). "
             f"'Near-critical' = 0 < TF <= {res.near_days:.0f}d. Erosion "
             "per window is measured on activities present and incomplete "
             "in both revisions (negative delta = float consumed)."
             "</context>\n"]
    lines.append("<float_profile_by_revision>")
    for s in res.snapshots:
        lines.append(
            f"- {s.label} (data date {fmt(s.data_date)}): "
            f"{s.incomplete_count} incomplete | median TF "
            f"{s.median_float}d | min TF {s.min_float}d | "
            f"critical (TF<=0): {s.critical_count} | negative: "
            f"{s.negative_count} | near-critical: {s.near_count}"
        )
    lines.append("</float_profile_by_revision>\n")
    for w in res.windows:
        lines.append(f"<window_{w.index} from='{w.from_label}' "
                     f"to='{w.to_label}'>")
        lines.append(f"- matched activities: {w.matched}; median float "
                     f"change {w.median_delta}d; eroded (>1d lost): "
                     f"{w.eroded_count}; gained (>1d): {w.gained_count}")
        for d in w.top_eroders:
            lines.append(f"  eroded: {d.task_code} '{d.name}' "
                         f"{d.old_tf:+.0f}d -> {d.new_tf:+.0f}d "
                         f"({d.delta:+.0f}d)")
        for d in w.top_gainers:
            lines.append(f"  gained: {d.task_code} '{d.name}' "
                         f"{d.old_tf:+.0f}d -> {d.new_tf:+.0f}d "
                         f"({d.delta:+.0f}d)")
        lines.append(f"</window_{w.index}>\n")
    lines.append("<caveats>")
    lines.extend(f"- {c}" for c in res.caveats)
    lines.extend(f"- {w}" for w in res.warnings)
    lines.append("</caveats>\n")
    lines.append(_instructions(template or DEFAULT_TEMPLATES["float_erosion"]))
    return "\n".join(lines)


def build_resources_prompt(
    res: ResourceLoadingResult, template: str | None = None
) -> str:
    lines = ["<context>Planned resource loading from programme "
             f"'{res.programme_label}': each assignment's target quantity "
             "spread uniformly across its activity's scheduled dates, "
             "bucketed by month. PLANNED loading, not actual expenditure."
             "</context>\n"]
    lines.append("<resources>")
    for r in res.resources:
        lines.append(f"- {r.short_name} ('{r.name}') [{r.rsrc_type}]: total "
                     f"planned qty {r.total_qty:,.0f} across "
                     f"{r.assignment_count} assignments")
    lines.append("</resources>\n")
    lines.append("<monthly_loading>")
    for p in res.histogram:
        lines.append(f"- {p.month_end:%Y-%m}: {p.resource} "
                     f"[{p.rsrc_type}] {p.qty:,.0f}")
    lines.append("</monthly_loading>\n")
    lines.append("<caveats>")
    lines.extend(f"- {c}" for c in res.caveats)
    lines.extend(f"- {w}" for w in res.warnings)
    lines.append("</caveats>\n")
    lines.append(_instructions(template or DEFAULT_TEMPLATES["resources"]))
    return "\n".join(lines)


def build_asbuilt_prompt(
    res: AsBuiltPathResult, template: str | None = None
) -> str:
    def fmt(d):
        return f"{d:%Y-%m-%d}" if d else "unknown"
    lines = ["<context>As-built critical path reconstructed from the "
             "project's own contemporaneous programmes: an activity is on "
             "the as-built path for a window when the programme in force at "
             "the window's start forecast it critical (backward driving-"
             "logic trace) AND the closing revision records it as performed "
             "in that window. The persistence index counts, per activity, "
             "the revisions in which it sat on the forecast path while "
             "still to be performed.</context>\n"]

    core = set(res.core_codes)
    lines.append("<summary>")
    lines.append(f"- Revisions used: {res.revision_count}; windows: "
                 f"{len(res.windows)}")
    lines.append(f"- Ever forecast-critical activities: "
                 f"{len(res.persistence)}; persistent core: "
                 f"{len(res.core_codes)}")
    lines.append(f"- Latest-path activities still to perform: "
                 f"{res.remaining_path_count}")
    lines.append("</summary>\n")

    for w in res.windows:
        lines.append(f"<window_{w.index} from='{w.from_label}' "
                     f"to='{w.to_label}' period='{fmt(w.start)} to "
                     f"{fmt(w.end)}'>")
        cov = (f"{w.coverage_pct:.0f}%" if w.coverage_pct is not None
               else "n/a")
        lines.append(f"- Forecast critical at window start: "
                     f"{w.forecast_critical_count}; performed in window: "
                     f"{len(w.activities)}; driving-work coverage: {cov}")
        for a in w.activities[:60]:
            af = fmt(a.act_finish) if a.act_finish else "in progress"
            tag = " [CORE]" if a.task_code in core else ""
            lines.append(f"  - {a.task_code} '{a.name}'{tag}: performed "
                         f"{fmt(a.act_start)} -> {af}")
        if len(w.activities) > 60:
            lines.append(f"  ... (+{len(w.activities) - 60} more)")
        lines.append(f"</window_{w.index}>\n")

    lines.append("<persistence_index>")
    for e in res.persistence[:80]:
        lines.append(f"- {e.task_code} '{e.name}': on forecast path "
                     f"{e.times_on_path} of {e.times_eligible} eligible "
                     f"revisions ({e.frequency:.0%})")
    if len(res.persistence) > 80:
        lines.append(f"... (+{len(res.persistence) - 80} more)")
    lines.append("</persistence_index>\n")

    lines.append("<caveats>")
    lines.extend(f"- {c}" for c in res.caveats)
    lines.extend(f"- {w}" for w in res.warnings)
    lines.append("</caveats>\n")
    lines.append(_instructions(template or DEFAULT_TEMPLATES["asbuilt_path"]))
    return "\n".join(lines)
