"""Narrative prompt builders for the programme modules.

Follows the dcma.narrative contract: the deterministic engines produce the
numbers; these functions serialise them into a constrained prompt; the LLM
(via ``dcma.narrative.stream_narrative``, any provider) narrates ONLY what is
in the prompt. Providers/keys/streaming are reused from dcma.narrative so all
modules share one backend.
"""

from __future__ import annotations

from .comparison import ComparisonResult
from .critical_path import CriticalPathResult
from .explain import ExplainResult
from .inventory import ProgrammeInventory
from .milestones import MilestoneSeries, MilestoneShiftResult
from .variance import VarianceResult
from .float_erosion import FloatErosionResult
from .progress import ProgressResult
from .resources import ResourceLoadingResult
from .sequence_coding import SequenceResult
from .tia import TIAResult
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
## As-Built Critical Path

### 1. Executive Summary
2-3 sentences: the milestone traced to, whether the works reached it, the
period the path spans, and how far the chain is corroborated by programmed
logic rather than sequence alone.

### 2. The Driving Chain
Walk the path from the start of the works to the terminal milestone as a
construction story — stages of work, not an activity list. Give the dates
of the significant hand-offs.

### 3. Work Packages
Where a work-package grouping is provided: each package, its span, and the
activity that drove its finish. State plainly that grouping is presentation
and that each package's dates come from its critical-path members only.

### 4. Evidence Behind the Hand-Offs
How many hand-offs follow a programmed relationship and how many continue on
sequence alone. Name the sequence-only hand-offs — they are the points where
the records show one activity followed another without the programme ever
linking them, and they need contemporaneous corroboration.

### 5. Stalls and Long Gaps
Hand-offs with large gaps: work that stopped between one activity finishing
and the next starting. Report the periods and their length; do not attribute
them to either party.

### 6. As-Built versus Forecast
Where the milestone was NOT achieved: state exactly where the recorded work
ends and the forecast begins, and never describe the forecast tail as
as-built.

### 7. Limitations
Every standing caveat and warning provided, in full.""",
    "apab": """\
## As-Planned vs As-Built Analysis

### 1. Executive Summary
2-3 sentences: the milestone(s) measured to, the as-built critical path
basis adopted, and the headline delay per milestone in calendar days.

### 2. The As-Built Critical Path
How the path was defined (longest path of the as-built programme, the
actual recorded sequence, or the analyst's own selection — as stated in
the data), and the work packages it runs through, in as-built order.

### 3. As-Planned vs As-Built, Package by Package
For each work package / activity on the path: planned dates (state the
elected basis — late or early), as-built dates, and the variance in
days. Tell it as a construction narrative, worst variances called out.

### 4. Key Dates & Analysis Windows
First state the measurement in one sentence: the delay at a key date is
its as-built finish minus its planned finish under the elected date
basis (calendar days, positive = late); windows run PROJECT START →
key date 1 → key date 2 → …, and the delay accrued in a window is the
change in that slippage across it. Then present the windows as a
markdown table with EXACTLY these columns:
| Window | From → To | Planned finish | Actual finish | Delay at key date (d) | Accrued in window (d) |
one row per window, figures verbatim from the data. Below the table,
explain each key date in turn: what it is, its planned vs actual date,
the delay at that date, and how much of it accrued in the window
leading to it. State which windows carry the delay and which recovered
time. A key date flagged RESEQUENCED was reached in a different order
than planned: report its direct delay normally but state that its
accrued-in-window figure carries a sequencing artefact.

### 5. Delay to Each Milestone
Per measured milestone: planned completion, as-built (or forecast)
completion, and the measured delay. Where the milestone is not yet
achieved, say the figure rests on the programme's own forecast.

### 6. Limitations
Every caveat and warning provided, in full.""",
    "comparison": """\
## Programme Revision Comparison

Every section that has data MUST carry its table — markdown tables render
as real tables in the Word export, so tabulate first, then narrate. Figures
verbatim from the data; never invent or round beyond what is supplied.

