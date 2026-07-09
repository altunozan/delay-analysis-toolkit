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

# --------------------------------------------------------------------------- #
# Module 6 — Revision comparison / change log
# --------------------------------------------------------------------------- #
def build_comparison_xlsx(cmp, narrative: str | None = None) -> bytes:
    """cmp: programme.comparison.ComparisonResult"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    _title(ws, "Programme Revision Comparison", 4)
    ws.cell(row=3, column=1, value=(
        f"'{cmp.old_label}' (DD {_fmt(cmp.old_data_date)}, finish "
        f"{_fmt(cmp.old_finish)})  vs  '{cmp.new_label}' "
        f"(DD {_fmt(cmp.new_data_date)}, finish {_fmt(cmp.new_finish)})"
    )).font = Font(italic=True)

    _header_row(ws, 5, ["Change category", "Count"])
    for i, (k, v) in enumerate(cmp.category_counts.items(), start=6):
        a = ws.cell(row=i, column=1, value=k)
        b = ws.cell(row=i, column=2, value=v)
        a.border = b.border = THIN_BORDER
        if k.startswith("Actual dates") and v:
            a.fill = b.fill = SLIP_FILL
    _autofit(ws, {1: 42, 2: 10})

    def _acts_sheet(title, refs):
        if not refs:
            return
        s = wb.create_sheet(title)
        _header_row(s, 1, ["Activity ID", "Activity", "Type",
                           "Start", "Finish", "Duration (d)"])
        for i, a in enumerate(refs, start=2):
            vals = [a.task_code, a.name,
                    "Milestone" if a.is_milestone else "Task",
                    _fmt(a.start), _fmt(a.finish),
                    a.duration_days if a.duration_days is not None else "—"]
            for col, v in enumerate(vals, start=1):
                s.cell(row=i, column=col, value=v).border = THIN_BORDER
        _autofit(s, {1: 18, 2: 52, 3: 10, 4: 12, 5: 12, 6: 12})
        s.freeze_panes = "A2"

    _acts_sheet("Added", cmp.added)
    _acts_sheet("Deleted", cmp.deleted)

    def _changes_sheet(title, changes, red_all=False):
        if not changes:
            return
        s = wb.create_sheet(title)
        _header_row(s, 1, ["Activity / Link", "Name", "Was", "Now",
                           "Delta (d)"])
        for i, c in enumerate(changes, start=2):
            vals = [c.task_code, c.name, c.old_value, c.new_value,
                    c.delta_days if c.delta_days is not None else ""]
            for col, v in enumerate(vals, start=1):
                cell = s.cell(row=i, column=col, value=v)
                cell.border = THIN_BORDER
                if red_all or (col == 5 and isinstance(v, (int, float))
                               and v > 0):
                    cell.fill = SLIP_FILL
                elif col == 5 and isinstance(v, (int, float)) and v < 0:
                    cell.fill = GAIN_FILL
        _autofit(s, {1: 26, 2: 46, 3: 26, 4: 30, 5: 10})
        s.freeze_panes = "A2"

    _changes_sheet("Duration Changes", cmp.duration_changes)
    _changes_sheet("Constraint Changes", cmp.constraint_changes)
    _changes_sheet("Calendar Changes", cmp.calendar_changes)
    _changes_sheet("Renamed", cmp.renamed)
    _changes_sheet("Lag Changes", cmp.lag_changes)
    _changes_sheet("Actuals Changed", cmp.actual_date_changes, red_all=True)

    def _logic_sheet(title, links):
        if not links:
            return
        s = wb.create_sheet(title)
        _header_row(s, 1, ["Predecessor", "Pred name", "Type",
                           "Successor", "Succ name", "Lag (d)"])
        for i, lk in enumerate(links, start=2):
            vals = [lk.pred_code, lk.pred_name, lk.link_type,
                    lk.succ_code, lk.succ_name, lk.lag_days]
            for col, v in enumerate(vals, start=1):
                s.cell(row=i, column=col, value=v).border = THIN_BORDER
        _autofit(s, {1: 18, 2: 40, 3: 7, 4: 18, 5: 40, 6: 9})
        s.freeze_panes = "A2"

    _logic_sheet("Logic Added", cmp.logic_added)
    _logic_sheet("Logic Removed", cmp.logic_removed)

    _notes_sheet(wb, cmp.warnings + cmp.caveats, "Warnings & Caveats")
    _narrative_sheet(wb, narrative)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

# --------------------------------------------------------------------------- #
# Module 7 — Windows / period movement
# --------------------------------------------------------------------------- #
def build_windows_xlsx(res, narrative: str | None = None) -> bytes:
    """res: programme.windows.WindowsResult"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Windows"
    _title(ws, "Windows / Period Movement Analysis", 10)
    if res.total_movement_days is not None:
        ws.cell(row=3, column=1, value=(
            f"Cumulative completion movement: "
            f"{res.total_movement_days:+.0f} days across "
            f"{len(res.windows)} window(s)")).font = Font(italic=True)

    headers = ["#", "From", "To", "Window start", "Window end",
               "Window (d)", "Finish (from)", "Finish (to)",
               "Movement (d)", "Path similarity"]
    _header_row(ws, 5, headers)
    for i, w in enumerate(res.windows, start=6):
        sim = f"{w.cp_similarity:.0%}" if w.cp_similarity is not None else "—"
        vals = [w.index, w.from_label, w.to_label, _fmt(w.start),
                _fmt(w.end), w.window_days, _fmt(w.finish_old),
                _fmt(w.finish_new), w.movement_days, sim]
        for col, v in enumerate(vals, start=1):
            c = ws.cell(row=i, column=col, value=v)
            c.border = THIN_BORDER
            if col == 9 and isinstance(v, (int, float)):
                c.fill = SLIP_FILL if v > 0 else GAIN_FILL
    _autofit(ws, {1: 4, 2: 26, 3: 26, 4: 13, 5: 13, 6: 11, 7: 13, 8: 13,
                  9: 13, 10: 14})
    ws.freeze_panes = "A6"

    shifts = [(w.index, s) for w in res.windows for s in w.shifts]
    if shifts:
        s2 = wb.create_sheet("Path Changes")
        _header_row(s2, 1, ["Window", "Direction", "Activity ID", "Activity"])
        for i, (widx, s) in enumerate(shifts, start=2):
            vals = [widx, s.direction, s.task_code, s.name]
            for col, v in enumerate(vals, start=1):
                c = s2.cell(row=i, column=col, value=v)
                c.border = THIN_BORDER
                if col == 2:
                    c.fill = SLIP_FILL if v == "joined" else GAIN_FILL
        _autofit(s2, {1: 8, 2: 10, 3: 20, 4: 56})
        s2.freeze_panes = "A2"

    _notes_sheet(wb, res.warnings + res.caveats, "Warnings & Caveats")
    _narrative_sheet(wb, narrative)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

