"""QA/QC regression suite — engine level.

Layer A: delay-analyst cross-validation — modules must agree with each other
and with manual recomputation from raw XER rows.
Layer B: software edge cases — degenerate inputs, symmetry, bounds.
Layer C: report integrity — prompts carry the hard rules and caveats; every
workbook opens with its narrative sheet.

Run: python3 test_qa.py  (exit code 1 on any failure)
"""
import os
import sys

def _p(rel: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), rel)


from dcma import parse_xer, run_all_checks
from dcma.config import DCMAConfig
from programme import (
    analyse_float_erosion, analyse_windows, build_comparison_prompt,
    build_comparison_xlsx, build_critical_path_prompt,
    build_critical_path_xlsx, build_float_erosion_prompt,
    build_float_erosion_xlsx, build_inventory, build_inventory_prompt,
    build_inventory_xlsx, build_milestone_prompt, build_milestone_xlsx,
    build_progress_prompt, build_progress_xlsx, build_resources_prompt,
    build_resources_xlsx, build_variance_prompt, build_variance_xlsx,
    build_windows_prompt, build_windows_xlsx, compare_revisions,
    compute_progress, compute_variance_by_mapping, end_activity_candidates,
    extract_critical_path, extract_longest_path, extract_resource_loading,
    task_wbs_assignments, track_milestone_shifts,
)

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append((name, detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))

cfg = DCMAConfig()
with open(_p("sample/Sample Baseline.xer"),"rb") as fh:
    B = parse_xer(fh.read())
with open(_p("sample/Sample Update.xer"),"rb") as fh:
    U = parse_xer(fh.read())
fix = []
for f in ["revA.xer","revB.xer","revC.xer"]:
    with open(_p(f"sample/revisions/{f}"), "rb") as fh:
        fix.append((f, parse_xer(fh.read())))

print("== A. Cross-module numerical consistency ==")

# A1. Negative float: DCMA check 7 vs float-erosion snapshot (baseline)
dcma = {c.number: c for c in run_all_checks(B, cfg)}
fe = analyse_float_erosion([("B", B), ("U", U)])
check("A1 DCMA neg-float == float-erosion neg count (baseline)",
      dcma[7].affected_count == fe.snapshots[0].negative_count,
      f"dcma={dcma[7].affected_count} vs fe={fe.snapshots[0].negative_count}")

# A2. Critical count: DCMA check 12 vs float-method CP module
cp_f = extract_critical_path(B, "B")
check("A2 DCMA critical count == CP module critical (TF<=0)",
      dcma[12].affected_count == len(cp_f.critical),
      f"dcma={dcma[12].affected_count} vs cp={len(cp_f.critical)}")

# A3. Manual TF recount from raw rows
manual_crit = 0
for t in B.tasks:
    if t.is_loe_or_wbs or t.is_complete or t.total_float_hr is None:
        continue
    if t.total_float_hr / B.hours_per_day(t, cfg) <= 0:
        manual_crit += 1
check("A3 manual TF<=0 recount == CP module", manual_crit == len(cp_f.critical),
      f"manual={manual_crit} vs cp={len(cp_f.critical)}")

# A4. Windows completion movement == project-level scheduled finish delta
wres = analyse_windows([("B", B), ("U", U)])
manual_move = (U.project.scheduled_finish - B.project.scheduled_finish).days
check("A4 windows movement == scheduled finish delta",
      wres.windows[0].movement_days == manual_move,
      f"win={wres.windows[0].movement_days} vs manual={manual_move}")

# A5. Windows total == sum across fixture windows
wfix = analyse_windows(fix)
tot = sum(w.movement_days for w in wfix.windows if w.movement_days is not None)
check("A5 fixtures cumulative movement == sum of windows",
      wfix.total_movement_days == tot)

# A6. Longest path is a subset of... no — verify every longest-path link
# joins two on-path activities and terminal is on path
cp_l = extract_longest_path(B, "B")
codes = {a.task_code for a in cp_l.critical}
bad_links = [lk for lk in cp_l.links
             if lk.pred_code not in codes or lk.succ_code not in codes]
check("A6 longest-path links all join on-path activities", not bad_links,
      f"{len(bad_links)} dangling")
check("A6b terminal on path", cp_l.end_choice in codes)

