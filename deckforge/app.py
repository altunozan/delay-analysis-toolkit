"""DeckForge — automated think-cell-style chart & deck builder (standalone).

A separate product from the delay-analysis toolkit: edit data like a
think-cell datasheet, preview instantly, and export a native, editable
PowerPoint deck plus an interactive dashboard view — no manual chart work.

Run with:  streamlit run deckforge/app.py --server.port 8502
"""

from __future__ import annotations

import os
import pickle
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Parent repo on the path too, so the optional P6 (.xer) importer can reuse
# the toolkit's parser when DeckForge lives alongside it. Fully optional.
sys.path.insert(1, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import streamlit as st

import render_plotly
import samples
from data_io import (
    frame_to_bar, frame_to_butterfly, frame_to_gantt, frame_to_line,
    frame_to_mekko, frame_to_pie, frame_to_process, frame_to_scatter,
    frame_to_table, frame_to_waterfall, load_frame,
)
from render_pptx import build_deck
from specs import DeltaArrow, GanttItem, GanttSpec, spec_kind
from theme import DEFAULT_THEME, THEMES

st.set_page_config(page_title="DeckForge", page_icon="📊", layout="wide")

CHART_TYPES = {
    "Stacked bar": ("bar", "stacked"),
    "Clustered bar": ("bar", "clustered"),
    "100% stacked bar": ("bar", "stacked100"),
    "Combo (bar + line)": ("combo", "stacked"),
    "Line": ("line", "line"),
    "Area": ("line", "area"),
    "Waterfall": ("waterfall", None),
    "Gantt / timeline": ("gantt", None),
    "Marimekko": ("mekko", None),
    "Pie / doughnut": ("pie", None),
    "Butterfly": ("butterfly", None),
    "Scatter / bubble": ("scatter", None),
    "Process flow": ("process", None),
    "Table / agenda": ("table", None),
}

DEFAULT_TITLES = {
    "bar": "Revenue development by workstream",
    "combo": "Revenue by workstream vs fit-out trend",
    "line": "Progress S-curve — planned vs actual",
    "waterfall": "Delay build-up to forecast completion (days)",
    "gantt": "Summary programme",
    "mekko": "Market composition by segment and region",
    "pie": "Cost split by package",
    "butterfly": "Planned vs actual crew by trade",
    "scatter": "Package risk map",
    "process": "Claim preparation process",
    "table": "Agenda & status",
}

UNITS = {"(none)": "", "thousands (k)": "k", "millions (m)": "m",
         "billions (bn)": "bn"}


# The deck survives page reloads / app restarts: specs are plain dataclasses,
# autosaved to disk on every mutation.
AUTOSAVE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        ".deckforge_autosave.pkl")


def _deck() -> list:
    if "deck" not in st.session_state:
        deck = []
        try:
            with open(AUTOSAVE, "rb") as fh:
                deck = pickle.load(fh)
        except Exception:  # noqa: BLE001 — missing/stale autosave is fine
            pass
        st.session_state["deck"] = deck
    return st.session_state["deck"]


def _save_deck() -> None:
    try:
        with open(AUTOSAVE, "wb") as fh:
            pickle.dump(st.session_state.get("deck", []), fh)
    except OSError:
        pass


def _state_df(kind: str) -> pd.DataFrame:
    key = f"df_{kind}"
    if key not in st.session_state:
        st.session_state[key] = samples.SAMPLE_FRAMES[kind]()
    return st.session_state[key]


def _sidebar():
    with st.sidebar:
        st.markdown("## 🎨 Theme")
        name = st.selectbox("Colour theme", list(THEMES),
                            label_visibility="collapsed")
        theme = THEMES.get(name, DEFAULT_THEME)
        st.markdown(
            "".join(
                f'<span style="display:inline-block;width:26px;height:26px;'
                f'border-radius:4px;margin-right:4px;background:{c}"></span>'
                for c in theme.palette
            ),
            unsafe_allow_html=True,
        )
        st.divider()
        deck = _deck()
        st.markdown(f"## 🗂 Deck — {len(deck)} slide(s)")
        for s in deck:
            st.caption(f"• {spec_kind(s)}: {s.title[:42]}")
        if deck and st.button("Clear deck", use_container_width=True):
            st.session_state["deck"] = []
            _save_deck()
            st.rerun()
    return theme