### 1. Executive Summary
3-4 sentences: the two revisions compared (with data dates), the movement
of the scheduled completion date between them, the overall volume and
character of the changes, and — where attribution data exists — whether the
movement traces to programme editing or to progress slippage.

### 2. Basis of Comparison
A table:
| | Earlier revision | Later revision |
|---|---|---|
| File | | |
| Data date | | |
| Scheduled finish | | |
then one line stating the completion movement in calendar days.

### 3. Scope Changes
A table of activities added and deleted:
| Activity ID | Name | Added / Deleted | Duration (d) | Start | Finish |
followed by 2-3 sentences on what areas of work they sit in (from the
names). If scope is unchanged, state that as a point of programme
stability and omit the table.

### 4. Logic & Sequencing Changes
One table for relationships added and removed:
| Predecessor | Type | Successor | Lag (d) | Added / Removed |
and one for lag changes:
| Link | Was | Now | Delta (d) |
then 2-3 sentences on what the re-sequencing amounts to. If the logic is
substantially unchanged, say the sequencing basis has been maintained.

### 5. Duration & Constraint Changes
A table of the duration changes, largest first:
| Activity ID | Name | Was | Now | Delta (d) |
and the constraint changes in a like table. Call out the largest
extensions and reductions in a sentence each.

### 6. Retrospective Changes to Actual Dates
CRITICAL SECTION: a table of EVERY actualised date changed or removed,
exactly as provided:
| Activity ID | Name | Was | Now | Delta (d) |
If there are none, state explicitly that no actualised dates were altered
— a positive indicator for the contemporaneity of the records.

### 7. Materiality Screening
Where screening data is provided, the ranked changes as a table (top 20):
| Score | Path position | Category | Change | Detail |
with one sentence explaining the score's construction (path position +
magnitude + red-flag bonus) and one on where analyst attention should go
first. State plainly this is a screening, not a causation finding.

### 8. What Moved Completion
Where completion-attribution data is provided: state the kernel completion
of each revision and the movement, then the tested changes as a table:
| Change | Category | Completion with | Completion without | Contribution (d) |
one row per tested change, figures verbatim. Explain the top contributors
in a sentence each — e.g. "reverting this lag change pulls completion from
X back to Y, so the change contributed +Nd". Where none of the tested
changes moves completion materially, say the movement is progress
slippage rather than programme editing. State plainly that each change was
tested one at a time against a programme where every other change remains,
so contributions interact and need not sum to the total. Note how many
changes were not re-scheduled and why (completed side, untested
categories, test cap).

### 9. Change Provenance
Where provenance data is provided, the window matrix as a table:
| Window | Completion moved (d) | Retro actual changes | Top edit categories |
then state which window introduced the bulk of the editing, which moved
completion most, and where retrospective actual-date changes first appear.

### 10. Limitations
Every standing caveat and warning provided, in full. Note that the
completion-at-a-glance chart and the change-mix chart are attached to this
document as leading figures — refer to them; do not attempt to redraw
them in text.""",
    "explain": """\
## Explain This Delay

### 1. The Question
Which milestone is examined, its date in the earliest revision, its date
(or actual) in the latest, and the total movement.

### 2. What the Records Show (FACTS)
Window by window: the milestone's recorded forecast at each data date and
the movement. These are facts from the programme files — state them as
such. Windows where the milestone held stable deserve equal mention.

### 3. The Inferred Drivers (INFERENCE)
Per window with movement: the activities that joined the driving path to
the milestone — the candidate drivers — and the work that left it. Label
this section explicitly as inference from forecast logic, to be
corroborated against contemporaneous records.

### 4. Alternative Explanations & Contrary Indications
Where the driving path switched substantially, say the attribution is
uncertain and name what else could explain the movement (re-logic,
re-planning, progress elsewhere). Reproduce the reliability flags.

### 5. Limitations
Every standing caveat and warning provided, in full.""",
    "tia": """\
## Time Impact Analysis

### 1. Executive Summary
2-3 sentences: the event, the programme it was assessed against (with data
date), and the forecast effect on completion in days.

### 2. The Event
What the event is, when it arose, the responsibility asserted (as an
assertion, not a conclusion), and the evidence noted.

