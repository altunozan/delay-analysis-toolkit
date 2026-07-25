"""Field test: every engine against every project family, timed,
tracebacks captured. Usage: python3 field_test.py <PROJECT_DIR> [files...]"""
import glob, sys, time, traceback

from dcma.xer_parser import parse_xer
from dcma.config import DCMAConfig
from dcma.checks import run_all_checks
from dcma.trace import build_dcma_trace
from programme import (build_inventory, extract_longest_path,
                       extract_critical_path, out_of_sequence_flags,
                       build_repair_plan, apply_asbuilt_repairs,
                       compare_revisions, assess_comparison_impact,
                       build_provenance, analyse_windows,
                       track_milestone_shifts,
                       extract_actual_trace, collapse_asbuilt,
                       run_progress_transfer, explain_delay,
                       oos_evolution, planned_vs_actual,
                       analyse_float_erosion, compute_progress)

RESULTS = []

def step(name, fn, *a, **kw):
    t0 = time.time()
    try:
        out = fn(*a, **kw)
        RESULTS.append((name, time.time() - t0, "OK", ""))
        return out
    except Exception as exc:
        tb = traceback.format_exc().strip().split("\n")[-3:]
        RESULTS.append((name, time.time() - t0, type(exc).__name__,
                        " | ".join(l.strip() for l in tb)))
        return None

folder = sys.argv[1]
files = sys.argv[2:] or sorted(glob.glob(folder + "/*.xer"))
cfg = DCMAConfig()

parsed = []
for f in files:
    short = f.split("/")[-1]
    d = step(f"parse {short}", parse_xer, f)
    if d is not None:
        parsed.append((short, d))

if parsed:
    parsed.sort(key=lambda p: (p[1].project.data_date
                               if p[1].project and p[1].project.data_date
                               else __import__("datetime").datetime.min))
    inv = step("inventory", build_inventory, parsed)
    latest_lbl, latest = parsed[-1]
    first_lbl, first = parsed[0]

    step(f"dcma17 {latest_lbl}", run_all_checks, latest, cfg)
    res17 = run_all_checks(latest, cfg) if RESULTS[-1][2] == "OK" else None
    if res17:
        step("dcma traceback", build_dcma_trace, latest, cfg, res17)
    step("longest path (DAG 8h)", extract_longest_path, latest,
         latest_lbl, branch_tolerance_hours=8.0)
    step("float path", extract_critical_path, latest, latest_lbl)
    flags = step("oos flags", out_of_sequence_flags, latest)
    if flags is not None:
        plan = step("oos repair plan", build_repair_plan, latest, flags)
        if plan is not None:
            raw = open([f for f in files
                        if f.endswith(latest_lbl)][0],
                       encoding="latin-1", errors="replace").read()
            step("oos apply+roundtrip", apply_asbuilt_repairs,
                 raw, latest, plan)
    step("float erosion", analyse_float_erosion, parsed)
    step("progress s-curve", compute_progress, parsed[0][1],
         parsed[0][0], parsed[1:])
    step("asbuilt actual trace", extract_actual_trace, parsed)
    step("collapse (empty set)", collapse_asbuilt, latest, latest_lbl,
         set())

    if len(parsed) >= 2:
        cmp_r = step("comparison first->latest", compare_revisions,
                     first, latest, first_lbl, latest_lbl)
        step("impact assessment", assess_comparison_impact,
             first, latest, first_lbl, latest_lbl, comparison=cmp_r)
        step("provenance (all revs)", build_provenance, parsed)
        step("windows+bifurcation", analyse_windows, parsed)
        step("oos evolution", oos_evolution, parsed)
        step("milestone shifts", track_milestone_shifts,
             [(l, d.project.data_date, d) for l, d in parsed])
        step("planned vs actual", planned_vs_actual, first, latest)
        step("progress transfer", run_progress_transfer,
             first, latest, first_lbl, latest_lbl)
        ms = [t for t in latest.tasks if t.is_milestone][:1]
        if ms:
            step("explain delay", explain_delay, parsed,
                 ms[0].task_code)

print(f"\n=== {folder.split('/')[-1]} ===")
worst = 0.0
for name, dt, status, detail in RESULTS:
    mark = "OK " if status == "OK" else "!! "
    worst = max(worst, dt)
    line = f"{mark}{name:32s} {dt:6.1f}s  {status}"
    if status != "OK":
        line += f"  {detail[:150]}"
    print(line)
n_fail = sum(1 for r in RESULTS if r[2] != "OK")
print(f"--- {len(RESULTS)} steps, {n_fail} failed, slowest {worst:.1f}s")
