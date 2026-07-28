"""Word-report appendix tables — the complete record, per module.

Every AI narrative caps its body tables at the five most material rows.
These builders supply the FULL set as (title, rows) pairs, appended to
the same Word document so a reader never has to open a second file to
see a row the narrative summarised.

One builder per result type, all in one place: the shapes mirror the
Excel workbooks, so the appendix and the workbook cannot drift apart
module by module. Pure data assembly — no rendering, no LLM.
"""

from __future__ import annotations

Table = tuple[str, list[dict]]


def _d(x) -> str:
    return f"{x:%Y-%m-%d}" if x else "—"


def _pack(*tables: Table) -> list[Table]:
    """Drop empty tables — an appendix heading with no rows is noise."""
    return [(t, rows) for t, rows in tables if rows]


# --------------------------------------------------------------------------- #
# Module 0 — intake
# --------------------------------------------------------------------------- #

def inventory_appendix(inv) -> list[Table]:
    return _pack(
        ("Programme revisions received", [{
            "File": r.file_name,
            "Project": r.project_short_name or "—",
            "Data date": _d(r.data_date),
            "Role": ("Baseline" if r.is_baseline
                     else "Current" if r.is_current else "Update"),
            "Plan start": _d(r.plan_start),
            "Scheduled finish": _d(r.scheduled_finish),
            "Activities": r.activity_count,
            "Relationships": r.relationship_count,
            "Milestones": r.milestone_count,
            "Activity codes": "Yes" if r.has_activity_codes else "No",
        } for r in inv.revisions]),
        ("Missing information", [{"Missing input": m}
                                 for m in inv.missing]),
    )


# --------------------------------------------------------------------------- #
# Module 3 — milestone shift tracker
# --------------------------------------------------------------------------- #

def milestone_appendix(res) -> list[Table]:
    tracked = sorted(res.series,
                     key=lambda s: -(s.total_shift_days or 0))
    return _pack(
        ("Milestone shift summary", [{
            "Milestone": s.key,
            "Name": s.name,
            "First forecast": _d(s.points[0].value_date
                                 if s.points else None),
            "Latest": _d(s.points[-1].value_date if s.points else None),
            "Total shift (d)": s.total_shift_days,
            "Achieved": ("Yes" if s.points and s.points[-1].is_actual
                         else "No"),
        } for s in tracked]),
        ("Milestone date at every data date", [{
            "Milestone": s.key,
            "Name": s.name,
            "Data date": _d(p.data_date),
            "Revision": p.revision_label,
            "Forecast / actual": _d(p.value_date),
            "Actual?": "Yes" if p.is_actual else "",
        } for s in tracked for p in s.points]),
        ("Milestone matches pending confirmation",
         [{"Milestone": k, "Detail": v}
          for k, v in (res.needs_confirmation or {}).items()]
         if isinstance(res.needs_confirmation, dict)
         else [{"Pending confirmation": str(x)}
               for x in (res.needs_confirmation or [])]),
    )


# --------------------------------------------------------------------------- #
# Module 4 — variance by breakdown group
# --------------------------------------------------------------------------- #

def variance_appendix(res) -> list[Table]:
    return _pack((f"Variance by {res.code_type_name}", [{
        "Group": g.code_value,
        "Planned start": _d(g.planned.start if g.planned else None),
        "Planned finish": _d(g.planned.finish if g.planned else None),
        "Recorded start": _d(g.recorded.start if g.recorded else None),
        "Recorded finish": _d(g.recorded.finish if g.recorded else None),
        "Start delta (d)": g.start_delta_days,
        "Finish delta (d)": g.finish_delta_days,
    } for g in res.groups]),)


# --------------------------------------------------------------------------- #
# As-built critical path
# --------------------------------------------------------------------------- #

