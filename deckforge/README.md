# DeckForge

Standalone, automated alternative to think-cell: edit a datasheet (or upload
Excel/CSV, or import straight from Primavera P6), preview the chart live, and
export **native, editable PowerPoint** — no manual chart assembly.

Separate from the delay-analysis toolkit in the parent folder; it only
*optionally* reuses the toolkit's XER parser for the P6 → Gantt importer.

## Run

```bash
streamlit run deckforge/app.py --server.port 8502
```

## Test (headless)

```bash
python3 deckforge/test_deckforge.py
```

Builds every chart type, renders through both renderers, checks the shared
maths, and round-trips the generated `.pptx`. Writes `sample_output.pptx`.

## Architecture

```
datasheet / Excel / P6 XER
        │
        ▼
   specs.py          typed ChartSpec IR — ALL derived numbers (totals,
        │            deltas, CAGR, waterfall running sums) computed here
   ┌────┴─────┐
   ▼          ▼
render_plotly  render_pptx
 (dashboard)    (native .pptx)
   theme.py — one palette/font set for both
```

## think-cell feature coverage

| Feature | Export fidelity |
|---|---|
| Stacked / clustered / 100% bars | Native editable chart |
| Difference & CAGR arrows | Overlay shapes; the value axis is pinned so positions are computed deterministically (vertical stacked bars) |
| Waterfall | Native stacked column with invisible base series; signed per-point labels; shape connectors |
| Gantt | Grouped shapes on a date scale (PowerPoint has no native gantt) |
| Gantt curtains | Shaded date-range bands behind the bars, with labels |
| Gantt date lines | Labelled dashed verticals (today, EOT award, data date, …) |
| Gantt brackets | Phase-span brackets above the bars; overlaps auto-stack |
| Gantt bar styles | solid / striped (forecast) / open (outline) per bar |
| Gantt labels | Start/finish dates at bar ends, duration ("87d"), milestone dates |
| Gantt remarks | Right-hand remark/responsibility column |
| Gantt shared rows | Items with the same label share a row (actual + striped forecast) |
| Gantt calendar | Year + month header (quarters on long spans); weekend shading ≤ ~4 months |
| Marimekko | Grouped shapes |
| Table / agenda | Native PowerPoint table |
| Corporate template | Upload a `.pptx`/`.potx`; slides inherit its master |

Known limits: arrow overlays don't reflow if someone edits the chart data
inside PowerPoint afterwards (regenerate the deck instead — that's the point),
and overlay alignment assumes PowerPoint's default plot-area layout
(`_INSET_*` constants in `render_pptx.py` tune it).