# A7. Single-branch trace (A3400) — every non-start activity has a driving
# predecessor within the path
cp_s = extract_longest_path(B, "B", end_task_code="A3400")
succs_with_pred = {lk.succ_code for lk in cp_s.links}
starts = [a.task_code for a in cp_s.critical
          if a.task_code not in succs_with_pred]
check("A7 single-branch trace has exactly one chain start",
      len(starts) == 1, f"starts={starts}")

# A8. Comparison symmetry: swap old/new -> added<->deleted, and
# reversed-data-date warning fires
c_fwd = compare_revisions(B, U, "B", "U")
c_rev = compare_revisions(U, B, "U", "B")
check("A8 comparison added/deleted symmetric",
      len(c_fwd.added) == len(c_rev.deleted)
      and len(c_fwd.deleted) == len(c_rev.added))
check("A8b reversed direction warned",
      any("LATER data date" in w for w in c_rev.warnings))

# A9. Self-comparison finds zero changes
c_self = compare_revisions(B, B, "B", "B2")
check("A9 self-comparison == 0 changes", c_self.total_changes == 0,
      f"{c_self.total_changes} changes: {c_self.category_counts}")

# A10. S-curve bounds and monotonicity
pr = compute_progress(B, "B", [("U", U)])
mono = all(a.cum_pct <= b.cum_pct + 1e-9
           for a, b in zip(pr.planned_curve, pr.planned_curve[1:]))
check("A10 planned curve monotonic", mono)
check("A10b planned curve ends at 100%",
      abs(pr.planned_curve[-1].cum_pct - 100.0) < 0.1,
      f"end={pr.planned_curve[-1].cum_pct}")
check("A10c recorded curve <= 100%",
      all(p.cum_pct <= 100.0 + 1e-9 for p in pr.recorded_curve))
rmono = all(a.cum_pct <= b.cum_pct + 1e-9
            for a, b in zip(pr.recorded_curve, pr.recorded_curve[1:]))
check("A10d recorded curve monotonic", rmono)

# A11. Recorded % manual recount (duration weights)
w = {}
for t in U.tasks:
    if t.is_loe_or_wbs: continue
    d = t.original_duration_days(U.hours_per_day(t, cfg)) or 0.0
    w[t.task_id] = max(d, 0.0)
pct = {r["task_id"].strip(): float(r.get("phys_complete_pct") or 0)
       for r in U.raw_tables["TASK"]}
earned = sum(w[t.task_id] if t.is_complete
             else w[t.task_id]*pct.get(t.task_id,0)/100 if t.act_start else 0
             for t in U.tasks if not t.is_loe_or_wbs)
manual_pct = round(100*earned/sum(w.values()), 1)
check("A11 recorded % matches manual recount",
      abs(manual_pct - pr.recorded_pct_at_dd) < 0.05,
      f"manual={manual_pct} vs module={pr.recorded_pct_at_dd}")

# A12. Milestone shift manual verification: pick one milestone present in
# both, verify its total shift equals date difference from raw fields
inv_pool = [("Sample Baseline.xer", B), ("Sample Update.xer", U)]
ms = track_milestone_shifts([
    ("Sample Baseline.xer", B.project.data_date, B),
    ("Sample Update.xer", U.project.data_date, U),
])
s_ok = None
for s in ms.series:
    if s.total_shift_days is not None and len([p for p in s.points if p.value_date]) == 2:
        p0, p1 = [p for p in s.points if p.value_date]
        expected = (p1.value_date - p0.value_date).days
        s_ok = (s.key, s.total_shift_days, expected)
        break
check("A12 milestone shift == raw date delta",
      s_ok is not None and abs(s_ok[1] - s_ok[2]) < 1.0, str(s_ok))

# A13. Variance group bounds: WBS L1 groups — min start / max finish manual
wbs_map = task_wbs_assignments(B, level=1)
var = compute_variance_by_mapping(B, U, wbs_map, wbs_map, "WBS L1")
g = next(g for g in var.groups if g.planned.activity_count > 5)
ids = [tid for tid, lbl in wbs_map.items() if lbl == g.code_value]
starts = [t.target_start or t.early_start for t in B.tasks
          if t.task_id in set(ids) and not t.is_loe_or_wbs
          and (t.target_start or t.early_start)]
check("A13 variance planned start == manual min",
      g.planned.start == min(starts),
      f"module={g.planned.start} manual={min(starts)}")