### 3. The Fragnet
Each fragnet activity with its duration, logic, the source/rationale for
the duration, and every stated assumption — reproduce the assumptions
verbatim.

### 4. Forecast Impact
Completion movement and the affected milestones with pre- and post-impact
dates. State plainly where milestones are NOT affected. Note the
calibration figure and what it means for reliance on absolute dates.

### 5. Limitations
Every standing caveat and warning provided, in full — including that the
forecast is not an entitlement conclusion.""",
    "sequence": """\
## Construction Sequence Review (Analyst Coding)

### 1. Executive Summary
2-3 sentences: the work fronts and stages the programme was recoded into,
the coverage of the coding, and which fronts finished last as recorded.

### 2. Basis of the Coding
State plainly how the coding was derived (activity-ID tokens, WBS, name
keywords), its coverage figures, and whether the analyst confirmed it. The
full mapping is disclosed with the report.

### 3. Sequence by Work Front
The story the actual-date bands tell: how the stages ran within and across
the fronts — which fronts progressed steadily, which stalled, where stages
overlapped. Group into a readable account, not a band list.

### 4. Late-Running Fronts
The fronts finishing last as recorded, with dates — the candidates for the
works that drove completion. Fronts that finished early deserve equal
mention.

### 5. Limitations
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
    cmp: ComparisonResult, template: str | None = None,
    impact=None, attribution=None, provenance=None,
) -> str:
    """The revision-comparison narrative prompt. When the page ran the
    impact screening, the completion attribution or the provenance
    timeline, their results ride along so the report covers EVERYTHING
    the page shows."""
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

    if impact is not None:
        lines.append("<impact_screening note='deterministic materiality "
                     "rank: path position + magnitude + red-flag bonus; "
                     "a screening for attention, not causation'>")
        for rc in impact.ranked[:30]:
            lines.append(f"- score {rc.score} [{rc.band}] {rc.category}: "
                         f"{rc.ref} '{rc.name}' — {rc.detail}")
        if len(impact.ranked) > 30:
            lines.append(f"... (+{len(impact.ranked) - 30} more)")
        lines.append("</impact_screening>\n")

    if attribution is not None:
        def fmtd(d):
            return f"{d:%Y-%m-%d}" if d else "n/a"
        lines.append(
            "<completion_attribution note='each change tested ONE AT A "
            "TIME: the later revision re-scheduled with that single "
            "change reverted; contribution +ve = the change pushed "
            "completion later. Kernel-vs-kernel deltas; contributions "
            "interact and need not sum to the total movement'>")
        lines.append(f"- kernel completion, earlier revision: "
                     f"{fmtd(attribution.kernel_completion_old)}")
        lines.append(f"- kernel completion, later revision: "
                     f"{fmtd(attribution.kernel_completion_new)}"
                     + (f" (moved {attribution.kernel_moved_days:+.0f}d)"
                        if attribution.kernel_moved_days is not None
                        else ""))
        for a in attribution.tested_changes[:25]:
            lines.append(
                f"- {a.category}: {a.ref} '{a.name}' ({a.detail}): "
                f"completion {fmtd(a.completion_with)} with the change "
                f"-> {fmtd(a.completion_without)} without it, "
                f"contribution {a.contribution_days:+.1f}d"
                if a.contribution_days is not None else
                f"- {a.category}: {a.ref} '{a.name}': tested, no "
                "completion figure")
        untested = [a for a in attribution.changes if not a.tested]
        if untested:
            lines.append(f"- {len(untested)} change(s) not re-scheduled "
                         "(completed side, absent, or beyond the test "
                         "cap)")
        lines.append("</completion_attribution>\n")

    if provenance is not None and provenance.windows:
        lines.append("<provenance note='each change category attributed "
                     "to the update window that introduced it'>")
        for w in provenance.windows:
            top = sorted(((k, v) for k, v in w.counts.items() if v),
                         key=lambda x: -x[1])[:4]
            lines.append(
                f"- window {w.old_label} -> {w.new_label}: completion "
                f"moved {w.completion_moved_days:+.0f}d, "
                f"{w.red_flag_count} retrospective actual change(s); "
                "top edits: "
                + (", ".join(f"{k} x{v}" for k, v in top) or "none")
                if w.completion_moved_days is not None else
                f"- window {w.old_label} -> {w.new_label}: completion "
                "movement unknown")
        lines.append("</provenance>\n")

    lines.append("<caveats>")
    lines.extend(f"- {c}" for c in cmp.caveats)
    lines.extend(f"- {w}" for w in cmp.warnings)
    if impact is not None:
        lines.extend(f"- {c}" for c in impact.caveats)
        lines.extend(f"- {w}" for w in impact.warnings)
    if attribution is not None:
        lines.extend(f"- {c}" for c in attribution.caveats)
        lines.extend(f"- {w}" for w in attribution.warnings)
    if provenance is not None:
        lines.extend(f"- {c}" for c in provenance.caveats)
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
        movers = [d for d in w.drivers if (d.slip_days or 0) != 0][:8]
        for d in movers:
            lines.append(
                f"  * driver: {d.task_code} '{d.name}' finish "
                f"{fmt(d.finish_old)} -> {fmt(d.finish_new)} "
                f"({d.slip_days:+.1f}d, {d.basis_new}, {d.membership})")
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
    trace,
    roll=None,
    template: str | None = None,
) -> str:
    """Prompt for the as-built critical path (one adopted/traced path)."""
    lines = _asbuilt_prompt_body(trace, roll)
    lines.append(template or DEFAULT_TEMPLATES["asbuilt_path"])
    return "\n".join(lines)


