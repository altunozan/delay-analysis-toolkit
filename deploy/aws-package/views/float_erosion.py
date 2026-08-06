"""Float Erosion."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import state as sk
from programme import (
    float_appendix,
    analyse_float_erosion, build_float_erosion_prompt,
    build_float_erosion_xlsx,
)
from programme.narrative import DEFAULT_TEMPLATES
from views._shared import ai_narrative_panel, get_parsed_files


def float_erosion_tab() -> None:
    st.caption(
        "How the programme's scheduling flexibility changed across "
        "revisions: float profile per revision and float consumption per "
        "window."
    )
    files = get_parsed_files()
    inv = st.session_state.get(sk.INVENTORY)
    if not files or inv is None or len(files) < 2:
        st.info("Upload at least two programmes in the **Data Intake** tab "
                "first.")
        return

    near = st.number_input("Near-critical threshold (days)",
                           1.0, 100.0, 10.0, 1.0)
    pool = dict(files)
    ordered = [(r.file_name, pool[r.file_name]) for r in inv.revisions]
    res = analyse_float_erosion(ordered, near_days=near)

    # Float exists only on INCOMPLETE work: on a fully complete
    # as-built every float statistic is None and the headline read
    # em-dashes that contradicted the baseline's 32 critical
    # activities shown one page over. Headline the LAST revision that
    # still has a remaining network, and say which one it is.
    populated = [s for s in res.snapshots if s.incomplete_count > 0]
    last = populated[-1] if populated else res.snapshots[-1]
    if not populated:
        st.info("Every revision in the pool is fully complete — total "
                "float exists only on remaining work, so there is no "
                "float profile to erode. The table below still shows "
                "each revision's population.")
    elif last is not res.snapshots[-1]:
        st.info(f"The latest revision is fully complete (no remaining "
                "work carries float). Headline figures below are the "
                f"last revision WITH a remaining network: {last.label}.")
    m1, m2, m3, m4 = st.columns(4)
    _hdr = f" ({last.label})" if populated else ""
    m1.metric(f"Median float{_hdr}",
              f"{last.median_float:+.0f} d"
              if last.median_float is not None else "—")
    m2.metric("Negative-float activities", last.negative_count)
    m3.metric("Critical (TF ≤ 0)", last.critical_count)
    m4.metric("Minimum float",
              f"{last.min_float:+.0f} d"
              if last.min_float is not None else "—")

    for w in res.warnings:
        (st.success if w.startswith("Favourable") else st.warning)(w)

    prof = []
    for s in res.snapshots:
        if s.data_date is None:
            continue
        # None values must never reach a chart layer — Vega renders an
        # empty panel with infinite-extent warnings instead of a chart
        if s.median_float is not None:
            prof.append(
                {"Data date": s.data_date, "Revision": s.label,
                 "Metric": "Median float (d)", "Value": s.median_float})
        if s.incomplete_count > 0:
            prof.append(
                {"Data date": s.data_date, "Revision": s.label,
                 "Metric": "Negative-float count",
                 "Value": s.negative_count})
    if not prof:
        st.caption("No float profile to chart — no revision carries "
                   "remaining work with stored float.")
    if prof:
        st.altair_chart(
            alt.Chart(pd.DataFrame(prof)).mark_line(point=True)
            .encode(
                x=alt.X("Data date:T", title=None,
                        axis=alt.Axis(format="%b %Y")),
                y=alt.Y("Value:Q", title=None),
                color=alt.Color("Metric:N", title=None,
                                legend=alt.Legend(orient="top")),
                tooltip=["Revision", "Metric", "Value"],
            ).properties(height=260).facet(
                column=alt.Column("Metric:N", title=None)
            ).resolve_scale(y="independent"),
            width="stretch",
        )

    st.subheader("Float profile by revision")
    st.dataframe(pd.DataFrame([{
        "Revision": s.label,
        "Data date": f"{s.data_date:%Y-%m-%d}" if s.data_date else "—",
        "Incomplete": s.incomplete_count,
        "Median TF (d)": s.median_float,
        "Min TF (d)": s.min_float,
        "Critical (TF ≤ 0)": s.critical_count,
        "Negative": s.negative_count,
        f"Near (≤ {near:.0f}d)": s.near_count,
    } for s in res.snapshots]), width="stretch", hide_index=True)

    for w in res.windows:
        if w.top_eroders or w.top_gainers:
            with st.expander(
                f"Window {w.index}: {w.from_label} → {w.to_label} — "
                f"median Δ {w.median_delta:+.0f}d, {w.eroded_count} eroded, "
                f"{w.gained_count} gained"
            ):
                st.dataframe(pd.DataFrame([{
                    "Direction": "eroded", "Activity ID": d.task_code,
                    "Activity": d.name, "TF was (d)": d.old_tf,
                    "TF now (d)": d.new_tf, "Delta (d)": round(d.delta, 1),
                } for d in w.top_eroders] + [{
                    "Direction": "gained", "Activity ID": d.task_code,
                    "Activity": d.name, "TF was (d)": d.old_tf,
                    "TF now (d)": d.new_tf, "Delta (d)": round(d.delta, 1),
                } for d in w.top_gainers]),
                    width="stretch", hide_index=True)

    with st.expander("Standing caveats (always apply)"):
        for c in res.caveats:
            st.write("•", c)

    narrative = ai_narrative_panel(
        "nar_float",
        lambda tmpl: build_float_erosion_prompt(res, tmpl),
        "float_erosion",
        DEFAULT_TEMPLATES["float_erosion"],
        appendix_builder=lambda: float_appendix(res),
    )
    st.download_button(
        "⬇️ Download float erosion report (Excel)",
        data=build_float_erosion_xlsx(res, narrative),
        file_name="float_erosion_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