# --------------------------------------------------------------------------- #
# Module 8 — Progress S-curve
# --------------------------------------------------------------------------- #
def build_progress_xlsx(res, narrative: str | None = None) -> bytes:
    """res: programme.progress.ProgressResult"""
    from .progress import WEIGHT_OPTIONS
    wb = Workbook()
    ws = wb.active
    ws.title = "S-Curve"
    _title(ws, "Progress S-Curve (Planned vs As-Recorded)", 4)
    ws.cell(row=3, column=1, value=(
        f"Weighting: {WEIGHT_OPTIONS.get(res.weight_scheme, res.weight_scheme)}"
        + (f" | Planned {res.planned_pct_at_dd}% vs recorded "
           f"{res.recorded_pct_at_dd}% at latest data date"
           if res.planned_pct_at_dd is not None else "")
        + (f" | time offset {res.time_offset_days:+.0f}d"
           if res.time_offset_days is not None else "")
    )).font = Font(italic=True)

    _header_row(ws, 5, ["Month end", "Planned cum %", "Recorded cum %"])
    rec = {p.date.strftime("%Y-%m"): p.cum_pct for p in res.recorded_curve}
    pla = {p.date.strftime("%Y-%m"): p.cum_pct for p in res.planned_curve}
    months = sorted(set(rec) | set(pla))
    prev_p = prev_r = None
    for i, m in enumerate(months, start=6):
        p = pla.get(m, prev_p if prev_p is not None else None)
        r = rec.get(m, prev_r if prev_r is not None else None)
        prev_p, prev_r = p, r
        vals = [m, round(p, 1) if p is not None else "",
                round(r, 1) if r is not None else ""]
        for col, v in enumerate(vals, start=1):
            ws.cell(row=i, column=col, value=v).border = THIN_BORDER
    _autofit(ws, {1: 12, 2: 14, 3: 15})
    ws.freeze_panes = "A6"

    if res.revision_points:
        s2 = wb.create_sheet("Revision Points")
        _header_row(s2, 1, ["Revision", "Data date", "Recorded %",
                            "Planned %", "Gap (pts)"])
        for i, rp in enumerate(res.revision_points, start=2):
            gap = (round(rp.planned_pct - rp.recorded_pct, 1)
                   if rp.planned_pct is not None
                   and rp.recorded_pct is not None else "")
            vals = [rp.label, _fmt(rp.data_date), rp.recorded_pct,
                    rp.planned_pct, gap]
            for col, v in enumerate(vals, start=1):
                c = s2.cell(row=i, column=col, value=v)
                c.border = THIN_BORDER
                if col == 5 and isinstance(v, (int, float)):
                    c.fill = SLIP_FILL if v > 0 else GAIN_FILL
        _autofit(s2, {1: 30, 2: 12, 3: 12, 4: 12, 5: 10})

    _notes_sheet(wb, res.warnings + res.caveats, "Warnings & Caveats")
    _narrative_sheet(wb, narrative)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