def build_asbuilt_multi_prompt(
    traces: list,
    roll=None,
    template: str | None = None,
) -> str:
    """One report across several adopted paths (one per milestone).

    The work-package roll-up is project-wide, so it is presented once
    with the first path rather than repeated per milestone.
    """
    lines: list[str] = []
    for i, tr in enumerate(traces):
        if len(traces) > 1:
            lines.append(f"=== PATH {i + 1} of {len(traces)}: to "
                         f"{tr.terminal_code or 'unknown'} ===\n")
        lines.extend(_asbuilt_prompt_body(tr, roll if i == 0 else None))
    lines.append(template or DEFAULT_TEMPLATES["asbuilt_path"])
    return "\n".join(lines)


def _asbuilt_prompt_body(trace, roll=None) -> list[str]:
    def fmt(d):
        return f"{d:%Y-%m-%d}" if d else "unknown"
    lines = ["<context>As-built critical path to a chosen milestone — "
             "either traced BACKWARDS through the recorded dates to the "
             "start of the works, or the analyst's adopted election "
             "between computed candidates (the caveats disclose which). "
             "A programmed relationship between consecutive activities "
             "corroborates the hand-off; where none exists the chain "
             "continues on SEQUENCE alone and is flagged. Activity "
             "dates are as recorded; where the milestone was not reached "
             "the tail is the file's own forecast and is labelled "
             "'forecast'.</context>\n"]

    lines.append("<summary>")
    lines.append(f"- Terminal milestone: {trace.terminal_code}")
    lines.append(f"- Path length: {len(trace.activities)} activities")
    lines.append(f"- Basis: {trace.asbuilt_count} as-built, "
                 f"{trace.in_progress_count} in progress, "
                 f"{trace.forecast_count} forecast")
    lines.append(f"- Data date: {fmt(trace.data_date)}")
    if trace.hybrid:
        lines.append("- HYBRID PATH: the milestone was NOT achieved. Never "
                     "describe the forecast tail as as-built.")
    n_seq = sum(1 for lk in trace.links if not lk.had_logic)
    lines.append(f"- Hand-offs: {len(trace.links) - n_seq} corroborated by "
                 f"programmed logic, {n_seq} on sequence alone")
    lines.append("</summary>\n")

    lines.append("<path>")
    for i, a in enumerate(trace.activities, start=1):
        lines.append(f"{i}. {a.task_code} '{a.name}' [{a.basis}]: "
                     f"{fmt(a.act_start)} -> {fmt(a.act_finish)}")
    lines.append("</path>\n")

    if trace.links:
        lines.append("<hand_offs>")
        for lk in trace.links:
            lines.append(f"- {lk.pred_code} -> {lk.succ_code} [{lk.kind}] "
                         f"gap {lk.gap_days:+.0f}d, "
                         f"{'programmed logic' if lk.had_logic else 'SEQUENCE ONLY'}"
                         f", confidence {lk.score:.2f}")
        lines.append("</hand_offs>\n")

    if roll is not None and roll.umbrellas:
        lines.append("<work_packages note='grouping is presentation only; "
                     "measured dates come from critical-path members'>")
        for u in roll.umbrellas:
            if not u.measured:
                continue
            lines.append(f"- {u.name}: {u.member_count} activities "
                         f"({u.on_path_count} on path), "
                         f"{fmt(u.actual_start)} -> {fmt(u.actual_finish)}, "
                         f"driven by {u.driving_member}")
        lines.append("</work_packages>\n")

    lines.append("<caveats>")
    for c in list(trace.caveats) + (list(roll.caveats) if roll else []):
        lines.append(f"- {c}")
    for w in trace.warnings:
        lines.append(f"- WARNING: {w}")
    lines.append("</caveats>\n")
    return lines

