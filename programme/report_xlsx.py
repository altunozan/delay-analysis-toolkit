"""Excel report builders for the programme modules.

One workbook per module (inventory / milestone shifts / variance), matching
the dcma.report_xlsx look. Each accepts an optional AI narrative which lands
on its own sheet. UI-independent: every builder returns bytes.
"""

from __future__ import annotations

import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .inventory import ProgrammeInventory
from .milestones import MilestoneSeries, MilestoneShiftResult
from .variance import VarianceResult

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(color="FFFFFF", bold=True)
TITLE_FONT = Font(size=16, bold=True, color="1F3864")
THIN_BORDER = Border(*[Side(style="thin", color="BFBFBF")] * 4)
WRAP = Alignment(wrap_text=True, vertical="top")
SLIP_FILL = PatternFill("solid", fgColor="FFC7CE")
GAIN_FILL = PatternFill("solid", fgColor="C6EFCE")


def _title(ws, text: str, span: int) -> None:
    ws["A1"] = text
    ws["A1"].font = TITLE_FONT
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=span)
    ws.cell(row=2, column=1,
            value=f"Generated {datetime.now():%Y-%m-%d %H:%M}").font = Font(
        italic=True, color="6E7781")


def _header_row(ws, row: int, headers: list[str]) -> None:
    for col, h in enumerate(headers, start=1):
        c = ws.cell(row=row, column=col, value=h)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.border = THIN_BORDER


def _autofit(ws, widths: dict[int, int]) -> None:
    for col_idx, width in widths.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = width


def _narrative_sheet(wb: Workbook, narrative: str | None) -> None:
    if not narrative:
        return
    ws = wb.create_sheet("AI Narrative")
    ws["A1"] = "AI-Generated Narrative"
    ws["A1"].font = Font(size=13, bold=True, color="1F3864")
    ws.column_dimensions["A"].width = 110
    for i, para in enumerate(narrative.split("\n"), start=3):
        c = ws.cell(row=i, column=1, value=para)
        c.alignment = WRAP


def _notes_sheet(wb: Workbook, notes: list[str], title: str = "Notes") -> None:
    if not notes:
        return
    ws = wb.create_sheet(title)
    ws["A1"] = title
    ws["A1"].font = Font(size=13, bold=True, color="1F3864")
    ws.column_dimensions["A"].width = 110
    for i, n in enumerate(notes, start=3):
        c = ws.cell(row=i, column=1, value=f"• {n}")
        c.alignment = WRAP


def _fmt(d) -> str:
    return f"{d:%Y-%m-%d}" if d else "—"


# --------------------------------------------------------------------------- #
# Module 0 — Data inventory
# --------------------------------------------------------------------------- #
def build_inventory_xlsx(
    inv: ProgrammeInventory, narrative: str | None = None
) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Inventory"
    _title(ws, "Programme Data Inventory", 8)

    headers = ["File", "Project", "Data Date", "Role", "Activities",
               "Relationships", "Milestones", "Activity Codes"]
    _header_row(ws, 4, headers)
    for i, r in enumerate(inv.revisions, start=5):
        role = ("Baseline" if r.is_baseline
                else "Current" if r.is_current else "Update")
        values = [r.file_name, r.project_short_name or "—", _fmt(r.data_date),
                  role, r.activity_count, r.relationship_count,
                  r.milestone_count, "Yes" if r.has_activity_codes else "No"]
        for col, v in enumerate(values, start=1):
            c = ws.cell(row=i, column=col, value=v)
            c.border = THIN_BORDER
    _autofit(ws, {1: 30, 2: 22, 3: 12, 4: 10, 5: 11, 6: 14, 7: 11, 8: 14})
    ws.freeze_panes = "A5"

    _notes_sheet(wb, inv.missing + inv.warnings, "Missing & Warnings")
    _narrative_sheet(wb, narrative)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Module 3 — Milestone shifts
# --------------------------------------------------------------------------- #
def build_milestone_xlsx(
    result: MilestoneShiftResult,
    series: list[MilestoneSeries],
    narrative: str | None = None,
) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Shift Summary"
    _title(ws, "Milestone Shift Tracker", 6)

    headers = ["Activity ID", "Milestone", "First Forecast", "Latest Date",
               "Total Shift (days)", "Achieved"]
    _header_row(ws, 4, headers)
    for i, s in enumerate(series, start=5):
        shift = round(s.total_shift_days, 1) if s.total_shift_days is not None else None
        values = [s.key, s.name, _fmt(s.first_value), _fmt(s.last_value),
                  shift, "Yes" if s.is_achieved else "No"]
        for col, v in enumerate(values, start=1):
            c = ws.cell(row=i, column=col, value=v)
            c.border = THIN_BORDER
            if col == 5 and isinstance(shift, float):
                c.fill = SLIP_FILL if shift > 0 else GAIN_FILL
    _autofit(ws, {1: 14, 2: 55, 3: 14, 4: 14, 5: 17, 6: 10})
    ws.freeze_panes = "A5"

    # Full revision-by-revision detail.
    dws = wb.create_sheet("Revision Detail")
    _title(dws, "Milestone Dates per Revision", 5)
    _header_row(dws, 4, ["Activity ID", "Milestone", "Data Date",
                         "Forecast/Actual Date", "Status"])
    row = 5
    for s in series:
        for p in s.points:
            values = [s.key, s.name, _fmt(p.data_date), _fmt(p.value_date),
                      "Actual" if p.is_actual else "Forecast"]
            for col, v in enumerate(values, start=1):
                c = dws.cell(row=row, column=col, value=v)
                c.border = THIN_BORDER
            row += 1
    _autofit(dws, {1: 14, 2: 55, 3: 12, 4: 18, 5: 10})
    dws.freeze_panes = "A5"

    notes = list(result.warnings)
    notes += [
        f"Possible renamed milestone (unconfirmed): {m.task_code} "
        f"'{m.task_name}' ~ {m.matched_to_key} '{m.matched_to_name}' "
        f"({m.similarity:.0%})"
        for m in result.needs_confirmation
    ]
    _notes_sheet(wb, notes, "Warnings")
    _narrative_sheet(wb, narrative)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Module 4 — As-planned vs as-recorded
