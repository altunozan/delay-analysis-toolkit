"""Lightweight data models for parsed P6 schedule entities.

These wrap the raw XER rows (dict of column-name -> string value) with typed
accessors and DCMA-relevant helpers. All durations/floats/lags in XER are
stored in HOURS; helpers convert to days using the activity calendar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


# --- XER status / type / relationship code constants ---

STATUS_NOT_STARTED = "TK_NotStart"
STATUS_ACTIVE = "TK_Active"
STATUS_COMPLETE = "TK_Complete"

TYPE_TASK = "TT_Task"
TYPE_RSRC = "TT_Rsrc"
TYPE_START_MILE = "TT_Mile"
TYPE_FIN_MILE = "TT_FinMile"
TYPE_LOE = "TT_LOE"
TYPE_WBS = "TT_WBS"

MILESTONE_TYPES = {TYPE_START_MILE, TYPE_FIN_MILE}
# Summary / non-working activity types excluded from most metric checks.
EXCLUDED_FROM_LOGIC = {TYPE_WBS, TYPE_LOE}

REL_FS = "PR_FS"
REL_SS = "PR_SS"
REL_FF = "PR_FF"
REL_SF = "PR_SF"


_DATE_FORMATS = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
)


def parse_date(value: str | None) -> datetime | None:
    """Parse an XER date string; return None if empty/unparseable."""
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


@dataclass
class Calendar:
    clndr_id: str
    name: str
    day_hr_cnt: float

    @classmethod
    def from_row(cls, row: dict[str, str], default_hpd: float) -> "Calendar":
        hpd = _to_float(row.get("day_hr_cnt"))
        if hpd is None or hpd <= 0:
            hpd = default_hpd
        return cls(
            clndr_id=row.get("clndr_id", "").strip(),
            name=row.get("clndr_name", "").strip(),
            day_hr_cnt=hpd,
        )


@dataclass
class Project:
    proj_id: str
    short_name: str
    plan_start: datetime | None
    must_finish: datetime | None        # plan_end_date == Must Finish By
    scheduled_finish: datetime | None   # scd_end_date
    data_date: datetime | None          # last_recalc_date

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "Project":
        return cls(
            proj_id=row.get("proj_id", "").strip(),
            short_name=row.get("proj_short_name", "").strip(),
            plan_start=parse_date(row.get("plan_start_date")),
            must_finish=parse_date(row.get("plan_end_date")),
            scheduled_finish=parse_date(row.get("scd_end_date")),
            data_date=parse_date(row.get("last_recalc_date")),
        )


@dataclass
class Relationship:
    pred_task_id: str
    task_id: str            # successor
    pred_type: str          # PR_FS / PR_SS / PR_FF / PR_SF
    lag_hr: float

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "Relationship":
        return cls(
            pred_task_id=row.get("pred_task_id", "").strip(),
            task_id=row.get("task_id", "").strip(),
            pred_type=row.get("pred_type", "").strip(),
            lag_hr=_to_float(row.get("lag_hr_cnt")) or 0.0,
        )


@dataclass
class Task:
    task_id: str            # internal id (join key)
    task_code: str          # user-facing Activity ID
    name: str
    task_type: str
    status: str
    clndr_id: str

    target_drtn_hr: float | None
    remain_drtn_hr: float | None
    total_float_hr: float | None
    free_float_hr: float | None

    early_start: datetime | None
    early_finish: datetime | None
    late_start: datetime | None
    late_finish: datetime | None
    act_start: datetime | None
    act_finish: datetime | None
    target_start: datetime | None
    target_finish: datetime | None

    cstr_type: str
    cstr_date: datetime | None
    cstr_type2: str
    cstr_date2: datetime | None

    # Populated after parsing for resource check (number of resource assigns).
    resource_count: int = 0

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "Task":
        return cls(
            task_id=row.get("task_id", "").strip(),
            task_code=row.get("task_code", "").strip(),
            name=row.get("task_name", "").strip(),
            task_type=row.get("task_type", "").strip(),
            status=row.get("status_code", "").strip(),
            clndr_id=row.get("clndr_id", "").strip(),
            target_drtn_hr=_to_float(row.get("target_drtn_hr_cnt")),
            remain_drtn_hr=_to_float(row.get("remain_drtn_hr_cnt")),
            total_float_hr=_to_float(row.get("total_float_hr_cnt")),
            free_float_hr=_to_float(row.get("free_float_hr_cnt")),
            early_start=parse_date(row.get("early_start_date")),
            early_finish=parse_date(row.get("early_end_date")),
            late_start=parse_date(row.get("late_start_date")),
            late_finish=parse_date(row.get("late_end_date")),
            act_start=parse_date(row.get("act_start_date")),
            act_finish=parse_date(row.get("act_end_date")),
            target_start=parse_date(row.get("target_start_date")),
            target_finish=parse_date(row.get("target_end_date")),
            cstr_type=row.get("cstr_type", "").strip(),
            cstr_date=parse_date(row.get("cstr_date")),
            cstr_type2=row.get("cstr_type2", "").strip(),
            cstr_date2=parse_date(row.get("cstr_date2")),
        )

    # --- status helpers ---
    @property
    def is_complete(self) -> bool:
        return self.status == STATUS_COMPLETE

    @property
    def is_incomplete(self) -> bool:
        return self.status != STATUS_COMPLETE

    @property
    def is_not_started(self) -> bool:
        return self.status == STATUS_NOT_STARTED

    @property
    def is_milestone(self) -> bool:
        return self.task_type in MILESTONE_TYPES

    @property
    def is_loe_or_wbs(self) -> bool:
        return self.task_type in EXCLUDED_FROM_LOGIC

    def total_float_days(self, hours_per_day: float) -> float | None:
        if self.total_float_hr is None:
            return None
        return self.total_float_hr / hours_per_day

    def remaining_duration_days(self, hours_per_day: float) -> float | None:
        if self.remain_drtn_hr is None:
            return None
        return self.remain_drtn_hr / hours_per_day

    def original_duration_days(self, hours_per_day: float) -> float | None:
        if self.target_drtn_hr is None:
            return None
        return self.target_drtn_hr / hours_per_day