def _arrows_ui(categories: list[str]) -> list[DeltaArrow]:
    arrows: list[dict] = st.session_state.setdefault("arrows", [])
    with st.expander("↔️ Difference / CAGR arrows (think-cell style)",
                     expanded=bool(arrows)):
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
        frm = c1.selectbox("From", categories, index=0, key="arr_from")
        to = c2.selectbox("To", categories,
                          index=len(categories) - 1, key="arr_to")
        mode = c3.selectbox("Mode", ["absolute", "percent", "cagr"],
                            key="arr_mode")
        c4.markdown("<div style='height:1.75em'></div>",
                    unsafe_allow_html=True)
        if c4.button("Add", key="arr_add", use_container_width=True):
            if frm != to:
                arrows.append({"from": frm, "to": to, "mode": mode})
                st.rerun()
        if arrows:
            for k, a in enumerate(arrows):
                cc1, cc2 = st.columns([6, 1])
                cc1.write(f"`{a['from']}` → `{a['to']}`  ·  {a['mode']}")
                if cc2.button("✕", key=f"arr_del_{k}"):
                    arrows.pop(k)
                    st.rerun()
    return [
        DeltaArrow(a["from"], a["to"], a["mode"])
        for a in arrows
        if a["from"] in categories and a["to"] in categories
    ]


def _p6_import_ui() -> None:
    with st.expander("📥 Import from Primavera P6 (.xer)"):
        st.caption("Prefills the Gantt datasheet from a P6 programme — "
                   "milestones or the longest path.")
        try:
            from dcma import parse_xer
        except ImportError:
            st.info("P6 import needs the delay-analysis toolkit next to "
                    "DeckForge (dcma package not found).")
            return
        up = st.file_uploader("XER file", type=["xer"], key="p6_up")
        mode = st.radio("Import", ["Milestones", "Longest path"],
                        horizontal=True, key="p6_mode")
        limit = st.slider("Max rows", 5, 60, 25, key="p6_limit")
        if up is None or not st.button("Load into datasheet", key="p6_go"):
            return
        try:
            data = parse_xer(up.getvalue())
        except Exception as exc:  # noqa: BLE001 — surface parser errors
            st.error(f"Could not parse XER: {exc}")
            return
        rows = []
        if mode == "Milestones":
            ms = [t for t in data.tasks if t.is_milestone]
            ms.sort(key=lambda t: (t.act_finish or t.act_start
                                   or t.early_finish or t.early_start
                                   or datetime.max))
            for t in ms[:limit]:
                when = (t.act_finish or t.act_start or t.early_finish
                        or t.early_start or t.target_finish)
                rows.append({"Activity": f"{t.task_code} · {t.name[:40]}",
                             "Start": when, "Finish": when,
                             "Type": "milestone", "Group": "Milestones"})
        else:
            try:
                from programme import extract_longest_path
                cp = extract_longest_path(data, up.name)
                acts = cp.critical[:limit]
            except Exception as exc:  # noqa: BLE001
                st.error(f"Longest-path trace failed: {exc}")
                return
            for a in acts:
                rows.append({
                    "Activity": f"{a.task_code} · {a.name[:40]}",
                    "Start": a.early_start or a.early_finish,
                    "Finish": a.early_finish or a.early_start,
                    "Type": "milestone" if a.is_milestone else "bar",
                    "Group": "Longest path",
                })
        if not rows:
            st.warning("Nothing importable found in this XER.")
            return
        st.session_state["df_gantt"] = pd.DataFrame(rows)
        st.success(f"Loaded {len(rows)} rows into the datasheet.")
        st.rerun()


