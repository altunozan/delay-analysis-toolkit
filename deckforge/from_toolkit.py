"""One-click forensic report deck from two P6 programmes.

Builds the standard preliminary-review slides straight from a baseline and
an update XER — no UI, fully reproducible:

    1. Top milestone slips (horizontal bar, sorted)
    2. Baseline vs current milestone comparison gantt (slip remarks)
    3. Baseline longest path gantt
    4. Progress S-curve (planned vs actual)

Usage:
    python3 deckforge/from_toolkit.py "sample/Sample Baseline.xer" \
        "sample/Sample Update.xer" -o report_deck.pptx --top 12 \
        --title "Programme review" --agenda chapters
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(1, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import p6_bridge as pb
from data_io import frame_to_bar, frame_to_gantt, frame_to_line
from render_pptx import build_deck
from theme import DEFAULT_THEME, THEMES


def build_report_specs(base, cur, top: int = 12):
    from programme import extract_longest_path

    specs = [
        frame_to_bar(
            pb.milestone_slip_frame(base, cur, top=top),
            title="Top milestone slips (days, + = later)", mode="stacked",
            orientation="horizontal", show_values=True, show_totals=False,
            deltas=[], sort="desc"),
        frame_to_gantt(
            pb.comparison_gantt_frame(base, cur, top=top),
            title="Milestones — baseline vs current",
            show_remarks=True, show_date_labels=True),
    ]

    cp = extract_longest_path(base, "Baseline")
    lp_rows = [
        {"Activity": f"{a.task_code} · {a.name[:36]}",
         "Start": a.early_start or a.early_finish,
         "Finish": a.early_finish or a.early_start,
         "Type": "milestone" if a.is_milestone else "bar",
         "Group": "Longest path", "Style": "solid", "Remark": ""}
        for a in cp.critical[:25]
    ]
    if lp_rows:
        specs.append(frame_to_gantt(
            pd.DataFrame(lp_rows), title="Baseline longest path (top 25)"))

    specs.append(frame_to_line(
        pb.s_curve_frame(base, cur),
        title="Progress S-curve — planned vs actual",
        mode="line", axis_title="% activities finished"))
    return specs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("baseline", help="Baseline .xer")
    ap.add_argument("update", help="Current update .xer")
    ap.add_argument("-o", "--output", default="report_deck.pptx")
    ap.add_argument("--top", type=int, default=12,
                    help="Milestones on the slip/comparison slides")
    ap.add_argument("--title", default="Programme review")
    ap.add_argument("--theme", default="Consulting Blue",
                    choices=list(THEMES))
    ap.add_argument("--agenda", default="none",
                    choices=["none", "front", "chapters"])
    args = ap.parse_args()

    from dcma import parse_xer
    with open(args.baseline, "rb") as fh:
        base = parse_xer(fh.read())
    with open(args.update, "rb") as fh:
        cur = parse_xer(fh.read())

    specs = build_report_specs(base, cur, top=args.top)
    blob = build_deck(specs, THEMES.get(args.theme, DEFAULT_THEME),
                      deck_title=args.title, agenda=args.agenda)
    with open(args.output, "wb") as fh:
        fh.write(blob)
    print(f"Wrote {args.output}: {len(specs)} chart slides "
          f"({len(blob):,} bytes)")


if __name__ == "__main__":
    main()
