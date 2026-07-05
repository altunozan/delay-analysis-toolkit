"""Narrative prompt builders for the programme modules.

Follows the dcma.narrative contract: the deterministic engines produce the
numbers; these functions serialise them into a constrained prompt; the LLM
(via ``dcma.narrative.stream_narrative``, any provider) narrates ONLY what is
in the prompt. Providers/keys/streaming are reused from dcma.narrative so all
modules share one backend.
"""

from __future__ import annotations

from .critical_path import CriticalPathResult
from .inventory import ProgrammeInventory
from .milestones import MilestoneSeries, MilestoneShiftResult
from .variance import VarianceResult

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
