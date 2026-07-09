"""DeckForge batch build — a whole deck from one YAML/JSON file, headless.

The deck definition lives in a file you can version-control; the deck becomes
a reproducible artifact. `--watch` rebuilds whenever the definition or any
referenced data file changes (the automation think-cell's Excel links can't
do without opening PowerPoint).

Usage:
    python3 deckforge/build.py deck.yaml
    python3 deckforge/build.py deck.yaml --watch

Definition format (see example_deck.yaml):
    theme: Consulting Blue
    title: Programme review          # optional title slide
    agenda: front                    # none | front | chapters
    harmonise_bars: false
    output: out.pptx
    slides:
      - type: bar                    # bar|clustered|stacked100|combo|line|
                                     # area|waterfall|gantt|mekko|pie|
                                     # doughnut|butterfly|scatter|process|table
        title: Revenue by workstream
        data: revenue.xlsx           # or  data: file.xlsx#SheetName
        inline:                      # ...or inline columns instead of a file
          Category: [FY22, FY23]
          Construction: [420, 465]
        group: 1                     # slides sharing a group share a slide
        # type-specific options: unit, sort, deltas, line_columns,
        # axis_break, orientation, show_values, show_totals, doughnut, ...
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

from data_io import (
    frame_to_bar, frame_to_butterfly, frame_to_gantt, frame_to_line,
    frame_to_mekko, frame_to_pie, frame_to_process, frame_to_scatter,
    frame_to_table, frame_to_waterfall,
)
from render_pptx import build_deck
from specs import DeltaArrow
from theme import DEFAULT_THEME, THEMES


def _load_definition(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if path.endswith(".json"):
        return json.loads(text)
    try:
        import yaml
        return yaml.safe_load(text)
    except ImportError as exc:
        raise SystemExit(
            "PyYAML is not installed — use a .json definition or "
            "`pip install pyyaml`.") from exc


def _frame_for(slide: dict, base_dir: str) -> pd.DataFrame:
    if "inline" in slide:
        return pd.DataFrame(slide["inline"])
    ref = slide.get("data")
    if not ref:
        raise ValueError(f"Slide '{slide.get('title')}' has no data/inline.")
    path, _, sheet = str(ref).partition("#")
    full = path if os.path.isabs(path) else os.path.join(base_dir, path)
    if full.endswith(".csv"):
        return pd.read_csv(full)
    return pd.read_excel(full, sheet_name=sheet or 0)


def _spec_for(slide: dict, df: pd.DataFrame):
    kind = slide["type"]
    title = slide.get("title", kind)
    common = dict(title=title)
    if kind in ("bar", "clustered", "stacked100", "combo"):
        mode = {"bar": "stacked", "clustered": "clustered",
                "stacked100": "stacked100", "combo": "stacked"}[kind]
        deltas = [DeltaArrow(d["from"], d["to"], d.get("mode", "absolute"))
                  for d in slide.get("deltas", [])]
        brk = slide.get("axis_break")
        return frame_to_bar(
            df, **common, mode=mode,
            orientation=slide.get("orientation", "vertical"),
            show_values=slide.get("show_values", True),
            show_totals=slide.get("show_totals", mode == "stacked"),
            deltas=deltas, unit=slide.get("unit", ""),
            sort=slide.get("sort", "none"),
            line_columns=slide.get("line_columns",
                                   [str(df.columns[-1])] if kind == "combo"
                                   else []),
            axis_break=tuple(brk) if brk else None)
    if kind in ("line", "area"):
        return frame_to_line(df, **common, mode=kind,
                             show_values=slide.get("show_values", False),
                             unit=slide.get("unit", ""),
                             axis_title=slide.get("axis_title", ""))
    if kind == "waterfall":
        return frame_to_waterfall(
            df, **common, show_values=slide.get("show_values", True),
            show_connectors=slide.get("show_connectors", True))
    if kind == "gantt":
        today = slide.get("today")
        return frame_to_gantt(
            df, **common,
            today=pd.to_datetime(today).to_pydatetime() if today else None,
            curtains_df=pd.DataFrame(slide["curtains"])
            if slide.get("curtains") else None,
            datelines_df=pd.DataFrame(slide["date_lines"])
            if slide.get("date_lines") else None,
            brackets_df=pd.DataFrame(slide["brackets"])
            if slide.get("brackets") else None,
            show_date_labels=slide.get("show_date_labels", False),
            show_durations=slide.get("show_durations", False),
            show_remarks=slide.get("show_remarks", False),
            weekend_shading=slide.get("weekend_shading", False))
    if kind == "mekko":
        return frame_to_mekko(df, **common,
                              show_values=slide.get("show_values", True))
    if kind in ("pie", "doughnut"):
        return frame_to_pie(df, **common, doughnut=kind == "doughnut",
                            show_pcts=slide.get("show_pcts", True))
    if kind == "butterfly":
        return frame_to_butterfly(
            df, **common, show_values=slide.get("show_values", True),
            unit=slide.get("unit", ""))
    if kind == "scatter":
        quad = slide.get("quadrants")
        return frame_to_scatter(
            df, **common, x_title=slide.get("x_title", ""),
            y_title=slide.get("y_title", ""),
            quadrants=tuple(quad) if quad else None)
    if kind == "process":
        return frame_to_process(df, **common,
                                highlight=slide.get("highlight"))
    if kind == "table":
        return frame_to_table(df, **common)
    raise ValueError(f"Unknown slide type: {kind}")


def build_from_file(path: str) -> str:
    base_dir = os.path.dirname(os.path.abspath(path))
    d = _load_definition(path)

    specs, group_of = [], []
    for slide in d.get("slides", []):
        specs.append(_spec_for(slide, _frame_for(slide, base_dir)))
        group_of.append(slide.get("group"))

    groups, by_id = [], {}
    for spec, gid in zip(specs, group_of):
        if gid is None:
            groups.append([spec])
        elif gid in by_id:
            by_id[gid].append(spec)
        else:
            by_id[gid] = [spec]
            groups.append(by_id[gid])

    template = None
    if d.get("template"):
        tpath = os.path.join(base_dir, d["template"])
        with open(tpath, "rb") as fh:
            template = fh.read()

    blob = build_deck(
        specs, THEMES.get(d.get("theme", ""), DEFAULT_THEME),
        template=template, deck_title=d.get("title"),
        groups=groups, agenda=d.get("agenda", "none"),
        harmonise_bars=bool(d.get("harmonise_bars", False)))

    out = d.get("output", "deck.pptx")
    if not os.path.isabs(out):
        out = os.path.join(base_dir, out)
    with open(out, "wb") as fh:
        fh.write(blob)
    print(f"Wrote {out}: {len(specs)} charts on {len(groups)} slides "
          f"({len(blob):,} bytes)")
    return out


def _watched_files(path: str) -> list[str]:
    base_dir = os.path.dirname(os.path.abspath(path))
    files = [path]
    try:
        d = _load_definition(path)
        for slide in d.get("slides", []):
            ref = slide.get("data")
            if ref:
                p = str(ref).partition("#")[0]
                files.append(p if os.path.isabs(p)
                             else os.path.join(base_dir, p))
        if d.get("template"):
            files.append(os.path.join(base_dir, d["template"]))
    except Exception:  # noqa: BLE001 — broken definition still watched
        pass
    return files


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("definition", help="deck .yaml / .json definition")
    ap.add_argument("--watch", action="store_true",
                    help="rebuild whenever the definition or data changes")
    args = ap.parse_args()

    build_from_file(args.definition)
    if not args.watch:
        return
    print("Watching for changes — Ctrl+C to stop.")
    last = {f: os.path.getmtime(f) for f in _watched_files(args.definition)
            if os.path.exists(f)}
    while True:
        time.sleep(1.0)
        now = {f: os.path.getmtime(f) for f in _watched_files(args.definition)
               if os.path.exists(f)}
        if now != last:
            last = now
            try:
                build_from_file(args.definition)
            except Exception as exc:  # noqa: BLE001 — keep watching
                print(f"Build failed: {exc}")


if __name__ == "__main__":
    main()
