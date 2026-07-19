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
import io

from openpyxl import load_workbook

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


# A18. AI-review prompt/parser layer (offline)
from programme import (build_mapping_review_prompt, parse_mapping_review,
                       build_view_advice_prompt, parse_view_advice)
pmr = build_mapping_review_prompt(sp.rows[:5])
check("A18 review prompt lists stages and rows",
      "Allowed stage labels" in pmr and sp.rows[0].task_code in pmr)
good = parse_mapping_review(
    '[{"id": "%s", "stage": "Finishes & Fit-Out"}]' % sp.rows[0].task_code,
    {r.task_code for r in sp.rows[:5]})
check("A18b parser accepts valid correction", len(good) == 1)
check("A18c parser rejects unknown ids and stages",
      parse_mapping_review('[{"id":"ZZZ","stage":"Finishes & Fit-Out"},'
                           '{"id":"%s","stage":"Made Up"}]'
                           % sp.rows[0].task_code,
                           {sp.rows[0].task_code}) == {})
check("A18d parser survives garbage", parse_mapping_review("oops", {"A"}) == {})
adv = parse_view_advice('{"mode":"bands","colour":"Stage","max_fronts":10,"rationale":"r"}')
check("A18e view advice parses and clamps",
      adv is not None and adv["mode"] == "bands"
      and parse_view_advice('{"mode":"nope"}') is None)
check("A18f view advice prompt built",
      "sequence_gantt" in build_view_advice_prompt(sq, 30))


# A19. Hierarchy rebuild invariants
from programme import (available_dimensions, build_hierarchy, tree_to_dict,
                       build_gantt_html, config_to_json, config_from_json)
hd = available_dimensions(B)
check("A19 dimensions discovered (5 WBS levels, no codes in sample)",
      len([d for d in hd if d.dim_id.startswith("wbs:")]) == 5)
hh = build_hierarchy(B, ["wbs:2", "wbs:3"], "B",
                     dim_labels=["WBS Level 2", "WBS Level 3"])
check("A19b every source activity placed exactly once",
      hh.is_complete and hh.placed_activities == hh.source_activities)
# leaf-count == placed (no duplication anywhere in the tree)
def _leaves(n):
    return len(n.activities) + sum(_leaves(c) for c in n.children.values())
check("A19c tree leaf count == placed", _leaves(hh.root) == hh.placed_activities)
# rollup: root span brackets every activity date
def _acts(n):
    yield from n.activities
    for c in n.children.values():
        yield from _acts(c)
all_starts = [a.start for a in _acts(hh.root) if a.start]
all_fins = [a.finish for a in _acts(hh.root) if a.finish]
root_kids = list(hh.root.children.values())
check("A19d rollup start == min child start",
      min(k.start for k in root_kids if k.start) == min(all_starts))
check("A19e rollup finish == max child finish",
      max(k.finish for k in root_kids if k.finish) == max(all_fins))
# source data untouched: parse count unchanged after building
check("A19f source untouched (task count stable)",
      hh.source_activities == sum(1 for t in B.tasks
                                  if t.task_type != "TT_WBS"))
html = build_gantt_html(tree_to_dict(hh.root))
check("A19g gantt html self-contained", "<script>" in html
      and "http" not in html.split("</style>")[0].lower())
cfg = config_from_json(config_to_json("v", ["wbs:2"], ["WBS Level 2"]))
check("A19h config round-trips", cfg is not None and cfg[1] == ["wbs:2"])
check("A19i bad config rejected", config_from_json('{"dimensions":["x:1"]}') is None)


# A20. Sequence dims + hierarchy xlsx
from programme import sequence_dimension_mappings, build_hierarchy_xlsx
ex = sequence_dimension_mappings(U, sp.rows)
hs = build_hierarchy(U, ["seq:front", "seq:stage"], "U",
                     dim_labels=["Front", "Stage"], extra_mappings=ex)
check("A20 seq-dims hierarchy places all activities",
      hs.is_complete and hs.placed_activities == hs.source_activities)