def build_sequence_prompt(
    seq: SequenceResult, template: str | None = None
) -> str:
    def fmt(d):
        return f"{d:%Y-%m-%d}" if d else "—"
    lines = ["<context>Construction-sequence recoding of programme "
             f"'{seq.programme_label}': every activity assigned to a work "
             "front (from activity-ID tokens / WBS) and a construction "
             "stage (name keywords), analyst-editable; bands bracket "
             "earliest actual start to latest actual finish per front and "
             "stage. Mapping "
             + ("CONFIRMED by the analyst."
                if seq.mapping_confirmed else
                "AUTO-PROPOSED, not yet analyst-confirmed.")
             + "</context>\n"]
    lines.append("<fronts_by_recorded_finish>")
    for f, fin in seq.fronts_by_finish:
        lines.append(f"- {f}: last recorded finish {fmt(fin)}")
    lines.append("</fronts_by_recorded_finish>\n")
    lines.append("<front_stage_bands>")
    cur = None
    for b in sorted(seq.bands,
                    key=lambda b: (b.front,
                                   seq.stage_order.index(b.stage)
                                   if b.stage in seq.stage_order else 99)):
        if b.front != cur:
            cur = b.front
            lines.append(f"Front {b.front}:")
        lines.append(f"  - {b.stage}: {fmt(b.act_start)} -> "
                     f"{fmt(b.act_finish)} ({b.activity_count} acts, "
                     f"{b.complete_count} complete)")
    lines.append("</front_stage_bands>\n")
    lines.append("<caveats>")
    lines.extend(f"- {c}" for c in seq.caveats)
    lines.extend(f"- {w}" for w in seq.warnings)
    lines.append("</caveats>\n")
    lines.append(_instructions(template or DEFAULT_TEMPLATES["sequence"]))
    return "\n".join(lines)


