"""Module 0 — Intake & Data Inventory.

Catalogues the set of programme revisions supplied for analysis and, crucially,
what is *missing*. Every downstream programme module depends on this: the
revision timeline (ordered by data date) drives the milestone shift tracker,
and the baseline/current split drives the variance module.

Pure and deterministic — no LLM. The output object is intended to be rendered
directly as the report's data-inventory front-matter and to seed the caveats
aggregator (Module 9) via ``missing`` and ``warnings``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from dcma.xer_parser import XerData

from .activity_codes import activity_code_types


@dataclass
class RevisionInfo:
    """One programme export in the revision set."""

    file_name: str
    project_short_name: str | None
    data_date: datetime | None
    plan_start: datetime | None
    scheduled_finish: datetime | None
    activity_count: int
    relationship_count: int
    milestone_count: int
    has_activity_codes: bool
    is_baseline: bool = False
    is_current: bool = False

    @property
    def label(self) -> str:
        """Human-facing revision label: data date is what matters forensically."""
        if self.data_date:
            return f"{self.project_short_name or self.file_name} @ {self.data_date:%Y-%m-%d}"
        return self.project_short_name or self.file_name


@dataclass
class ProgrammeInventory:
    revisions: list[RevisionInfo] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)      # absent inputs
    warnings: list[str] = field(default_factory=list)      # data-quality flags

    @property
    def baseline(self) -> RevisionInfo | None:
        return next((r for r in self.revisions if r.is_baseline), None)

    @property
    def current(self) -> RevisionInfo | None:
        return next((r for r in self.revisions if r.is_current), None)

    @property
    def data_dates(self) -> list[datetime]:
        return [r.data_date for r in self.revisions if r.data_date]


def _revision_from_data(file_name: str, data: XerData) -> RevisionInfo:
    proj = data.project
    milestones = sum(1 for t in data.tasks if t.is_milestone)
    return RevisionInfo(
        file_name=file_name,
        project_short_name=proj.short_name if proj else None,
        data_date=proj.data_date if proj else None,
        plan_start=proj.plan_start if proj else None,
        scheduled_finish=proj.scheduled_finish if proj else None,
        activity_count=len(data.tasks),
        relationship_count=len(data.relationships),
        milestone_count=milestones,
        has_activity_codes=bool(activity_code_types(data)),
    )


def build_inventory(
    files: list[tuple[str, XerData]],
    *,
    baseline_file: str | None = None,
    has_correspondence: bool = False,
    has_contract: bool = False,
    has_labour_records: bool = False,
) -> ProgrammeInventory:
    """Build the data inventory from parsed revisions.

    Parameters
    ----------
    files
        ``(file_name, XerData)`` pairs — one per uploaded XER.
    baseline_file
        File the analyst has flagged as the contract baseline. If omitted, the
        earliest data date is assumed to be the baseline (flagged as an
        assumption in ``warnings``).
    has_correspondence, has_contract, has_labour_records
        Whether these non-programme inputs were supplied; drives ``missing``.
    """
    inv = ProgrammeInventory()

    inv.revisions = [_revision_from_data(name, data) for name, data in files]

    # Multi-project exports: all tasks are pooled and the first project's
    # data date is used — that can silently distort every downstream metric,
    # so it must be surfaced loudly.
    for name, data in files:
        if len(data.projects) > 1:
            others = ", ".join(p.short_name or p.proj_id
                               for p in data.projects[1:])
            inv.warnings.append(
                f"'{name}' contains {len(data.projects)} projects "
                f"(also: {others}). All activities are pooled and the first "
                f"project's data date is used — re-export a single project "
                "per XER for reliable results."
            )

    # Order the revision timeline by data date. Revisions without a data date
    # are pushed to the end and flagged — they cannot sit on the timeline.
    def _sort_key(r: RevisionInfo):
        return (r.data_date is None, r.data_date or datetime.max)

    inv.revisions.sort(key=_sort_key)

    dated = [r for r in inv.revisions if r.data_date]
    undated = [r for r in inv.revisions if not r.data_date]
    for r in undated:
        inv.warnings.append(
            f"'{r.file_name}' has no data date (last_recalc_date); it cannot be "
            "placed on the revision timeline."
        )

    # Baseline / current designation.
    if dated:
        if baseline_file:
            match = next((r for r in dated if r.file_name == baseline_file), None)
            if match:
                match.is_baseline = True
            else:
                inv.warnings.append(
                    f"Flagged baseline '{baseline_file}' not found among revisions; "
                    "falling back to earliest data date."
                )
        if not any(r.is_baseline for r in dated):
            dated[0].is_baseline = True
            if not baseline_file:
                inv.warnings.append(
                    f"No baseline flagged — assuming earliest revision "
                    f"({dated[0].label}) is the baseline. Confirm before relying "
                    "on variance output."
                )
        dated[-1].is_current = True

    # Duplicate data dates are ambiguous for a shift timeline.
    seen: dict[datetime, str] = {}
    for r in dated:
        if r.data_date in seen:
            inv.warnings.append(
                f"'{r.file_name}' shares a data date ({r.data_date:%Y-%m-%d}) with "
                f"'{seen[r.data_date]}'; milestone-shift ordering between them is "
                "arbitrary."
            )
        else:
            seen[r.data_date] = r.file_name

    # Missing non-programme inputs — these become report caveats.
    if len(inv.revisions) < 2:
        inv.missing.append(
            "Only one programme revision supplied — milestone-shift and "
            "as-planned-vs-as-recorded analysis need at least two."
        )
    if not has_correspondence:
        inv.missing.append("No correspondence set (letters/RFIs/notices) provided.")
    if not has_contract:
        inv.missing.append("No contract provided (needed for notice & methodology).")
    if not has_labour_records:
        inv.missing.append("No labour/manpower records provided.")
    if dated and not any(r.has_activity_codes for r in dated):
        inv.missing.append(
            "No activity codes present in any revision — the as-planned vs "
            "as-recorded breakdown cannot be sliced by area/work type."
        )

    return inv