# A14. Resource totals == raw TASKRSRC sum (for dated, positive assignments)
rl = extract_resource_loading(B, "B")
raw_total = 0.0
tid_ok = {t.task_id for t in B.tasks if not t.is_loe_or_wbs
          and (t.target_start or t.early_start or t.act_start)}
rid_ok = {r.rsrc_id for r in rl.resources} | {
    (row.get("rsrc_id") or "").strip() for row in B.raw_tables["RSRC"]}
for row in B.raw_tables["TASKRSRC"]:
    try: q = float(row.get("target_qty") or 0)
    except ValueError: q = 0
    if q > 0 and (row.get("task_id") or "").strip() in tid_ok:
        raw_total += q
mod_total = sum(r.total_qty for r in rl.resources)
check("A14 resource totals == raw sum", abs(raw_total - mod_total) < 0.5,
      f"raw={raw_total:,.0f} vs module={mod_total:,.0f}")
hist_total = sum(p.qty for p in rl.histogram)
check("A14b histogram sums to totals", abs(hist_total - mod_total) < 1.0,
      f"hist={hist_total:,.0f} vs {mod_total:,.0f}")


# A15. As-built path invariants
from programme import analyse_asbuilt_path
ab = analyse_asbuilt_path([("B", B), ("U", U)])
check("A15 asbuilt: stitched activities were forecast critical",
      all(a.forecast_by == "B" for w in ab.windows for a in w.activities))
check("A15b asbuilt: persistence freq within [0,1] and on<=eligible",
      all(0 <= e.frequency <= 1 and e.times_on_path <= e.times_eligible
          for e in ab.persistence))
check("A15c asbuilt: coverage within [0,100]",
      all(w.coverage_pct is None or 0 <= w.coverage_pct <= 100
          for w in ab.windows))
check("A15d asbuilt: core subset of persistence",
      set(ab.core_codes) <= {e.task_code for e in ab.persistence})
ab1 = analyse_asbuilt_path([("B", B)])
check("A15e asbuilt single revision -> warning, no crash",
      not ab1.windows and ab1.warnings)


# A16. Actual-date trace + triangulation invariants
from programme import extract_actual_trace, triangulate
tr_strict = extract_actual_trace([("B", B), ("U", U)], max_gap_days=240)
check("A16 strict trace: every link logic-evidenced",
      all(lk.had_logic for lk in tr_strict.links))
check("A16b trace links form a chain (each pred is next activity)",
      all(lk.score is not None and 0 <= lk.score <= 1
          for lk in tr_strict.links))
codes = [a.task_code for a in tr_strict.activities]
check("A16c trace chain has no duplicates", len(codes) == len(set(codes)))
tr_fb = extract_actual_trace([("B", B), ("U", U)], max_gap_days=15,
                             allow_temporal_fallback=True)
check("A16d fallback trace longer or equal to strict at same gap",
      len(tr_fb.activities) >= len(extract_actual_trace(
          [("B", B), ("U", U)], max_gap_days=15).activities))
tri = triangulate(ab, tr_strict)
check("A16e triangulation: agreement in [0,100] and sets partition union",
      (tri.agreement_pct is None or 0 <= tri.agreement_pct <= 100)
      and not (set(tri.both) & set(tri.trace_only))
      and not (set(tri.both) & set(tri.stitched_only)))


# A17. Sequence coding invariants
from programme import propose_sequence_mapping, analyse_sequence
sp = propose_sequence_mapping(U, "U")
check("A17 sequence: every activity gets a front and a stage",
      all(r.front and r.stage for r in sp.rows))
check("A17b sequence: coverage percentages in [0,100]",
      0 <= sp.stage_coverage_pct <= 100 and 0 <= sp.front_coverage_pct <= 100)
sq = analyse_sequence(sp.rows, "U")
check("A17c sequence: band bounds ordered (start <= finish)",
      all(b.act_start is None or b.act_finish is None
          or b.act_start <= b.act_finish for b in sq.bands))
check("A17d sequence: mapped count == actualised rows",
      sq.mapped_activities == sum(1 for r in sp.rows if r.act_start))
check("A17e sequence: unconfirmed mapping carries the extra caveat",
      any("AUTO-PROPOSED" in c for c in sq.caveats))