def build_tia_prompt(res: TIAResult, template: str | None = None) -> str:
    def fmt(d):
        return f"{d:%Y-%m-%d}" if d else "—"
    e = res.event
    lines = ["<context>Prospective Time Impact Analysis: a fragnet "
             "representing the event was inserted into an in-memory copy "
             f"of programme '{res.programme_label}' (data date "
             f"{fmt(res.data_date)}) and pre- vs post-impact forecasts "
             "computed under one simplified CPM. Positive delta = later."
             "</context>\n"]
    lines.append(f"<event id='{e.event_id}'>")
    lines.append(f"- Title: {e.title}")
    if e.description:
        lines.append(f"- Description: {e.description}")
    if e.date_raised:
        lines.append(f"- Date raised: {fmt(e.date_raised)}")
    if e.responsibility_asserted:
        lines.append(f"- Responsibility ASSERTED (not concluded): "
                     f"{e.responsibility_asserted}")
    if e.evidence_note:
        lines.append(f"- Evidence noted: {e.evidence_note}")
    lines.append("</event>\n")
    lines.append("<fragnet>")
    for f in res.fragnet:
        preds = "; ".join(f"{l.other_id} {l.link_type}"
                          + (f"{l.lag_days:+g}d" if l.lag_days else "")
                          for l in f.predecessors) or "none"
        succs = "; ".join(f"{l.other_id} {l.link_type}"
                          + (f"{l.lag_days:+g}d" if l.lag_days else "")
                          for l in f.successors) or "none"
        lines.append(f"- {f.act_id} '{f.name}': {f.duration_days:g}d | "
                     f"preds: {preds} | succs: {succs}")
        if f.rationale:
            lines.append(f"    source/rationale: {f.rationale}")
        if f.assumptions:
            lines.append(f"    ASSUMPTION: {f.assumptions}")
    lines.append("</fragnet>\n")
    lines.append("<forecast_impact>")
    lines.append(f"- Completion: {fmt(res.completion_pre)} -> "
                 f"{fmt(res.completion_post)} "
                 f"({res.completion_delta_days:+.1f} days)"
                 if res.completion_delta_days is not None else
                 "- Completion impact not computable")
    for m in res.milestone_impacts:
        d = (f"{m.delta_days:+.0f}d" if m.delta_days is not None else "n/a")
        lines.append(f"- {m.code} '{m.name}': {fmt(m.pre)} -> "
                     f"{fmt(m.post)} ({d})")
    if res.calibration_days is not None:
        lines.append(f"- Calibration vs P6 scheduled finish: "
                     f"{res.calibration_days:+.1f} days")
    lines.append("</forecast_impact>\n")
    lines.append("<caveats>")
    lines.extend(f"- {c}" for c in res.caveats)
    lines.extend(f"- {w}" for w in res.warnings)
    lines.append("</caveats>\n")
    lines.append(_instructions(template or DEFAULT_TEMPLATES["tia"]))
    return "\n".join(lines)


def build_explain_prompt(res: ExplainResult,
                         template: str | None = None) -> str:
    def fmt(d):
        return f"{d:%Y-%m-%d}" if d else "—"
    lines = ["<context>'Explain this delay' analysis for milestone "
             f"{res.target_code} '{res.target_name}'. FACTS = the "
             "milestone's dates as recorded by each revision and the "
             "movement between them. DRIVERS = INFERENCE from each "
             "revision's forecast driving logic (candidates, not proven "
             "causes). Positive movement = later.</context>\n"]
    lines.append("<facts_recorded_dates>")
    for p in res.points:
        kind = "ACTUAL" if p.is_actual else "forecast"
        lines.append(f"- {p.label} (data date {fmt(p.data_date)}): "
                     f"{kind} {fmt(p.forecast)}")
    if res.total_movement_days is not None:
        lines.append(f"- Total movement: "
                     f"{res.total_movement_days:+.0f} days")
    lines.append("</facts_recorded_dates>\n")
    for w in res.windows:
        rel = ("attribution RELIABLE" if w.attribution_reliable
               else "attribution UNCERTAIN — path switched")
        sim = (f"{w.path_similarity:.0f}%"
               if w.path_similarity is not None else "n/a")
        mv = (f"{w.movement_days:+.0f}d"
              if w.movement_days is not None else "n/a")
        lines.append(f"<window_{w.index} from='{w.from_label}' "
                     f"to='{w.to_label}'>")
        lines.append(f"- FACT: {fmt(w.pre)} -> {fmt(w.post)} "
                     f"(movement {mv})")
        lines.append(f"- INFERENCE basis: driving-path similarity {sim} "
                     f"({rel})")
        for s in w.joined[:15]:
            lines.append(f"  + joined driving path: {s.task_code} "
                         f"'{s.name}'")
        if len(w.joined) > 15:
            lines.append(f"  ... (+{len(w.joined) - 15} more joined)")
        for s in w.left[:10]:
            lines.append(f"  - left driving path: {s.task_code} '{s.name}'")
        if len(w.left) > 10:
            lines.append(f"  ... (+{len(w.left) - 10} more left)")
        lines.append(f"</window_{w.index}>\n")
    lines.append("<caveats>")
    lines.extend(f"- {c}" for c in res.caveats)
    lines.extend(f"- {w}" for w in res.warnings)
    lines.append("</caveats>\n")
    lines.append(_instructions(template or DEFAULT_TEMPLATES["explain"]))
    return "\n".join(lines)


