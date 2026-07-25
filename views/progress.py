"""Progress S-Curve."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import state as sk
from programme import (
    WEIGHT_OPTIONS, build_progress_prompt, build_progress_xlsx,
    compute_progress,
)
from programme.narrative import DEFAULT_TEMPLATES
from views._shared import ai_narrative_panel, get_parsed_files


def progress_tab() -> None:
    st.caption(
        "Planned cumulative progress from the baseline vs recorded progress "
        "from the updates — slippage appears as the horizontal gap between "
        "the curves."
    )
    files = get_parsed_files()
    inv = st.session_state.get(sk.INVENTORY)
    if not files or inv is None:
        st.info("Upload programmes in the **Data Intake** tab first.")
        return
    if inv.baseline is None or len(files) < 2:
        st.info("A baseline plus at least one update are needed for the "
                "S-curve comparison.")
        return

    pool = dict(files)
    base_name = inv.baseline.file_name
    updates = [(r.file_name, pool[r.file_name])
               for r in inv.revisions if r.file_name != base_name]

    scheme_label = st.radio(
        "Progress weighting", list(WEIGHT_OPTIONS.values()), horizontal=True,
        help="How much each activity contributes to overall percent "
             "complete.")
    scheme = next(k for k, v in WEIGHT_OPTIONS.items()
                  if v == scheme_label)

    res = compute_progress(pool[base_name], base_name, updates,
                           weight_scheme=scheme)
    if not res.planned_curve:
        for w in res.warnings:
            st.warning(w)
        return

    m1, m2, m3 = st.columns(3)
    m1.metric("Planned at data date",
              f"{res.planned_pct_at_dd:.1f}%"
              if res.planned_pct_at_dd is not None else "—")
    m2.metric("Recorded at data date",
              f"{res.recorded_pct_at_dd:.1f}%"
              if res.recorded_pct_at_dd is not None else "—")
    m3.metric("Time offset",
              f"{res.time_offset_days:+.0f} d"
              if res.time_offset_days is not None else "—",
              help="Positive = the recorded level of progress was planned "
                   "to be reached that many days earlier.")

    for w in res.warnings:
        (st.success if w.startswith("Favourable") else st.warning)(w)

    rows = ([{"Date": p.date, "Cum %": p.cum_pct, "Series": "Planned"}
             for p in res.planned_curve]
            + [{"Date": p.date, "Cum %": p.cum_pct, "Series": "As-recorded"}
               for p in res.recorded_curve])
    layers = [
        alt.Chart(pd.DataFrame(rows)).mark_line(point=True)
        .encode(
            x=alt.X("Date:T", title=None, axis=alt.Axis(format="%b %Y")),
            y=alt.Y("Cum %:Q", title="Cumulative progress (%)",
                    scale=alt.Scale(domain=[0, 100])),
            color=alt.Color("Series:N", title=None,
                            scale=alt.Scale(
                                domain=["Planned", "As-recorded"],
                                range=["#14324A", "#9B3227"]),
                            legend=alt.Legend(orient="top")),
            tooltip=[alt.Tooltip("Date:T", format="%b %Y"), "Series",
                     alt.Tooltip("Cum %:Q", format=".1f")],
        )
    ]
    pts = [{"Date": rp.data_date, "Cum %": rp.recorded_pct,
            "Revision": rp.label}
           for rp in res.revision_points
           if rp.data_date and rp.recorded_pct is not None]
    if pts:
        layers.append(
            alt.Chart(pd.DataFrame(pts)).mark_point(
                shape="diamond", size=140, filled=True, color="#B07A24")
            .encode(x="Date:T", y="Cum %:Q",
                    tooltip=["Revision",
                             alt.Tooltip("Date:T", format="%d %b %Y"),
                             alt.Tooltip("Cum %:Q", format=".1f")]))
    st.altair_chart(alt.layer(*layers).properties(height=380),
                    width="stretch")
    st.caption("◆ = each revision's overall recorded % at its data date.")

    if res.revision_points:
        st.dataframe(pd.DataFrame([{
            "Revision": rp.label,
            "Data date": (f"{rp.data_date:%Y-%m-%d}"
                          if rp.data_date else "—"),
            "Recorded %": rp.recorded_pct,
            "Planned %": rp.planned_pct,
            "Gap (pts)": (round(rp.planned_pct - rp.recorded_pct, 1)
                          if rp.planned_pct is not None
                          and rp.recorded_pct is not None else None),
        } for rp in res.revision_points]),
            width="stretch", hide_index=True)

    with st.expander("Standing caveats (always apply)"):
        for c in res.caveats:
            st.write("•", c)

    narrative = ai_narrative_panel(
        f"nar_progress_{scheme}",
        lambda tmpl: build_progress_prompt(res, tmpl),
        "progress",
        DEFAULT_TEMPLATES["progress"],
    )
    st.download_button(
        "⬇️ Download S-curve report (Excel)",
        data=build_progress_xlsx(res, narrative),
        file_name="progress_scurve_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