def asbuilt_appendix(trace, roll=None, links=None) -> list[Table]:
    tables = [
        ("As-built critical path — every activity", [{
            "#": i,
            "Activity ID": a.task_code,
            "Activity": a.name,
            "Start": _d(a.act_start),
            "Finish": _d(a.act_finish),
            "Basis": a.basis,
        } for i, a in enumerate(trace.activities, start=1)]),
        ("Hand-offs along the path", [{
            "Predecessor": lk.pred_code,
            "Pred name": lk.pred_name,
            "Type": lk.kind,
            "Successor": lk.succ_code,
            "Succ name": lk.succ_name,
            "Gap (d)": lk.gap_days,
            "Basis": ("programmed logic" if lk.had_logic
                      else "SEQUENCE ONLY"),
            "Confidence": lk.score,
        } for lk in trace.links]),
    ]
    if roll is not None:
        tables.append(("Work packages", [{
            "Work package": u.name,
            "Members": u.member_count,
            "On CP": u.on_path_count,
            "Measured start": _d(u.actual_start),
            "Measured finish": _d(u.actual_finish),
            "Driving member": u.driving_member or "—",
            "Full group runs on (d)": u.presentation_only_days,
            "Measured?": "yes" if u.measured else "PRESENTATION ONLY",
        } for u in roll.umbrellas]))
    if links:
        tables.append(("Links between work packages", [{
            "From": r["from"], "To": r["to"], "Basis": r["basis"],
            "Hand-offs": r["hand_off_count"],
            "On logic": r["logic_evidenced"],
            "Sequence only": r["sequence_only"],
        } for r in links]))
    return _pack(*tables)


# --------------------------------------------------------------------------- #
# As-planned vs as-built
# --------------------------------------------------------------------------- #

def apab_appendix(display_rows, windows_by_ms=None,
                  keydates=None) -> list[Table]:
    tables = [("As-planned vs as-built — every row", [{
        "": {"umbrella": "▣", "member": "↳"}.get(
            r.get("row_kind"), ""),
        "Activity ID": r.get("task_code", ""),
        "Activity": r.get("name", ""),
        "Planned start": _d(r.get("planned_start")),
        "Planned finish": _d(r.get("planned_finish")),
        "As-built start": _d(r.get("actual_start")),
        "As-built finish": _d(r.get("actual_finish")),
        "Variance (d)": r.get("finish_var_days"),
    } for r in display_rows if r.get("row_kind") != "section"])]
    wins = [w for ws in (windows_by_ms or {}).values() for w in ws]
    if wins:
        tables.append(("Analysis windows", [{
            "From": w["from_code"], "To": w["to_code"],
            "Window start": _d(w.get("window_start")),
            "Window end": _d(w.get("window_end")),
            "Planned finish": _d(w.get("planned_finish")),
            "Actual finish": _d(w.get("actual_finish")),
            "Delay at key date (d)": w.get("cumulative_delay_days"),
            "Accrued in window (d)": w.get("window_delay_days"),
            "Resequenced": "YES" if w.get("resequenced") else "",
        } for w in wins]))
    if keydates:
        tables.append(("Key dates elected", [
            {"Activity ID": c, "Why it is key": why or ""}
            for c, why in keydates.items()]))
    return _pack(*tables)


# --------------------------------------------------------------------------- #
# Explain this delay
# --------------------------------------------------------------------------- #

def explain_appendix(res) -> list[Table]:
    return _pack(
        ("Milestone trajectory across the revisions", [{
            "Data date": _d(p.data_date),
            "Revision": p.revision_label,
            "Forecast / actual": _d(p.value_date),
            "Actual?": "Yes" if p.is_actual else "",
        } for p in res.points]),
        ("Window-by-window movement", [{
            "Window": w.index,
            "From": w.from_label, "To": w.to_label,
            "Period": f"{_d(w.start)} → {_d(w.end)}",
            "Milestone before": _d(w.pre),
            "Milestone after": _d(w.post),
            "Movement (d)": w.movement_days,
            "Path similarity": w.path_similarity,
            "Attribution reliable": ("yes" if w.attribution_reliable
                                     else "NO — path switched"),
        } for w in res.windows]),
        ("Candidate drivers per window (INFERENCE)", [{
            "Window": w.index,
            "Activity ID": s.task_code,
            "Activity": s.name,
            "Joined / left the driving path": s.direction,
        } for w in res.windows for s in w.shifts]),
    )