def chart_builder_tab(theme) -> None:
    c_type, c_title = st.columns([1, 2])
    options = list(CHART_TYPES)
    # Deep link: ?chart=Waterfall preselects the type (also handy for demos).
    linked = st.query_params.get("chart", "")
    default_idx = options.index(linked) if linked in options else 0
    choice = c_type.selectbox("Chart type", options, index=default_idx)
    kind, bar_mode = CHART_TYPES[choice]
    title = c_title.text_input("Chart title", DEFAULT_TITLES[kind],
                               key=f"title_{kind}")

    with st.expander("📄 Load data from Excel / CSV"):
        st.caption("First column = categories / labels; remaining columns = "
                   "series (Gantt: Activity, Start, Finish, Type, Group).")
        up = st.file_uploader("File", type=["xlsx", "csv"],
                              key=f"up_{kind}")
        if up is not None and st.button("Replace datasheet", key=f"rep_{kind}"):
            try:
                st.session_state[f"df_{kind}"] = load_frame(up)
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not read file: {exc}")

    if kind == "gantt":
        _p6_import_ui()

    st.markdown("**Datasheet** — edit like a think-cell sheet; the chart "
                "updates live.")
    col_cfg = None
    if kind == "gantt":
        col_cfg = {
            "Start": st.column_config.DatetimeColumn("Start",
                                                     format="YYYY-MM-DD"),
            "Finish": st.column_config.DatetimeColumn("Finish",
                                                      format="YYYY-MM-DD"),
            "Type": st.column_config.SelectboxColumn(
                "Type", options=["bar", "milestone"]),
            "Style": st.column_config.SelectboxColumn(
                "Style", options=["solid", "striped", "open"],
                help="striped = forecast/tentative, open = outline only"),
        }
    df = st.data_editor(_state_df(kind), num_rows="dynamic",
                        use_container_width=True, key=f"editor_{kind}",
                        column_config=col_cfg)

    # ---- options + spec ------------------------------------------------
    if kind in ("bar", "combo"):
        o1, o2, o3 = st.columns(3)
        orientation = (o1.radio("Orientation", ["vertical", "horizontal"],
                                horizontal=True, key="bar_orient")
                       if kind == "bar" else "vertical")
        show_values = o2.toggle("Segment labels", value=True, key="bar_vals")
        show_totals = o3.toggle("Totals", value=bar_mode == "stacked",
                                key="bar_tots", disabled=bar_mode != "stacked")
        line_cols: list[str] = []
        if kind == "combo":
            num_cols = [str(c) for c in df.columns[1:]]
            line_cols = o1.multiselect("Line series", num_cols,
                                       default=num_cols[-1:],
                                       key="combo_lines")
        with st.expander("⚙️ Advanced — units, sorting, axis break"):
            a1, a2, a3 = st.columns(3)
            unit = UNITS[a1.selectbox("Unit scaling", list(UNITS),
                                      key="bar_unit")]
            sort = a2.selectbox("Sort categories", ["none", "desc", "asc"],
                                key="bar_sort")
            brk = None
            if kind == "bar" and a3.toggle("Value-axis break",
                                           key="bar_brk"):
                b1, b2 = st.columns(2)
                lo = b1.number_input("Break from", value=250.0,
                                     key="bar_brk_lo")
                hi = b2.number_input("Break to", value=550.0,
                                     key="bar_brk_hi")
                if hi > lo > 0:
                    brk = (lo, hi)
                    st.caption("ℹ️ With a break the PowerPoint bars are "
                               "drawn as shapes (a native chart can't "
                               "compress its own axis). Arrows are "
                               "disabled.")
        cats = [str(c) for c in df.iloc[:, 0].dropna()]
        deltas = (_arrows_ui(cats)
                  if bar_mode == "stacked" and len(cats) > 1 and not brk
                  else [])
        spec = frame_to_bar(df, title=title, mode=bar_mode,
                            orientation=orientation, show_values=show_values,
                            show_totals=show_totals, deltas=deltas,
                            unit=unit, sort=sort, line_columns=line_cols,
                            axis_break=brk)
        if deltas and orientation == "horizontal":
            st.caption("ℹ️ Difference arrows export to PowerPoint for "
                       "vertical stacked bars; the dashboard shows both.")
    elif kind == "line":
        o1, o2 = st.columns(2)
        spec = frame_to_line(
            df, title=title, mode=bar_mode,
            show_values=o1.toggle("Value labels", False, key="ln_vals"),
            unit=UNITS[o2.selectbox("Unit scaling", list(UNITS),
                                    key="ln_unit")],
        )
    elif kind == "pie":
        o1, o2 = st.columns(2)
        spec = frame_to_pie(
            df, title=title,
            doughnut=o1.toggle("Doughnut", False, key="pie_dough"),
            show_pcts=o2.toggle("Percent labels", True, key="pie_pcts"),
        )
    elif kind == "butterfly":
        spec = frame_to_butterfly(
            df, title=title,
            show_values=st.toggle("Value labels", True, key="bf_vals"),
        )
        st.caption("First numeric column = left wing, second = right wing.")
    elif kind == "scatter":
        o1, o2, o3 = st.columns(3)
        x_t = o1.text_input("X axis title", "Delay risk", key="sc_x")
        y_t = o2.text_input("Y axis title", "Cost impact", key="sc_y")
        quad = None
        if o3.toggle("Quadrant lines", True, key="sc_quad"):
            q1, q2 = st.columns(2)
            quad = (q1.number_input("Quadrant X", value=60.0, key="sc_qx"),
                    q2.number_input("Quadrant Y", value=60.0, key="sc_qy"))
        spec = frame_to_scatter(df, title=title, x_title=x_t, y_title=y_t,
                                quadrants=quad)
        st.caption("Columns: Label, X, Y, Size (blank = plain scatter), "
                   "Group.")
    elif kind == "process":
        steps_n = len(df.dropna(how="all"))
        hl = st.selectbox(
            "Highlight step", ["(none)"] + [str(v) for v in
                                            df.iloc[:, 0].dropna()],
            key="pr_hl")
        hl_idx = None
        labels = [str(v) for v in df.iloc[:, 0].dropna()]
        if hl != "(none)" and hl in labels:
            hl_idx = labels.index(hl)
        spec = frame_to_process(df, title=title, highlight=hl_idx)
    elif kind == "waterfall":
        o1, o2 = st.columns(2)
        spec = frame_to_waterfall(
            df, title=title,
            show_values=o1.toggle("Value labels", True, key="wf_vals"),
            show_connectors=o2.toggle("Connectors", True, key="wf_conn"),
        )
    elif kind == "gantt":
        o1, o2, o3, o4, o5 = st.columns(5)
        use_today = o1.toggle("Today line", value=False, key="g_today")
        today = (pd.Timestamp(o2.date_input("Today", key="g_today_d"))
                 .to_pydatetime() if use_today else None)
        show_dates = o3.toggle("Date labels", value=False, key="g_dates")
        show_dur = o4.toggle("Durations", value=False, key="g_dur")
        show_rem = o5.toggle("Remarks column", value=False, key="g_rem")

        date_col = st.column_config.DatetimeColumn(format="YYYY-MM-DD")
        with st.expander("🪟 Curtains — shaded date ranges"):
            st.caption("think-cell curtain: a tinted band across the chart "
                       "(shutdowns, embargo windows, seasonal constraints).")
            if "df_curtains" not in st.session_state:
                st.session_state["df_curtains"] = samples.gantt_curtains_frame()
            cur_df = st.data_editor(
                st.session_state["df_curtains"], num_rows="dynamic",
                use_container_width=True, key="ed_curtains",
                column_config={"Start": date_col, "End": date_col})
        with st.expander("📏 Date lines — labelled vertical dates"):
            if "df_datelines" not in st.session_state:
                st.session_state["df_datelines"] = samples.gantt_datelines_frame()
            dl_df = st.data_editor(
                st.session_state["df_datelines"], num_rows="dynamic",
                use_container_width=True, key="ed_datelines",
                column_config={"Date": date_col})
        with st.expander("⌐¬ Brackets — phase spans above the bars"):
            if "df_brackets" not in st.session_state:
                st.session_state["df_brackets"] = samples.gantt_brackets_frame()
            br_df = st.data_editor(
                st.session_state["df_brackets"], num_rows="dynamic",
                use_container_width=True, key="ed_brackets",
                column_config={"Start": date_col, "End": date_col})
        weekend = st.toggle(
            "Weekend shading (drawn when the span is ≤ ~4 months)",
            value=False, key="g_wknd")

        spec = frame_to_gantt(
            df, title=title, today=today, curtains_df=cur_df,
            datelines_df=dl_df, brackets_df=br_df,
            show_date_labels=show_dates, show_durations=show_dur,
            show_remarks=show_rem, weekend_shading=weekend)
        st.caption("💡 Rows with the same Activity share one chart row — "
                   "use it for actual + striped forecast segments.")
    elif kind == "mekko":
        spec = frame_to_mekko(
            df, title=title,
            show_values=st.toggle("Share labels", True, key="mk_vals"))
    else:
        spec = frame_to_table(df, title=title)

    fig = render_plotly.render(spec, theme)
    st.plotly_chart(fig, use_container_width=True, theme=None)

    b1, b2, _sp = st.columns([1.2, 1.2, 4])
    if b1.button("➕ Add to deck", type="primary"):
        _deck().append(spec)
        _save_deck()
        st.toast(f"Added “{spec.title}” to the deck "
                 f"({len(st.session_state['deck'])} slides).")
        st.rerun()
    if b2.button("🖼 Render PNG", key="png_go",
                 help="High-res PNG of this chart (for emails/reports)."):
        try:
            st.session_state["png"] = fig.to_image(
                format="png", width=1600, height=900, scale=2)
        except Exception as exc:  # noqa: BLE001 — kaleido missing/broken
            st.error(f"PNG export needs the 'kaleido' package: {exc}")
    if st.session_state.get("png"):
        st.download_button("⬇️ Download PNG", st.session_state["png"],
                           file_name="chart.png", mime="image/png",
                           key="png_dl")


