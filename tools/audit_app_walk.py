"""Whole-app audit: QA walk of every page + analyst coherence checks.

QA hat: every registered page renders exception-free on the bundled
Harbour Point pair, and again with degenerate inputs (single file).
Analyst hat: the delay story must agree across modules — the documented
+92 calendar days must be what the toolkit reports, and the modules
must not contradict each other.
"""
import sys
import traceback

sys.path.insert(0, ".")

from streamlit.testing.v1 import AppTest

from dcma import parse_xer
from programme import build_inventory
import state as sk

ROOT = "./sample/"
BASE_F = "Harbour Point DCP-03 - Baseline Programme Rev 0.xer"
BUILT_F = "Harbour Point DCP-03 - As-Built Programme Rev 12.xer"

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}"
          + (f" — {detail}" if detail and not cond else ""))


def load(files=(BASE_F, BUILT_F)):
    pool = [(n, parse_xer(open(ROOT + n, "rb").read())) for n in files]
    return pool


POOL = load()
INV = build_inventory(POOL)

# ---------------------------------------------------------------- #
# QA 1 — every page renders exception-free with the full pair       #
# ---------------------------------------------------------------- #
PAGES = [
    ("Data Intake", "views.intake", "intake_tab"),
    ("DCMA 14-Point", "views.dcma_page", "dcma_tab"),
    ("Baseline Critical Path", "views.critical_path", "critical_path_tab"),
    ("Revision Comparison", "views.comparison", "comparison_tab"),
    ("Out-of-Sequence Repair", "views.oos", "oos_tab"),
    ("Float Erosion", "views.float_erosion", "float_erosion_tab"),
    ("Progress S-Curve", "views.progress", "progress_tab"),
    ("Resource Loading", "views.resources", "resources_tab"),
    ("Sequence Coding", "views.sequence", "sequence_tab"),
    ("Hierarchy Rebuild", "views.hierarchy", "hierarchy_tab"),
    ("Milestone Shift Tracker", "views.milestone", "milestone_tab"),
    ("Progress Transfer", "views.progress_transfer", "progress_transfer_tab"),
    ("As-Built Critical Path", "views.asbuilt", "asbuilt_tab"),
    ("Report Assembler", "views.report", "report_tab"),
    ("As-Planned vs As-Built", "views.apab_v2", "apab_v2_tab"),
    ("Time Slice Windows", "views.windows", "windows_tab"),
    ("Impacted As-Planned", "views.impacted_asplanned",
     "impacted_asplanned_tab"),
    ("Collapsed As-Built", "views.collapsed_asbuilt",
     "collapsed_asbuilt_tab"),
    ("Time Impact Analysis", "views.tia", "tia_tab"),
    ("Concurrency (sub)", "views.concurrency", "concurrency_tab"),
    ("Explain This Delay (sub)", "views.explain", "explain_tab"),
]


def _page(mod: str, fn: str):
    # AppTest re-execs this function's SOURCE, so nothing may be
    # captured from an enclosing scope — args come in via kwargs
    import sys
    sys.path.insert(0, ".")
    import importlib
    getattr(importlib.import_module(mod), fn)()


def run_page(mod, fn, pool, inv, extra_state=None):
    at = AppTest.from_function(_page, default_timeout=180,
                               kwargs={"mod": mod, "fn": fn})
    at.session_state[sk.XER_POOL] = pool
    if inv is not None:
        at.session_state[sk.INVENTORY] = inv
    for k, v in (extra_state or {}).items():
        at.session_state[k] = v
    at.run()
    return at