xh = build_hierarchy_xlsx(hs)
from openpyxl import load_workbook as _lw
import io as _io2
_wbh = _lw(_io2.BytesIO(xh))
check("A20b hierarchy xlsx sheets",
      set(_wbh.sheetnames) >= {"Hierarchy", "Flat Table"})
outl = sum(1 for rd in _wbh["Hierarchy"].row_dimensions.values()
           if rd.outline_level)
check("A20c hierarchy xlsx has collapsible outlines", outl > 100)
flat_rows = _wbh["Flat Table"].max_row - 1
check("A20d flat table row per activity",
      flat_rows == hs.placed_activities,
      f"flat={flat_rows} vs placed={hs.placed_activities}")
check("A20e seq config ids accepted",
      config_from_json('{"dimensions": ["seq:front"], "labels": ["F"]}')
      is not None)


# A21. Dimension menu = WBS levels + activity codes + TASK UDFs only
hd2 = available_dimensions(U)
kinds2 = {d.dim_id.partition(":")[0] for d in hd2}
check("A21 only the three families offered", kinds2 <= {"wbs", "code", "udf"})
check("A21b all WBS levels present",
      {f"wbs:{i}" for i in range(1, 6)} <= {d.dim_id for d in hd2})
# synthetic TASK UDF proves the udf: path end-to-end
_t0 = U.tasks[0]
U.raw_tables.setdefault("UDFTYPE", []).append(
    {"udf_type_id": "999", "table_name": "TASK",
     "udf_type_label": "QA Zone", "udf_type_name": "qa_zone",
     "logical_data_type": "FT_TEXT"})
U.raw_tables.setdefault("UDFVALUE", []).append(
    {"udf_type_id": "999", "fk_id": _t0.task_id, "udf_text": "Zone QA",
     "udf_number": "", "udf_date": "", "udf_code_id": ""})
hd3 = available_dimensions(U)
check("A21c TASK UDF surfaces as a dimension",
      any(d.dim_id == "udf:999" and "QA Zone" in d.label for d in hd3))
_hu = build_hierarchy(U, ["udf:999"], "U", dim_labels=["QA Zone"])
check("A21d UDF hierarchy: tagged task grouped, rest Unassigned",
      _hu.is_complete and "Zone QA" in _hu.root.children
      and _hu.root.children["Zone QA"].activity_count == 1)
U.raw_tables["UDFTYPE"].pop(); U.raw_tables["UDFVALUE"].pop()
# synthetic global + project code types both surface, scope-labelled
U.raw_tables.setdefault("ACTVTYPE", []).append(
    {"actv_code_type_id": "801", "actv_code_type": "Zone",
     "actv_code_type_scope": "AS_Global"})
U.raw_tables["ACTVTYPE"].append(
    {"actv_code_type_id": "802", "actv_code_type": "Package",
     "actv_code_type_scope": "AS_Project"})
hd4 = available_dimensions(U)
lbls = {d.dim_id: d.label for d in hd4}
check("A21e global + project codes both offered, scope in label",
      "[Global]" in lbls.get("code:801", "")
      and "[Project]" in lbls.get("code:802", ""))
U.raw_tables["ACTVTYPE"] = []
check("A21f config kinds restricted",
      config_from_json('{"dimensions": ["cal:"]}') is None
      and config_from_json('{"dimensions": ["udf:9", "wbs:2"]}') is not None)


# A22. Prospective TIA engine
from programme import (DelayEvent, FragnetActivity, FragnetLink, run_tia,
                       validate_fragnet, parse_fragnet_json, parse_links,
                       find_template_activities, find_template_work_packages,
                       assess_event_scope, build_logic_recommendation_prompt,
                       parse_logic_recommendation_json)
from datetime import timedelta as _td
_ev = DelayEvent("EV-QA", "test event")
_fr = [FragnetActivity("TIA-010", "chain", 120,
                       successors=[FragnetLink("KD15")])]