def deck_tab(theme) -> None:
    deck: list = _deck()
    if not deck:
        st.info("The deck is empty — build a chart and click "
                "**Add to deck**.")
        return

    for i, spec in enumerate(deck):
        c1, c2, c3, c4 = st.columns([8, 1, 1, 1])
        c1.markdown(f"**{i + 1}. {spec.title}**  ·  {spec_kind(spec)}")
        if c2.button("⬆️", key=f"up_{i}", disabled=i == 0):
            deck[i - 1], deck[i] = deck[i], deck[i - 1]
            _save_deck()
            st.rerun()
        if c3.button("⬇️", key=f"dn_{i}", disabled=i == len(deck) - 1):
            deck[i + 1], deck[i] = deck[i], deck[i + 1]
            _save_deck()
            st.rerun()
        if c4.button("🗑", key=f"rm_{i}"):
            deck.pop(i)
            _save_deck()
            st.rerun()

    st.divider()
    c1, c2 = st.columns([2, 2])
    deck_title = c1.text_input("Title slide (blank = none)",
                               "Programme review")
    template_bytes = None
    with c2.expander("🏷 Use a corporate template (.pptx / .potx)"):
        tmpl = st.file_uploader("Template", type=["pptx", "potx"],
                                key="tmpl_up")
        if tmpl is not None:
            template_bytes = tmpl.getvalue()
            st.caption(f"Slides render onto “{tmpl.name}” layouts.")

    with st.expander("📐 Layout — agenda, grid, harmonised scales"):
        a1, a2 = st.columns(2)
        agenda = a1.selectbox(
            "Agenda slides", ["None", "Front only", "Chapter dividers"],
            key="deck_agenda")
        agenda_arg = {"None": "none", "Front only": "front",
                      "Chapter dividers": "chapters"}[agenda]
        harmonise = a2.toggle(
            "Same value-axis scale on all stacked bar charts",
            value=False, key="deck_harmonise",
            help="Makes stacked bar totals visually comparable slide to "
                 "slide, think-cell's 'same scale' option.")

        st.caption("Group slides into 2-up / 4-up layouts (indices from "
                   "the list above, comma-separated, one group per line; "
                   "e.g. `1,2` then `3` puts slides 1+2 side by side, "
                   "slide 3 alone). Leave blank for one chart per slide.")
        grid_text = st.text_area("Slide groups", value="", height=70,
                                 key="deck_groups",
                                 placeholder="1,2\n3\n4,5,6,7")
        groups_arg = None
        if grid_text.strip():
            try:
                groups_arg = []
                seen = set()
                for line in grid_text.strip().splitlines():
                    idxs = [int(x.strip()) - 1 for x in line.split(",")
                            if x.strip()]
                    if not idxs:
                        continue
                    groups_arg.append([deck[i] for i in idxs])
                    seen.update(idxs)
                for i in range(len(deck)):
                    if i not in seen:
                        groups_arg.append([deck[i]])
            except (ValueError, IndexError) as exc:
                st.error(f"Couldn't parse slide groups: {exc}")
                groups_arg = None

    try:
        pptx_bytes = build_deck(deck, theme, template=template_bytes,
                                deck_title=deck_title.strip() or None,
                                groups=groups_arg, agenda=agenda_arg,
                                harmonise_bars=harmonise)
    except Exception as exc:  # noqa: BLE001 — template quirks surface here
        st.error(f"Deck build failed: {exc}")
        return
    st.download_button(
        f"⬇️ Download PowerPoint ({len(deck)} chart slides)",
        data=pptx_bytes,
        file_name="deckforge.pptx",
        mime=("application/vnd.openxmlformats-officedocument"
              ".presentationml.presentation"),
        type="primary",
    )
    st.caption("Bar charts, waterfalls and tables are native, editable "
               "PowerPoint objects — colleagues can restyle them or edit "
               "the data in PowerPoint. Gantt and Marimekko slides are "
               "grouped shapes.")