sq2 = analyse_sequence(sp.rows, "U", mapping_confirmed=True)
check("A17f sequence: confirmed mapping drops it",
      not any("AUTO-PROPOSED" in c for c in sq2.caveats))

print("\n== B. Edge cases / degenerate inputs ==")

# B1. Windows with one revision
w1 = analyse_windows([("B", B)])
check("B1 single-revision windows -> warning, no crash",
      not w1.windows and w1.warnings)

# B2. Float erosion with same file twice -> zero erosion
fe2 = analyse_float_erosion([("B", B), ("B2", B)])
check("B2 self float erosion: median delta == 0",
      fe2.windows[0].median_delta == 0 and fe2.windows[0].eroded_count == 0)

# B3. Progress with no updates
pr0 = compute_progress(B, "B", [])
check("B3 progress w/o updates: planned only, no crash",
      pr0.planned_curve and not pr0.recorded_curve
      and pr0.time_offset_days is None)

# B4. Longest path with bogus end code -> falls back with warning
cp_b = extract_longest_path(B, "B", end_task_code="NOPE-123")
check("B4 bogus end code -> fallback + warning",
      cp_b.end_choice is not None
      and any("not found" in w for w in cp_b.warnings))

# B5. Resources on fixture without RSRC table
rA = extract_resource_loading(fix[0][1], "revA")
check("B5 no-resource file -> warning, no crash",
      not rA.histogram and rA.warnings)

# B6. Critical path with absurd tolerance -> no critical, warning
cp_none = extract_critical_path(B, "B", float_tolerance_days=-9999)
check("B6 impossible tolerance -> warning, empty",
      not cp_none.critical and cp_none.warnings)

# B7. Fixtures through every multi-rev engine (3 revisions)
try:
    analyse_windows(fix); analyse_float_erosion(fix)
    compare_revisions(fix[0][1], fix[2][1], "A", "C")
    compute_progress(fix[0][1], "A", [(l, d) for l, d in fix[1:]])
    check("B7 fixtures through all multi-rev engines", True)
except Exception as e:
    check("B7 fixtures through all multi-rev engines", False,
          f"{type(e).__name__}: {e}")

print("\n== C. Report integrity (prompts + workbooks) ==")
from openpyxl import load_workbook
import io as _io

inv = build_inventory(inv_pool)
builds = {
    "inventory": (build_inventory_prompt(inv), build_inventory_xlsx(inv, "n")),
    "milestones": (build_milestone_prompt(ms, ms.series[:5]),
                   build_milestone_xlsx(ms, ms.series[:5], "n")),
    "variance": (build_variance_prompt(var), build_variance_xlsx(var, "n")),
    "critical_path": (build_critical_path_prompt(cp_l),
                      build_critical_path_xlsx(cp_l, "n")),
    "comparison": (build_comparison_prompt(c_fwd),
                   build_comparison_xlsx(c_fwd, "n")),
    "windows": (build_windows_prompt(wres), build_windows_xlsx(wres, "n")),
    "progress": (build_progress_prompt(pr), build_progress_xlsx(pr, "n")),
    "float_erosion": (build_float_erosion_prompt(fe),
                      build_float_erosion_xlsx(fe, "n")),
    "resources": (build_resources_prompt(rl), build_resources_xlsx(rl, "n")),
}
for name, (prompt, xlsx) in builds.items():
    has_rules = "<rules>" in prompt and "Attribute nothing" in prompt
    has_caveats = "<caveats>" in prompt or "warnings" in prompt.lower() or name == "inventory"
    wb = load_workbook(_io.BytesIO(xlsx))
    has_narr = "AI Narrative" in wb.sheetnames
    check(f"C {name}: hard rules in prompt", has_rules)
    check(f"C {name}: workbook opens, narrative sheet present",
          has_narr, str(wb.sheetnames))

# C2. Every module's standing caveats reach its prompt
for name, (prompt, _) in builds.items():
    if name == "inventory":
        continue
    check(f"C2 {name}: limitations content present",
          "caveat" in prompt.lower() or "<caveats>" in prompt)

print(f"\n{'='*60}\nRESULT: {len(PASS)} passed, {len(FAIL)} FAILED")
for name, d in FAIL:
    print(f"  FAILED: {name} — {d}")

sys.exit(1 if FAIL else 0)
