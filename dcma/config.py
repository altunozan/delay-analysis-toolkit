"""DCMA 14-Point Assessment configuration and default thresholds.

All thresholds reflect the standard DCMA 14-Point Schedule Assessment.
They are exposed so the UI can let the planning team adjust them.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Constraint codes considered "hard" (two-way) for DCMA Check 5.
# CS_MANDSTART / CS_MANDFIN are the unambiguous hard constraints.
# The "or before" constraints cap dates and can drive float negative,
# so they are included by default but can be toggled off in the UI.
HARD_CONSTRAINT_CODES_STRICT = {"CS_MANDSTART", "CS_MANDFIN"}
HARD_CONSTRAINT_CODES_EXTENDED = {
    "CS_MANDSTART",
    "CS_MANDFIN",
    "CS_MSOB",  # Start On or Before (Start No Later Than)
    "CS_MEOB",  # Finish On or Before (Finish No Later Than)
}


@dataclass
class DCMAConfig:
    """Tunable thresholds for the 14 DCMA checks.

    Defaults follow the standard DCMA 14-Point Assessment. The UI may
    override any field before running the engine.
    """

    # --- Check 1: Logic ---
    # Target: <= 5% of incomplete activities missing a predecessor/successor.
    logic_max_pct: float = 5.0

    # --- Check 2: Leads (negative lag) ---
    # Target: 0 leads. Any negative lag fails.
    leads_max_count: int = 0

    # --- Check 3: Lags ---
    # Target: <= 5% of relationships carry a positive lag.
    lags_max_pct: float = 5.0

    # --- Check 4: Relationship Types ---
    # Target: >= 90% of relationships are Finish-to-Start.
    fs_min_pct: float = 90.0

    # --- Check 5: Hard Constraints ---
    # Target: <= 5% of activities use a hard constraint.
    hard_constraint_max_pct: float = 5.0
    # Which constraint codes count as "hard".
    hard_constraint_codes: set[str] = field(
        default_factory=lambda: set(HARD_CONSTRAINT_CODES_EXTENDED)
    )

    # --- Check 6: High Float ---
    # Target: <= 5% of activities with total float > 44 working days.
    high_float_days: float = 44.0
    high_float_max_pct: float = 5.0

    # --- Check 7: Negative Float ---
    # Target: 0 activities with negative total float.
    negative_float_max_count: int = 0

    # --- Check 8: High Duration ---
    # Target: <= 5% of incomplete activities with duration > 44 working days.
    high_duration_days: float = 44.0
    high_duration_max_pct: float = 5.0

    # --- Check 9: Invalid Dates ---
    # Target: 0 activities with actual dates beyond the data date or
    # forecast dates before the data date.
    invalid_dates_max_count: int = 0

    # --- Check 10: Resources ---
    # Target: 0 incomplete activities with duration but no resource/cost.
    resources_max_count: int = 0

    # --- Check 11: Missed Tasks ---
    # Target: <= 5% of activities finishing late vs baseline.
    missed_tasks_max_pct: float = 5.0

    # --- Check 12: Critical Path Test ---
    # Pass if a continuous critical (zero/near-zero float) path exists.
    critical_float_tolerance_days: float = 0.0

    # --- Check 13: CPLI (Critical Path Length Index) ---
    # Target: >= 0.95.
    cpli_min: float = 0.95

    # --- Check 14: BEI (Baseline Execution Index) ---
    # Target: >= 0.95.
    bei_min: float = 0.95

    # --- Conversion fallback ---
    # Hours-per-day used when an activity's calendar is missing day_hr_cnt.
    default_hours_per_day: float = 8.0
