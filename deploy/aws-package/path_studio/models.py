"""Serializable records for the detached RLPA Path Studio.

The records deliberately separate source schedule facts, an editable draft,
and an immutable adopted version.  Visibility in the Gantt never changes
critical-path membership; only ``PathDraft.path_codes`` does.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class StudioActivity:
    code: str
    name: str
    start: str | None
    finish: str | None
    planned_start: str | None = None
    planned_finish: str | None = None
    duration_days: float | None = None
    total_float_days: float | None = None
    free_float_days: float | None = None
    status: str = ""
    task_type: str = ""
    calendar: str = ""
    wbs: str = ""
    location: str = ""
    discipline: str = ""
    system: str = ""
    activity_codes: tuple[str, ...] = ()
    path_eligible: bool = True
    eligibility_reason: str = ""


@dataclass(frozen=True, slots=True)
class StudioRelationship:
    relationship_id: str
    predecessor: str
    successor: str
    relationship_type: str
    lag_days: float = 0.0
    lag_calendar: str = ""
    source: str = "recorded"
    evidence: str = ""


@dataclass(frozen=True, slots=True)
class StudioDataset:
    analysis_id: str
    title: str
    milestone_code: str
    candidate_basis: str
    data_date: str | None
    activities: tuple[StudioActivity, ...]
    relationships: tuple[StudioRelationship, ...]
    candidate_path_codes: tuple[str, ...]
    source_fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StudioDataset":
        return cls(
            analysis_id=str(payload["analysis_id"]),
            title=str(payload.get("title", "RLPA Path Studio")),
            milestone_code=str(payload.get("milestone_code", "")),
            candidate_basis=str(payload.get("candidate_basis", "")),
            data_date=payload.get("data_date"),
            activities=tuple(StudioActivity(
                **{**item, "activity_codes": tuple(item.get("activity_codes", ()))})
                for item in payload.get("activities", [])),
            relationships=tuple(StudioRelationship(**item)
                                for item in payload.get("relationships", [])),
            candidate_path_codes=tuple(payload.get("candidate_path_codes", ())),
            source_fingerprint=str(payload.get("source_fingerprint", "")),
        )


@dataclass(frozen=True, slots=True)
class PathDraft:
    analysis_id: str
    path_codes: tuple[str, ...]
    basis: str
    revision: int = 0
    reason: str = ""
    analyst: str = ""
    updated_utc: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PathDraft":
        return cls(**{**payload, "path_codes": tuple(payload.get("path_codes", ()))})


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    severity: str
    code: str
    message: str
    activity_codes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
