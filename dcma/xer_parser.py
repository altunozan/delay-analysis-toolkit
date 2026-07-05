"""Primavera P6 XER file parser.

The XER format is a tab-delimited flat file. Each line's first field is a
record marker:
    ERMHDR  -> header (first line)
    %T      -> start of a table block; field 2 is the table name
    %F      -> field (column) names for the current table
    %R      -> a data row, positionally aligned to the preceding %F line
    %E      -> end of file

Columns are mapped by NAME using the %F line (order is not guaranteed across
exports/versions). This module produces typed model objects plus the raw
tables for any check that needs extra columns.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .config import DCMAConfig
from .models import Calendar, Project, Relationship, Task


@dataclass
class XerData:
    """Parsed XER content for a single project export."""

    header: list[str] = field(default_factory=list)
    raw_tables: dict[str, list[dict[str, str]]] = field(default_factory=dict)

    projects: list[Project] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    calendars: dict[str, Calendar] = field(default_factory=dict)

    # Convenience lookups (built after parsing).
    tasks_by_id: dict[str, Task] = field(default_factory=dict)

    @property
    def project(self) -> Project | None:
        """Primary project (first one in the file)."""
        return self.projects[0] if self.projects else None

    def hours_per_day(self, task: Task, config: DCMAConfig) -> float:
        """Resolve the working-hours-per-day for a task's calendar."""
        cal = self.calendars.get(task.clndr_id)
        if cal is not None and cal.day_hr_cnt > 0:
            return cal.day_hr_cnt
        return config.default_hours_per_day


def _read_text(path_or_text: str) -> str:
    """Accept either a file path or raw XER text/bytes content."""
    if isinstance(path_or_text, bytes):
        return _decode_bytes(path_or_text)
    if os.path.exists(path_or_text) and len(path_or_text) < 4096:
        with open(path_or_text, "rb") as fh:
            return _decode_bytes(fh.read())
    return path_or_text


def _decode_bytes(data: bytes) -> str:
    # XER exports are commonly cp1252; fall back to utf-8 / latin-1.
    for enc in ("cp1252", "utf-8", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def parse_xer(path_or_text: str | bytes, config: DCMAConfig | None = None) -> XerData:
    """Parse XER content (file path, raw text, or bytes) into XerData."""
    config = config or DCMAConfig()
    text = _read_text(path_or_text)

    data = XerData()
    current_table: str | None = None
    current_fields: list[str] = []

    for raw_line in text.splitlines():
        if not raw_line:
            continue
        parts = raw_line.split("\t")
        marker = parts[0]

        if marker == "ERMHDR":
            data.header = parts[1:]
        elif marker == "%T":
            current_table = parts[1] if len(parts) > 1 else None
            current_fields = []
            if current_table:
                data.raw_tables.setdefault(current_table, [])
        elif marker == "%F":
            current_fields = parts[1:]
        elif marker == "%R":
            if current_table is None or not current_fields:
                continue
            values = parts[1:]
            # Pad/truncate to the field count to stay positionally aligned.
            if len(values) < len(current_fields):
                values = values + [""] * (len(current_fields) - len(values))
            row = dict(zip(current_fields, values))
            data.raw_tables[current_table].append(row)
        elif marker == "%E":
            break
        # Unknown markers (rare) are ignored.

    _build_models(data, config)
    return data


def _build_models(data: XerData, config: DCMAConfig) -> None:
    for row in data.raw_tables.get("PROJECT", []):
        data.projects.append(Project.from_row(row))

    for row in data.raw_tables.get("CALENDAR", []):
        cal = Calendar.from_row(row, config.default_hours_per_day)
        if cal.clndr_id:
            data.calendars[cal.clndr_id] = cal

    for row in data.raw_tables.get("TASK", []):
        task = Task.from_row(row)
        data.tasks.append(task)
        if task.task_id:
            data.tasks_by_id[task.task_id] = task

    for row in data.raw_tables.get("TASKPRED", []):
        data.relationships.append(Relationship.from_row(row))

    # Resource assignment counts (TASKRSRC) feed DCMA Check 10.
    for row in data.raw_tables.get("TASKRSRC", []):
        tid = row.get("task_id", "").strip()
        task = data.tasks_by_id.get(tid)
        if task is not None:
            task.resource_count += 1