print("\n=== QA 1: every page, full baseline+as-built pair ===")
for title, mod, fn in PAGES:
    try:
        at = run_page(mod, fn, POOL, INV)
        check(f"{title} renders", not at.exception,
              str(at.exception)[:300] if at.exception else "")
    except Exception as exc:
        check(f"{title} renders", False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()

# ---------------------------------------------------------------- #
# QA 2 — degenerate inputs: ONE file only, and NO files             #
# ---------------------------------------------------------------- #
print("\n=== QA 2: degenerate inputs (single file / empty pool) ===")
ONE = load((BUILT_F,))
INV1 = build_inventory(ONE)
for title, mod, fn in PAGES:
    try:
        at = run_page(mod, fn, ONE, INV1)
        check(f"{title} · single file", not at.exception,
              str(at.exception)[:200] if at.exception else "")
    except Exception as exc:
        check(f"{title} · single file", False,
              f"{type(exc).__name__}: {exc}")

for title, mod, fn in PAGES:
    try:
        at = run_page(mod, fn, [], None)
        check(f"{title} · empty pool", not at.exception,
              str(at.exception)[:200] if at.exception else "")
    except Exception as exc:
        check(f"{title} · empty pool", False,
              f"{type(exc).__name__}: {exc}")

# ---------------------------------------------------------------- #
# ANALYST — does the delay story hold together across modules?      #
# ---------------------------------------------------------------- #
print("\n=== ANALYST: cross-module coherence on Harbour Point ===")
base, built = POOL[0][1], POOL[1][1]

from programme import (
    extract_actual_trace, extract_asbuilt_longest_path, keydate_windows,
    planned_vs_actual, track_milestone_shifts,
)

MS = "H-5040"          # Substantial Completion & Taking Over

# 1. the documented story: +92 calendar days on completion
b_ms = {t.task_code: t for t in base.tasks}[MS]
a_ms = {t.task_code: t for t in built.tasks}[MS]
planned_fin = b_ms.target_finish or b_ms.early_finish
actual_fin = a_ms.act_finish or a_ms.early_finish
slip = (actual_fin - planned_fin).days
check("completion slip matches documented +92 d", slip == 92,
      f"got {slip} d ({planned_fin:%Y-%m-%d} -> {actual_fin:%Y-%m-%d})")

# 2. milestone tracker must report the same movement
shifts = track_milestone_shifts(
    [(n, d.project.data_date, d) for n, d in POOL])
row = next((s for s in shifts.series if s.key == MS), None)
_tot = row.total_shift_days if row is not None else None
check("milestone tracker agrees with the raw slip",
      _tot is not None and abs(_tot - slip) <= 1,
      f"tracker {_tot} vs raw {slip}")

# 3. as-built longest path must terminate at the elected milestone
trace = extract_asbuilt_longest_path(built, end_task_code=MS)
check("as-built longest path terminates at the elected milestone",
      trace.activities and trace.activities[-1].task_code == MS,
      trace.activities[-1].task_code if trace.activities else "empty")
check("as-built path is a continuous chain",
      len(trace.links) == max(len(trace.activities) - 1, 0),
      f"{len(trace.activities)} activities, {len(trace.links)} links")

# 4. APvAB delay measured on that path must equal the milestone slip
rows = planned_vs_actual(base, built, trace.codes, date_basis="late")
pf = [r["planned_finish"] for r in rows if r.get("planned_finish")]
af = [r["actual_finish"] for r in rows if r.get("actual_finish")]
delay = round((max(af) - max(pf)).total_seconds() / 86400, 1)
check("APvAB path delay agrees with the milestone slip",
      abs(delay - slip) <= 1.0, f"path {delay} d vs milestone {slip} d")

# 5. actual-sequence candidate must not contradict the logic candidate
seq = extract_actual_trace(POOL, end_task_code=MS, max_gap_days=60)
overlap = len(trace.codes & seq.codes) / max(len(trace.codes), 1)
check("logic and sequence candidates substantially agree",
      overlap >= 0.5, f"{overlap:.0%} overlap")

# 6. key-date windows must sum to the cumulative delay
kd = [a.task_code for a in trace.activities
      if a.task_code != MS][:2] + [MS]
kw = keydate_windows(rows, kd)
if kw:
    acc = round(sum(w["window_delay_days"] for w in kw), 1)
    cum = kw[-1]["cumulative_delay_days"]
    check("window deltas sum to the cumulative delay",
          abs(acc - cum) <= 1.0, f"sum {acc} vs cumulative {cum}")
else:
    check("key-date windows computed", False, "no windows returned")

# 7. no percentages leak into RLPA confidence wording
from programme.rlpa import RLPA_CAVEATS, aggregate_votes
from programme.rlpa import InferredLink
votes = aggregate_votes([[("A", "B", "r")], [("A", "B", "r")],
                         [("A", "B", "r")]])
check("3/3 agreement is the word 'strong', never a number",
      votes and votes[0].confidence == "strong"
      and "%" not in votes[0].confidence, str(votes))
check("standing caveats carry no percentages",
      not any("%" in c for c in RLPA_CAVEATS))

# 8. exports must actually build (bytes, not promises)
from programme import build_simple_xlsx, build_apab_gantt_png
try:
    wb = build_simple_xlsx("audit", sheets={"S": rows[:5]}, notes=["n"])
    check("workbook export builds", len(wb) > 3000, f"{len(wb)} bytes")
except Exception as exc:
    check("workbook export builds", False, str(exc))
try:
    png = build_apab_gantt_png(rows[:12], keydates={},
                               overall_delay_days=delay, title="audit",
                               windows=[], data_date=None)
    check("gantt PNG renders", png and len(png) > 5000,
          f"{len(png) if png else 0} bytes")
except Exception as exc:
    check("gantt PNG renders", False, str(exc))

# 9. path gantt dataset: planned side must come from the BASELINE
from path_studio import dataset_from_xer
ds = dataset_from_xer(built, path_codes=list(trace.codes), basis="b",
                      milestone_code=MS, baseline=base,
                      date_basis="late")
by = {a.code: a for a in ds.activities}
sample = by.get(MS)
check("path-gantt planned dates come from the baseline",
      sample and sample.planned_finish
      and sample.planned_finish[:10] == f"{planned_fin:%Y-%m-%d}",
      f"{sample.planned_finish if sample else None} vs baseline "
      f"{planned_fin:%Y-%m-%d}")
check("path-gantt carries the whole programme, not just the path",
      len(ds.activities) > len(trace.codes),
      f"{len(ds.activities)} activities vs {len(trace.codes)} on path")
check("path-gantt carries recorded relationships",
      len(ds.relationships) > 20, f"{len(ds.relationships)} links")

print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} FAILED")
if FAIL:
    print("FAILURES:")
    for f in FAIL:
        print("  -", f)
sys.exit(1 if FAIL else 0)
