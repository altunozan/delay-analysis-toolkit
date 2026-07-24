"""Scheduling-basis disclosure helpers.

P6 forecasts swing on the scheduling options (retained logic vs progress
override vs actual dates, float definition, lag calendar, longest-path
settings) — the first thing an opposing expert attacks. This module
reads the file's own SCHEDOPTIONS table into plain-language statements
so every scheduling module and the Basis of Analysis can disclose the
settings the submitted file was calculated under.

Pure helpers: XerData in, strings out. No LLM.
"""

from __future__ import annotations

from dcma.xer_parser import XerData

# Forensically material SCHEDOPTIONS fields, with plain-language labels.
# Fields not listed here (levelling priorities, ids) are noise for delay
# analysis and are ignored by both the disclosure and the revision diff.
SCHED_OPTION_LABELS: dict[str, str] = {
    "sched_retained_logic": "Retained Logic",
    "sched_progress_override": "Progress Override",
    "sched_float_type": "Total-float definition",
    "sched_calendar_on_relationship_lag": "Relationship-lag calendar",
    "sched_use_project_end_date_for_float": (
        "Float calculated to project must-finish"),
    "sched_open_critical_flag": "Open ends treated as critical",
    "sched_outer_depend_type": "External relationships",
    "sched_lag_early_start_flag": (
        "Lag from early start of predecessor"),
    "sched_setplantoforecast": "Plan set to forecast on schedule",
    "sched_use_expect_end_flag": "Expected-finish dates used",
    "enable_multiple_longest_path_calc": (
        "Multiple longest-path calculation"),
    "use_total_float_multiple_longest_paths": (
        "Longest path identified by total float"),
    "limit_multiple_longest_path_calc": "Longest-path count limited",
    "max_multiple_longest_path": "Longest paths calculated (max)",
    "key_activity_for_multiple_longest_paths": (
        "Longest-path key activity"),
}

_FLOAT_TYPES = {"FT_FF": "Finish Float (late finish - early finish)",
                "FT_SF": "Start Float (late start - early start)",
                "FT_MIN": "Smallest of start and finish float"}

_LAG_CALS = {"rcal_Predecessor": "predecessor's calendar",
             "rcal_Successor": "successor's calendar",
             "rcal_Project": "project default calendar",
             "rcal_24Hour": "24-hour calendar"}


def sched_options_row(data: XerData) -> dict[str, str]:
    """The file's SCHEDOPTIONS row (first project's), stripped."""
    rows = data.raw_tables.get("SCHEDOPTIONS", [])
    if not rows:
        return {}
    return {k: (v or "").strip() for k, v in rows[0].items()}


def progress_treatment(row: dict[str, str]) -> str:
    """P6's three-way progress treatment, resolved to one statement."""
    if not row:
        return "not recorded in the file"
    if row.get("sched_retained_logic") == "Y":
        return "Retained Logic"
    if row.get("sched_progress_override") == "Y":
        return "Progress Override"
    return "Actual Dates"


def sched_options_summary(data: XerData) -> list[str]:
    """Plain-language lines describing the file's scheduling options —
    for on-page disclosure and the Basis of Analysis appendix."""
    row = sched_options_row(data)
    if not row:
        return ["SCHEDOPTIONS not present in the file — the scheduling "
                "options the forecast was calculated under are NOT "
                "recorded and cannot be disclosed."]
    lines = [
        f"Out-of-sequence progress treatment: {progress_treatment(row)}",
        "Total-float definition: "
        + _FLOAT_TYPES.get(row.get("sched_float_type", ""),
                           row.get("sched_float_type", "?")),
        "Relationship lags scheduled on the "
        + _LAG_CALS.get(row.get("sched_calendar_on_relationship_lag", ""),
                        row.get("sched_calendar_on_relationship_lag",
                                "?")),
    ]
    if row.get("sched_use_project_end_date_for_float") == "Y":
        lines.append("Float is calculated to the project must-finish "
                     "date (can manufacture negative float project-wide)")
    if row.get("enable_multiple_longest_path_calc") == "Y":
        via_tf = row.get(
            "use_total_float_multiple_longest_paths") == "Y"
        lines.append(
            "Multiple longest-path calculation ON, identified by "
            + ("total float" if via_tf else "driving relationships"))
    if row.get("sched_open_critical_flag") == "Y":
        lines.append("Open ends are treated as critical")
    return lines
