"""Provisional, versioned rule configuration for RLPA/APvAB v2."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RLPAConfig:
    """Thresholds remain provisional until field calibration is completed."""

    actual_date_coverage_min: float = 0.70
    activities_per_30_days_min: float = 2.0
    classification_yield_min: float = 0.60
    comparable_identity_min: float = 0.70
    candidate_temporal_window_working_days: float = 45.0
    max_nonassigned_candidates_per_successor: int = 60
    temporal_adjacency_present_days: float = 2.0
    temporal_adjacency_partial_days: float = 5.0
    provisional_gap_min_working_days: float = 1.0
    interruption_report_min_working_days: float = 1.0
    clear_margin_internal_points: int = 2
    pattern_replication_min: int = 3
    coincidence_density_count: int = 8
    constraint_alignment_tolerance_days: float = 0.25
    float_critical_tolerance_days: float = 0.0
    anchor_name_tokens: tuple[str, ...] = (
        "completion", "complete", "handover", "hand over",
        "taking over", "practical completion", "mechanical completion",
        "commissioning completion", "energisation", "authority approval",
    )


UNCALIBRATED_STATEMENT = (
    "Tier assignments are rule-derived and have not been calibrated against "
    "a labelled sample. Tiers express the pattern of evidence assembled, "
    "not a validated likelihood."
)