def help_tab() -> None:
    st.markdown("""
### think-cell ⇄ DeckForge mapping

| think-cell feature | DeckForge | In the exported .pptx |
|---|---|---|
| Datasheet | Editable grid (or Excel/CSV upload) | — |
| Stacked / clustered / 100% chart | Bar chart types | **Native editable chart** |
| Difference & CAGR arrows | Arrows panel on stacked bars | Overlay shapes, positioned automatically |
| Waterfall | Waterfall type (signed values + totals) | **Native chart** (invisible-base technique) |
| Gantt | Gantt type — or import direct from P6 (.xer) | Grouped shapes on a date scale |
| Gantt: curtain | Curtains editor (shaded date ranges) | Tinted rectangles behind bars |
| Gantt: date lines | Date lines editor (today, EOT, data date …) | Dashed labelled lines |
| Gantt: brackets | Brackets editor (phase spans, auto-stacked) | Bracket shapes above bars |
| Gantt: bar styles | Style column — solid / striped / open | Solid, hatched or outline bars |
| Gantt: labels | Toggles: dates at bar ends, durations, remarks column | Positioned textboxes |
| Gantt: shared rows | Same Activity name = same row (actual + forecast) | Multiple bars per row |
| Gantt: calendar | Automatic month/quarter scale | Year + month header rows |
| Marimekko | Marimekko type | Grouped shapes |
| Agenda | Table type | **Native table** |

**Why this beats the manual workflow:** the datasheet *is* the chart —
regenerate the entire deck after a data change with one click, instead of
re-dragging labels and arrows slide by slide.

**Tips**
- Values in the waterfall sheet are *signed* movements; tick **Is total**
  for anchor columns (the running total is computed for you).
- CAGR arrows need positive start/end totals and at least one period.
- Upload your corporate template on the Deck tab and every slide inherits
  its master, fonts and page size.
""")


def main() -> None:
    theme = _sidebar()
    st.title("DeckForge")
    st.caption("Automated think-cell-style charts → native PowerPoint + "
               "interactive dashboard. Standalone tool.")
    t1, t2, t3 = st.tabs(["📈 Chart builder", "🗂 Deck & export", "❓ Help"])
    with t1:
        chart_builder_tab(theme)
    with t2:
        deck_tab(theme)
    with t3:
        help_tab()


if __name__ == "__main__":
    main()
