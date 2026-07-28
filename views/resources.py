"""Resource Loading."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import state as sk
from programme import (
    resources_appendix,
    build_resources_prompt, build_resources_xlsx, extract_resource_loading,
)
from programme.narrative import DEFAULT_TEMPLATES
from views._shared import ai_narrative_panel, get_parsed_files


def resources_tab() -> None:
    st.caption(
        "Monthly planned resource loading from the programme's assignments "
        "— planned deployment as scheduled, not actual expenditure."
    )
    files = get_parsed_files()
    inv = st.session_state.get(sk.INVENTORY)
    if not files or inv is None:
        st.info("Upload programmes in the **Data Intake** tab first.")
        return

    names = [r.file_name for r in inv.revisions]
    default_idx = (names.index(inv.baseline.file_name)
                   if inv.baseline else 0)
    chosen = st.selectbox("Programme", names, index=default_idx,
                          key="res_prog", help="Defaults to the baseline.")
    res = extract_resource_loading(dict(files)[chosen], chosen)

    for w in res.warnings:
        st.warning(w)
    if not res.histogram:
        return

    all_names = [r.short_name for r in res.resources]
    sel = st.multiselect(
        "Resources to chart", all_names, default=all_names[:8],
        help="Ordered by total planned quantity.")
    rows = [{"Month": p.month_end, "Resource": p.resource,
             "Type": p.rsrc_type, "Quantity": round(p.qty, 1)}
            for p in res.histogram if p.resource in sel]
    if rows:
        st.altair_chart(
            alt.Chart(pd.DataFrame(rows)).mark_bar()
            .encode(
                x=alt.X("yearmonth(Month):T", title=None,
                        axis=alt.Axis(format="%b %Y")),
                y=alt.Y("Quantity:Q", title="Planned quantity / month"),
                color=alt.Color("Resource:N",
                                legend=alt.Legend(orient="top", title=None)),
                tooltip=["Resource", "Type",
                         alt.Tooltip("yearmonth(Month):T", format="%b %Y"),
                         alt.Tooltip("Quantity:Q", format=",.0f")],
            ).properties(height=340),
            width="stretch",
        )

    st.subheader("Resources")
    st.dataframe(pd.DataFrame([{
        "Resource": r.short_name,
        "Name": r.name,
        "Type": r.rsrc_type,
        "Total planned qty": round(r.total_qty, 1),
        "Assignments": r.assignment_count,
    } for r in res.resources]), width="stretch", hide_index=True)

    with st.expander("Standing caveats (always apply)"):
        for c in res.caveats:
            st.write("•", c)

    narrative = ai_narrative_panel(
        f"nar_res_{chosen}",
        lambda tmpl: build_resources_prompt(res, tmpl),
        "resources",
        DEFAULT_TEMPLATES["resources"],
        appendix_builder=lambda: resources_appendix(res),
    )
    st.download_button(
        "⬇️ Download resource loading report (Excel)",
        data=build_resources_xlsx(res, narrative),
        file_name="resource_loading_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