def build_apab_report_prompt(
    sections: list[dict],
    date_basis: str,
    windows_by_ms: dict[str, list[dict]] | None = None,
    caveats: list[str] | None = None,
    template: str | None = None,
) -> str:
    """Prompt for the 4-step As-Planned vs As-Built method.

    ``sections`` — one dict per measured milestone:
      {"ms", "ms_name", "basis", "delay_days", "achieved",
       "rows": [planned_vs_actual-shaped dicts incl. row_kind]}.
    """
    def fmt(d):
        return f"{d:%Y-%m-%d}" if d else "unknown"
    lines = ["<context>As-planned vs as-built analysis. The as-built "
             "critical path per milestone was elected by the analyst "
             "from computed candidates (longest path of the as-built "
             "programme vs the actual recorded sequence) and may carry "
             "analyst edits; the basis is stated per milestone. Planned "
             "dates come from the contract baseline under the stated "
             "date basis. Variances in calendar days, positive = later "
             "than planned. Rows marked [umbrella] are analyst-confirmed "
             "work packages; their members follow marked [member]. "
             "Activities beyond the data date carry the programme's own "
             "forecast, flagged [forecast].</context>\n"]
    lines.append(f"<date_basis>Planned dates = the baseline's "
                 f"{'LATE (LS/LF)' if date_basis == 'late' else 'EARLY (ES/EF)'}"
                 " dates.</date_basis>\n")
    for sec in sections:
        d = sec.get("delay_days")
        lines.append(
            f"<milestone code='{sec['ms']}' name='{sec.get('ms_name', '')}' "
            f"basis='{sec.get('basis', '')}' "
            f"achieved='{str(bool(sec.get('achieved'))).lower()}' "
            f"delay_days='{d if d is not None else 'n/a'}'>")
        for r in sec.get("rows", []):
            kind = r.get("row_kind") or "activity"
            if kind == "section":
                continue
            tag = ("[umbrella]" if kind == "umbrella"
                   else "[member]" if kind == "member" else "")
            fc = "[forecast]" if r.get("actual_is_forecast") else ""
            var = r.get("finish_var_days")
            lines.append(
                f"- {tag}{fc} {r['task_code']} '{r['name']}': planned "
                f"{fmt(r.get('planned_start'))} -> "
                f"{fmt(r.get('planned_finish'))}, as-built "
                f"{fmt(r.get('actual_start'))} -> "
                f"{fmt(r.get('actual_finish'))}"
                + (f", variance {var:+.0f}d" if var is not None else ""))
        for i, w in enumerate(
                (windows_by_ms or {}).get(sec["ms"], []), start=1):
            lines.append(
                f"  window W{i} {w.get('from_code')} -> "
                f"{w.get('to_code')} '{w.get('to_name', '')}': spans "
                f"{fmt(w.get('window_start'))} -> "
                f"{fmt(w.get('window_end'))}; key date planned "
                f"{fmt(w.get('planned_finish'))}, actual "
                f"{fmt(w.get('actual_finish'))}; delay at key date "
                f"{w.get('cumulative_delay_days')}d (direct: actual "
                "minus planned finish); accrued in this window "
                f"{w.get('window_delay_days')}d"
                + (", RESEQUENCED (accrued figure carries a "
                   "sequencing artefact)" if w.get("resequenced")
                   else ""))
        lines.append("</milestone>\n")
    lines.append("<caveats>")
    for c in (caveats or []):
        lines.append(f"- {c}")
    lines.append("</caveats>\n")
    lines.append(_HARD_RULES + "\n")
    lines.append(template or DEFAULT_TEMPLATES["apab"])
    return "\n".join(lines)