# --------------------------------------------------------------------------- #
# Time impact analysis
# --------------------------------------------------------------------------- #

def tia_appendix(res) -> list[Table]:
    return _pack(
        ("Fragnet activities", [{
            "Activity": a.act_id,
            "Name": a.name,
            "Duration (d)": a.duration_days,
            "Predecessors": "; ".join(map(str, a.predecessors or [])),
            "Successors": "; ".join(map(str, a.successors or [])),
            "Source / rationale": a.rationale,
            "Confidence": a.confidence,
        } for a in (res.fragnet or [])]),
        ("Fragnet assumptions (verbatim)", [{
            "Activity": a.act_id, "Assumption": s}
            for a in (res.fragnet or []) for s in (a.assumptions or [])]),
        ("Milestone impacts", [{
            "Milestone": m.code,
            "Name": m.name,
            "Pre-impact": _d(m.pre),
            "Post-impact": _d(m.post),
            "Movement (d)": (round((m.post - m.pre).total_seconds()
                                   / 86400, 1)
                             if m.pre and m.post else None),
            "Float before (d)": m.float_pre,
            "Float after (d)": m.float_post,
        } for m in (res.milestone_impacts or [])]),
    )


# --------------------------------------------------------------------------- #
# Sequence coding
# --------------------------------------------------------------------------- #

def sequence_appendix(seq, mapping_rows=None) -> list[Table]:
    tables = [("Front / stage bands", [{
        "Work front": b.front,
        "Stage": b.stage,
        "Recorded start": _d(b.act_start),
        "Recorded finish": _d(b.act_finish),
        "Activities": b.activity_count,
        "Complete": b.complete_count,
    } for b in seq.bands])]
    if mapping_rows:
        tables.append(("Activity coding — the full mapping", [{
            "Activity ID": r.task_code,
            "Activity": r.name,
            "Work front": r.front,
            "Stage": r.stage,
            "Front evidence": r.front_evidence,
            "Stage evidence": r.stage_evidence,
            "Recorded start": _d(r.act_start),
            "Recorded finish": _d(r.act_finish),
        } for r in mapping_rows]))
    return _pack(*tables)


# --------------------------------------------------------------------------- #
# Resource loading
# --------------------------------------------------------------------------- #

def resources_appendix(rl) -> list[Table]:
    return _pack(
        ("Resources", [{
            "Resource": r.short_name,
            "Name": r.name,
            "Type": r.rsrc_type,
            "Total planned qty": round(r.total_qty, 1),
            "Assignments": r.assignment_count,
        } for r in rl.resources]),
        ("Monthly planned loading", [{
            "Month": _d(p.month_end),
            "Resource": p.resource,
            "Type": p.rsrc_type,
            "Planned qty": round(p.qty, 1),
        } for p in rl.histogram]),
    )


# --------------------------------------------------------------------------- #
# Float erosion
# --------------------------------------------------------------------------- #

def float_appendix(fe) -> list[Table]:
    return _pack(
        ("Float profile by revision", [{
            "Revision": s.label,
            "Data date": _d(s.data_date),
            "Incomplete activities": s.incomplete_count,
            "Critical (TF ≤ 0)": s.critical_count,
            "Near-critical": s.near_count,
            "Negative float": s.negative_count,
            "Median TF (d)": s.median_float,
            "Min TF (d)": s.min_float,
        } for s in fe.snapshots]),
        ("Float consumption per window", [{
            "Window": w.index,
            "From": w.from_label, "To": w.to_label,
            "Matched activities": w.matched,
            "Median TF change (d)": w.median_delta,
            "Eroded": w.eroded_count,
            "Gained": w.gained_count,
        } for w in fe.windows]),
        ("Largest float movements", [{
            "Window": w.index,
            "Direction": direction,
            "Activity ID": d.task_code,
            "Activity": d.name,
            "TF before (d)": d.old_tf,
            "TF after (d)": d.new_tf,
        } for w in fe.windows
            for direction, lst in (("eroded", w.top_eroders),
                                   ("gained", w.top_gainers))
            for d in (lst or [])]),
    )