# --------------------------------------------------------------------------- #
# Module 9 — Float erosion
# --------------------------------------------------------------------------- #
def build_float_erosion_xlsx(res, narrative: str | None = None) -> bytes:
    """res: programme.float_erosion.FloatErosionResult"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Float Profile"
    _title(ws, "Float Erosion Review", 8)
    _header_row(ws, 4, ["Revision", "Data date", "Incomplete",
                        "Median TF (d)", "Min TF (d)", "Critical (TF<=0)",
                        "Negative", f"Near (<= {res.near_days:.0f}d)"])
    for i, s in enumerate(res.snapshots, start=5):
        vals = [s.label, _fmt(s.data_date), s.incomplete_count,
                s.median_float, s.min_float, s.critical_count,
                s.negative_count, s.near_count]
        for col, v in enumerate(vals, start=1):
            c = ws.cell(row=i, column=col, value=v)
            c.border = THIN_BORDER
            if col == 7 and isinstance(v, int) and v > 0:
                c.fill = SLIP_FILL
    _autofit(ws, {1: 28, 2: 12, 3: 11, 4: 13, 5: 11, 6: 15, 7: 10, 8: 13})
    ws.freeze_panes = "A5"

    deltas = [(w, d, "eroded") for w in res.windows for d in w.top_eroders] \
        + [(w, d, "gained") for w in res.windows for d in w.top_gainers]
    if deltas:
        s2 = wb.create_sheet("Top Movers")
        _header_row(s2, 1, ["Window", "Direction", "Activity ID", "Activity",
                            "TF was (d)", "TF now (d)", "Delta (d)"])
        for i, (w, d, direction) in enumerate(deltas, start=2):
            vals = [f"{w.from_label} -> {w.to_label}", direction,
                    d.task_code, d.name, d.old_tf, d.new_tf,
                    round(d.delta, 1)]
            for col, v in enumerate(vals, start=1):
                c = s2.cell(row=i, column=col, value=v)
                c.border = THIN_BORDER
                if col == 7:
                    c.fill = SLIP_FILL if d.delta < 0 else GAIN_FILL
        _autofit(s2, {1: 34, 2: 10, 3: 18, 4: 46, 5: 11, 6: 11, 7: 10})
        s2.freeze_panes = "A2"

    _notes_sheet(wb, res.warnings + res.caveats, "Warnings & Caveats")
    _narrative_sheet(wb, narrative)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

# --------------------------------------------------------------------------- #
# Module 10 — Planned resource loading
# --------------------------------------------------------------------------- #
def build_resources_xlsx(res, narrative: str | None = None) -> bytes:
    """res: programme.resources.ResourceLoadingResult"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Resources"
    _title(ws, "Planned Resource Loading", 5)
    ws.cell(row=3, column=1,
            value=f"Programme: {res.programme_label} — PLANNED loading, "
                  "not actual expenditure").font = Font(italic=True)
    _header_row(ws, 5, ["Resource", "Name", "Type", "Total planned qty",
                        "Assignments"])
    for i, r in enumerate(res.resources, start=6):
        vals = [r.short_name, r.name, r.rsrc_type,
                round(r.total_qty, 1), r.assignment_count]
        for col, v in enumerate(vals, start=1):
            ws.cell(row=i, column=col, value=v).border = THIN_BORDER
    _autofit(ws, {1: 14, 2: 34, 3: 12, 4: 17, 5: 12})
    ws.freeze_panes = "A6"

    if res.histogram:
        s2 = wb.create_sheet("Monthly Loading")
        months = sorted({p.month_end for p in res.histogram})
        names = [r.short_name for r in res.resources]
        grid = {(p.resource, p.month_end): p.qty for p in res.histogram}
        _header_row(s2, 1, ["Month"] + names)
        for i, m in enumerate(months, start=2):
            s2.cell(row=i, column=1, value=f"{m:%Y-%m}").border = THIN_BORDER
            for j, n in enumerate(names, start=2):
                q = grid.get((n, m))
                c = s2.cell(row=i, column=j,
                            value=round(q, 1) if q else None)
                c.border = THIN_BORDER
        _autofit(s2, {1: 10, **{j: 13 for j in range(2, len(names) + 2)}})
        s2.freeze_panes = "B2"

    _notes_sheet(wb, res.warnings + res.caveats, "Warnings & Caveats")
    _narrative_sheet(wb, narrative)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