# --------------------------------------------------------------------------- #
def build_variance_xlsx(
    var: VarianceResult, narrative: str | None = None
) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Variance"
    _title(ws, f"As-Planned vs As-Recorded — by {var.code_type_name}", 9)

    headers = [var.code_type_name, "Planned Start", "Planned Finish",
               "Recorded Start", "Recorded Finish", "Δ Start (days)",
               "Δ Finish (days)", "Planned Acts", "Recorded Acts"]
    _header_row(ws, 4, headers)
    for i, g in enumerate(var.groups, start=5):
        sd = round(g.start_delta_days, 1) if g.start_delta_days is not None else None
        fd = round(g.finish_delta_days, 1) if g.finish_delta_days is not None else None
        values = [g.code_value, _fmt(g.planned.start), _fmt(g.planned.finish),
                  _fmt(g.recorded.start), _fmt(g.recorded.finish), sd, fd,
                  g.planned.activity_count, g.recorded.activity_count]
        for col, v in enumerate(values, start=1):
            c = ws.cell(row=i, column=col, value=v)
            c.border = THIN_BORDER
            if col in (6, 7) and isinstance(v, float):
                c.fill = SLIP_FILL if v > 0 else GAIN_FILL
    _autofit(ws, {1: 42, 2: 13, 3: 13, 4: 13, 5: 14, 6: 13, 7: 13, 8: 12, 9: 13})
    ws.freeze_panes = "A5"

    _notes_sheet(wb, var.caveats + var.warnings, "Caveats")
    _narrative_sheet(wb, narrative)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

# --------------------------------------------------------------------------- #
# Module 5 — Baseline planned critical path
# --------------------------------------------------------------------------- #
def build_critical_path_xlsx(cp, narrative: str | None = None) -> bytes:
    """cp: CriticalPathResult (imported lazily to avoid a cycle)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Critical Path"
    _title(ws, f"Planned Critical Path — {cp.programme_label}", 7)

    ws.cell(row=3, column=1, value=(
        f"{len(cp.critical)} critical (TF <= {cp.float_tolerance_days:.0f}d), "
        f"{len(cp.near_critical)} near-critical (TF <= "
        f"{cp.near_critical_days:.0f}d); "
        f"{'continuous path' if cp.is_continuous else f'{cp.chain_segments} broken segments'}"
    )).font = Font(italic=True)

    headers = ["Activity ID", "Activity Name", "Type", "Early Start",
               "Early Finish", "Duration (d)", "Total Float (d)"]
    _header_row(ws, 5, headers)
    row = 6
    for a in cp.activities:
        values = [a.task_code, a.name,
                  "Milestone" if a.is_milestone else "Task",
                  _fmt(a.early_start), _fmt(a.early_finish),
                  a.duration_days, a.total_float_days]
        for col, v in enumerate(values, start=1):
            c = ws.cell(row=row, column=col, value=v)
            c.border = THIN_BORDER
            if col == 7 and isinstance(v, float):
                c.fill = SLIP_FILL if v < 0 else (
                    GAIN_FILL if a.band == "critical" else PatternFill(
                        "solid", fgColor="FFF2CC"))
        row += 1
    _autofit(ws, {1: 16, 2: 55, 3: 11, 4: 12, 5: 12, 6: 12, 7: 14})
    ws.freeze_panes = "A6"

    if cp.links:
        lws = wb.create_sheet("Driving Links")
        _title(lws, "Logic Links Between Critical Activities", 4)
        _header_row(lws, 4, ["Predecessor", "Type", "Successor", "Lag (d)"])
        for i, lk in enumerate(cp.links, start=5):
            for col, v in enumerate(
                    [lk.pred_code, lk.link_type, lk.succ_code, lk.lag_days],
                    start=1):
                c = lws.cell(row=i, column=col, value=v)
                c.border = THIN_BORDER
        _autofit(lws, {1: 18, 2: 8, 3: 18, 4: 10})
        lws.freeze_panes = "A5"

    _notes_sheet(wb, cp.caveats + cp.warnings, "Caveats")
    _narrative_sheet(wb, narrative)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