# --------------------------------------------------------------------------- #
# Progress S-curve
# --------------------------------------------------------------------------- #

def progress_appendix(pr) -> list[Table]:
    return _pack(
        ("Progress at each data date", [{
            "Revision": rp.label,
            "Data date": _d(rp.data_date),
            "Planned complete (%)": rp.planned_pct,
            "Recorded complete (%)": rp.recorded_pct,
            "Gap (pp)": (round(rp.recorded_pct - rp.planned_pct, 1)
                         if rp.recorded_pct is not None
                         and rp.planned_pct is not None else None),
        } for rp in pr.revision_points]),
        ("Planned curve", [{"Date": _d(p.date),
                            "Cumulative planned (%)": p.cum_pct}
                           for p in pr.planned_curve]),
        ("As-recorded curve", [{"Date": _d(p.date),
                                "Cumulative recorded (%)": p.cum_pct}
                               for p in pr.recorded_curve]),
    )


# --------------------------------------------------------------------------- #
# Windows / period movement
# --------------------------------------------------------------------------- #

def windows_appendix(res) -> list[Table]:
    return _pack(
        ("Window-by-window movement", [{
            "Window": w.index,
            "From": w.from_label, "To": w.to_label,
            "Data dates": f"{_d(w.start)} → {_d(w.end)}",
            "Window (d)": w.window_days,
            "Completion before": _d(w.finish_old),
            "Completion after": _d(w.finish_new),
            "Movement (d)": w.movement_days,
            "Performance (d)": w.performance_days,
            "Replanning (d)": w.replanning_days,
        } for w in res.windows]),
        ("Critical-path evolution per window", [{
            "Window": w.index,
            "CP before": w.cp_old_count,
            "CP after": w.cp_new_count,
            "Retained": w.cp_retained,
            "Similarity": w.cp_similarity,
        } for w in res.windows]),
        ("Driving activities per window", [{
            "Window": w.index,
            "Activity ID": d.task_code,
            "Activity": d.name,
            "Membership": d.membership,
            "Finish before": _d(d.finish_old),
            "Finish after": _d(d.finish_new),
            "Slip (d)": d.slip_days,
        } for w in res.windows for d in (w.drivers or [])]),
    )


# --------------------------------------------------------------------------- #
# Baseline / longest critical path
# --------------------------------------------------------------------------- #

def critical_path_appendix(cp) -> list[Table]:
    return _pack(
        ("Critical and near-critical activities", [{
            "Activity ID": a.task_code,
            "Activity": a.name,
            "Band": a.band,
            "Early start": _d(a.early_start),
            "Early finish": _d(a.early_finish),
            "Total float (d)": a.total_float_days,
        } for a in cp.activities]),
        ("Links along the path", [{
            "Predecessor": lk.pred_code,
            "Successor": lk.succ_code,
            "Type": getattr(lk, "kind", getattr(lk, "link_type", "")),
            "Lag (d)": getattr(lk, "lag_days", None),
        } for lk in (cp.links or [])]),
    )


# --------------------------------------------------------------------------- #
# DCMA 14-point assessment
# --------------------------------------------------------------------------- #

def dcma_appendix(results, trace=None) -> list[Table]:
    """The 14 checks in full, plus every affected activity per check —
    the detail the narrative body summarises to five rows."""
    tables = [("DCMA 14-point results", [{
        "#": r.number,
        "Check": r.name,
        "Status": getattr(r.status, "value", str(r.status)),
        "Metric": r.metric_label,
        "Value": r.metric_value,
        "Threshold": r.threshold,
        "Summary": r.summary,
        "Affected activities": len(r.affected_ids or []),
        "Not applicable because": r.na_reason or "",
    } for r in results])]
    affected = [{
        "#": r.number, "Check": r.name, "Activity ID": code,
    } for r in results for code in (r.affected_ids or [])]
    if affected:
        tables.append(("Activities flagged by each check", affected))
    detail = [{"#": r.number, "Check": r.name} | dict(row)
              for r in results for row in (r.detail_rows or [])]
    if detail:
        tables.append(("Check detail rows", detail))
    return _pack(*tables)
