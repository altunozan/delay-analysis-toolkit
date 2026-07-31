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
import sys
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
    # UTF-8 FIRST: utf-8 is self-validating (random cp1252 text almost
    # never decodes as valid utf-8), while cp1252 accepts nearly any
    # byte sequence — trying cp1252 first made the utf-8 branch
    # unreachable and turned every utf-8 export into mojibake
    # ("Café" -> "CafÃ©"). cp1252 remains the fallback for the legacy
    # exports it actually fits.
    for enc in ("utf-8", "cp1252", "latin-1"):
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
            # Memory: XER rows are mostly empty cells and massively
            # repeated short strings (statuses, ids, dates). Dropping
            # empty cells is safe — every consumer reads via
            # row.get(col, default) — and interning short values makes
            # repeats share one object. On a 20 MB field export this
            # halves the parsed footprint; without it, Cloud's ~1 GB
            # host dies mid-parse on multi-revision uploads.
            row = {f: sys.intern(v) if len(v) <= 40 else v
                   for f, v in zip(current_fields, values) if v}
            data.raw_tables[current_table].append(row)
        elif marker == "%E":
            break
        # Unknown markers (rare) are ignored.

    _build_models(data, config)
    if not data.tasks:
        # Real-world specimen: a 27MB export carrying 25 copies of the
        # project's structural tables and no TASK table at all. A file
        # with zero activities cannot feed ANY module — fail loudly
        # instead of returning a silently empty programme.
        raise ValueError(
            "The file parsed but contains no activities (no TASK rows). "
            "It may be a structure-only export, an interrupted export, "
            "or a concatenation of project-structure blocks — re-export "
            "from P6 with activities included.")
    return data


def structural_defects(data: XerData) -> list[str]:
    """Evidential hard-gate findings (C4).

    Every code-keyed calculation (CPM nodes, comparison, windows, CAB)
    silently MERGES activities that share a visible Activity ID, and
    the parser pools every project in the file — so a multi-project
    export or a duplicate code can make an activity, its logic and its
    delay contribution disappear without any error. These conditions
    gate intake; they are not inventory footnotes.
    """
    out: list[str] = []
    proj_tasks: dict[str, int] = {}
    for row in data.raw_tables.get("TASK", []):
        pid = (row.get("proj_id") or "").strip()
        if pid:
            proj_tasks[pid] = proj_tasks.get(pid, 0) + 1
    if len(proj_tasks) > 1:
        detail = ", ".join(f"{p} ({n} activities)"
                           for p, n in sorted(proj_tasks.items()))
        out.append(
            f"Multi-project export: {len(proj_tasks)} projects carry "
            f"activities in one file ({detail}). Code-keyed analysis "
            "would pool them into one network — re-export ONE project "
            "per .xer file.")
    counts: dict[str, int] = {}
    for t in data.tasks:
        if t.task_code:
            counts[t.task_code] = counts.get(t.task_code, 0) + 1
    dups = sorted(c for c, n in counts.items() if n > 1)
    if dups:
        out.append(
            f"{len(dups)} duplicate Activity ID(s) (e.g. "
            + ", ".join(dups[:5]) + (" …" if len(dups) > 5 else "")
            + ") — activities sharing a code silently merge in every "
            "code-keyed calculation, deleting one of them from the "
            "network. Make Activity IDs unique in P6 and re-export.")
    return out


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