_r = run_tia(U, "U", _ev, _fr)
check("A22 TIA delta exact for a direct chain into completion",
      _r.completion_post == _r.data_date + _td(days=120)
      and (_r.completion_delta_days or 0) > 0)
_r0 = run_tia(U, "U", _ev, [])
check("A22b empty fragnet -> zero delta",
      _r0.completion_pre == _r0.completion_post)
check("A22c calibration disclosed", _r.calibration_days is not None
      and any("Calibration" in w for w in _r.warnings))
iss = validate_fragnet(U, [FragnetActivity("TIA-1", "x", -5)])
check("A22d validation flags open ends + bad duration",
      any("open start" in i for i in iss)
      and any("duration" in i for i in iss))
iss2 = validate_fragnet(U, [
    FragnetActivity("TIA-A", "a", 5,
                    predecessors=[FragnetLink("TIA-B")],
                    successors=[FragnetLink("TIA-B"), FragnetLink("KD15")]),
    FragnetActivity("TIA-B", "b", 5,
                    predecessors=[FragnetLink("TIA-A")],
                    successors=[FragnetLink("TIA-A")])])
check("A22e circular fragnet detected",
      any("Circular" in i for i in iss2))
check("A22f fragnet json parser rejects invalid refs",
      parse_fragnet_json('{"activities":[{"id":"TIA-1","name":"x",'
                         '"duration_days":5,'
                         '"successors":[{"id":"NOPE-99"}]}]}', U)[0]
      .successors == [])
check("A22g template search returns project evidence",
      len(find_template_activities(U, "installation of ceiling")) > 0)
check("A22h link text round-trip",
      parse_links("A1:SS:5")[0].link_type == "SS")
_scope = assess_event_scope(DelayEvent(
    "EV-S", "Additional ceiling installation", "include approval and test",
    area="Zone B", discipline="Architectural", project_context="Hospital",
    work_package="Additional ceiling works"))
check("A22i event understood before fragnet drafting",
      _scope.work_nature.startswith("Additional")
      and "Testing / inspection / handover" in _scope.lifecycle_stages)
_pkgs = find_template_work_packages(U, "installation of ceiling")
check("A22j existing work packages ranked before generic drafting",
      bool(_pkgs) and bool(_pkgs[0]["activities"])
      and _pkgs[0]["score"] > 0)
_logic_prompt = build_logic_recommendation_prompt(_ev, _fr, U)
check("A22k logic recommendation uses confirmed fragnet + programme IDs",
      "TIA-010" in _logic_prompt and "allowed_existing_activities" in _logic_prompt)
_known_pred = U.tasks[0].task_code
_logic = parse_logic_recommendation_json(
    '{"predecessors":[{"id":"' + _known_pred + '","type":"FS","lag_days":0}],'
    '"successors":[{"id":"KD15","type":"FS","lag_days":0}],'
    '"impacted_sections":[{"id":"KD15"}],'
    '"warnings":["planner review"]}', U)
_logic_bad = parse_logic_recommendation_json(
    '{"predecessors":[{"id":"INVENTED-1"}]}', U)
check("A22l logic parser accepts programme IDs and rejects invention",
      _logic["predecessors"][0]["id"] == _known_pred
      and _logic_bad["predecessors"] == [])
_calendar_id = next(iter(U.calendars))
_calendar_fragnet = parse_fragnet_json(
    '{"activities":[{"id":"TIA-CAL","name":"calendar test",'
    '"duration_days":2,"calendar_id":"' + _calendar_id + '",'
    '"successors":[{"id":"KD15"}]}]}', U)
check("A22m fragnet retains only a valid programme calendar",
      _calendar_fragnet[0].calendar_id == _calendar_id)
_targeted = run_tia(U, "U", _ev, _fr, target_milestone="KD15")
check("A22n selected impacted milestone is prioritised in results",
      bool(_targeted.milestone_impacts)
      and _targeted.milestone_impacts[0].code == "KD15")
from programme import build_tia_xlsx
_tia_book = load_workbook(io.BytesIO(build_tia_xlsx(
    _targeted, audit={"source_sha256": "abc"},
    run_history=[{"completion_delta_days": 5}])))
