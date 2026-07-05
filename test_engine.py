"""Quick CLI test harness for the DCMA engine (no Streamlit needed).

Usage:
    python3 test_engine.py [path/to/file.xer]

Defaults to "sample/Sample Baseline.xer" when no path is given.
"""

import sys

from dcma import DCMAConfig, parse_xer, run_all_checks

xer_path = sys.argv[1] if len(sys.argv) > 1 else "sample/Sample Baseline.xer"
data = parse_xer(xer_path, DCMAConfig())

print(f"Project: {data.project.short_name}")
print(f"Tasks: {len(data.tasks)}  Relationships: {len(data.relationships)}  "
      f"Calendars: {len(data.calendars)}")
print(f"Data date: {data.project.data_date}\n")

results = run_all_checks(data)
for r in results:
    print(f"Check {r.number:>2} {r.name:<22} [{r.status.value:^4}]  "
          f"{r.metric_value}  (target {r.threshold})")
    if r.affected_ids:
        print(f"        affected: {', '.join(r.affected_ids[:10])}")