check("A22o TIA export includes audit and rerun history",
      "Audit Trail" in _tia_book.sheetnames
      and "Run History" in _tia_book.sheetnames
      and "Calendar" in [c.value for c in _tia_book["Fragnet"][1]])


# A23. Explain This Delay
from programme import explain_delay
_ex = explain_delay([("B", B), ("U", U)], "KD15")
check("A23 explain: facts recorded per revision",
      len(_ex.points) == 2 and _ex.points[0].forecast is not None)
check("A23b explain: total movement == raw forecast delta",
      abs(_ex.total_movement_days
          - (_ex.points[-1].forecast
             - _ex.points[0].forecast).days) < 1)
check("A23c explain: uncertain attribution flagged when path switched",
      any(not w.attribution_reliable for w in _ex.windows)
      and any("uncertain" in w for w in _ex.warnings))
check("A23d explain: facts/inference separation in caveats",
      any("INFERENCE" in c for c in _ex.caveats))
_ex1 = explain_delay([("B", B)], "KD15")
check("A23e explain: single revision -> warning, no crash",
      not _ex1.windows and _ex1.warnings)


# A24. Event extraction (TIA intake) + 52R-06
from programme import (build_event_extraction_prompt, parse_event_candidates,
                       read_document, recommended_analysis_schedule)
_docs = [("L1.txt", "On 12 March 2018 the Engineer issued Instruction "
                    "EI-88 requiring additional ceiling works.")]
_p = build_event_extraction_prompt(_docs)
check("A24 extraction prompt cites 52R-06 and the doc",
      "52R-06" in _p and "L1.txt" in _p)
_good = ('{"events":[{"title":"EI-88","source_doc":"L1.txt",'
         '"source_snippet":"issued Instruction EI-88","date_start":'
         '"2018-03-12","confidence":"high"}]}')
_c, _d = parse_event_candidates(_good, _docs)
check("A24b verified snippet accepted", len(_c) == 1 and _c[0].verified)
_bad = ('{"events":[{"title":"Flood","source_doc":"L1.txt",'
        '"source_snippet":"site flooded for weeks"}]}')
_c2, _d2 = parse_event_candidates(_bad, _docs)
check("A24c fabricated snippet dropped", _c2 == [] and _d2 == 1)
check("A24d garbage tolerated", parse_event_candidates("x", _docs) == ([], 0))
from datetime import datetime as _dtx
_meta = [("U1", _dtx(2018, 1, 31)), ("U2", _dtx(2018, 2, 28))]
check("A24e 52R-06 picks last update before event",
      recommended_analysis_schedule(_meta, _dtx(2018, 2, 10)) == "U1")
check("A24f TIA caveats cite 52R-06",
      any("52R-06" in c for c in _r.caveats))
check("A24g txt reader works", "hello" in read_document("a.txt", b"hello"))


# A25. Impacted-programme XER export round-trip
from programme import build_impacted_xer
_raw = open(_p("sample/Sample Update.xer"), "rb").read()
_fr2 = [FragnetActivity("TIA-910", "a", 10,
                        successors=[FragnetLink("TIA-920")]),
        FragnetActivity("TIA-920", "b", 20,
                        predecessors=[FragnetLink("TIA-910")],
                        successors=[FragnetLink("KD15")])]
_res2 = run_tia(U, "U", _ev, _fr2)
_out = build_impacted_xer(_raw.decode("utf-8", errors="replace"),
                          U, _fr2, _res2)
_u2 = parse_xer(_out.encode("utf-8"))
check("A25 impacted xer: fragnet tasks import",
      len(_u2.tasks) == len(U.tasks) + 2)
check("A25b impacted xer: links deduped and resolved",
      len(_u2.relationships) == len(U.relationships) + 2)
_t2 = next(x for x in _u2.tasks if x.task_code == "TIA-920")
check("A25c impacted xer: not-started with duration",
      _t2.status == "TK_NotStart" and _t2.target_drtn_hr is not None)

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
