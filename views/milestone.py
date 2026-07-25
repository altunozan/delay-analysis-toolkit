"""Milestone Shift Tracker."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import state as sk
from programme import build_milestone_prompt, build_milestone_xlsx
from programme.narrative import DEFAULT_TEMPLATES
from views._shared import (
    _fkey, ai_narrative_panel, cached_milestone_shifts, get_parsed_files,
)


def milestone_tab() -> None:
    st.caption(
        "How milestone forecasts drifted as the project progressed. "
        "X-axis = revision data date; a rising line = slippage."
    )
    files = get_parsed_files()
    inv = st.session_state.get(sk.INVENTORY)
    if not files or inv is None:
        st.info("Upload programmes in the **Data Intake** tab first.")
        return

    data_by_name = dict(files)
    revs = [(r.label, r.data_date, data_by_name[r.file_name])
            for r in inv.revisions if r.data_date is not None]
    if len(revs) < 2:
        st.info("Need at least two revisions with data dates to track shifts.")
        return

    result = cached_milestone_shifts(
        tuple((_fkey(r.file_name), str(r.data_date))
              for r in inv.revisions if r.data_date is not None), revs)
    tracked = [s for s in result.series
               if len({p.data_date for p in s.points}) > 1
               and s.total_shift_days is not None]
    if not tracked:
        st.warning("No milestone could be matched across two or more revisions.")
        return

    if result.needs_confirmation:
        with st.expander(
            f"⚠️ {len(result.needs_confirmation)} possible renamed/re-IDed "
            "milestone(s) — confirm before trusting"
        ):
            for m in result.needs_confirmation:
                st.write(
                    f"• `{m.task_code}` \"{m.task_name}\" may be the same as "
                    f"`{m.matched_to_key}` \"{m.matched_to_name}\" "
                    f"(name similarity {m.similarity:.0%})"
                )

    by_slip = sorted(tracked, key=lambda s: abs(s.total_shift_days), reverse=True)

    labels = {
        s.key: f"{s.key} — {s.name[:60]}  ({s.total_shift_days:+.0f}d"
               f"{', achieved' if s.is_achieved else ''})"
        for s in by_slip
    }
    picked = st.multiselect(
        "Milestones to plot (worst slippage first)",
        options=[s.key for s in by_slip],
        default=list(dict.fromkeys(
            ([st.session_state.get(sk.CONTRACT_MS)]
             if any(s.key == st.session_state.get(sk.CONTRACT_MS)
                    for s in by_slip) else [])
            + [s.key for s in by_slip[:min(5, len(by_slip))]])),
        format_func=lambda k: labels[k],
        key="ms_multi",
    )
    selected = [s for s in by_slip if s.key in set(picked)]
    if not selected:
        st.info("Pick at least one milestone above.")
        return

    rows = []
    for s in selected:
        for p in s.points:
            if p.value_date is None:
                continue
            delay = ((p.value_date - s.first_value).days
                     if s.first_value else None)
            rows.append({
                "Milestone": f"{s.key} · {s.name[:45]}",
                "Data date": p.data_date,
                "Milestone date": p.value_date,
                "Status": "Actual" if p.is_actual else "Forecast",
                "Delay (days)": delay,
            })
    chart_df = pd.DataFrame(rows)

    # ONE line per milestone. The delay in days is the SAME information
    # as the completion date (delay = date - first forecast), so a second
    # dashed line on an independent axis only creates a false visual
    # divergence — instead the y-axis itself switches between the two
    # readings of the same line.
    y_mode = st.radio(
        "Y-axis", ["Completion date", "Delay vs first forecast (days)"],
        horizontal=True, key="ms_ymode")
    x_axis = alt.X("Data date:T", title="Data date",
                   axis=alt.Axis(format="%b %Y", labelAngle=-30,
                                 grid=True, titleFontSize=13,
                                 labelFontSize=11))
    if y_mode == "Completion date":
        y_enc = alt.Y("Milestone date:T",
                      title="Completion date (forecast / actual)",
                      scale=alt.Scale(zero=False),
                      axis=alt.Axis(format="%b %Y", grid=True,
                                    titleFontSize=13, labelFontSize=11))
    else:
        y_enc = alt.Y("Delay (days):Q",
                      title="Delay vs first forecast (days)",
                      axis=alt.Axis(grid=True, titleFontSize=13,
                                    labelFontSize=11, format="+.0f"))
    line = (
        alt.Chart(chart_df)
        .mark_line(strokeWidth=2.5, interpolate="monotone")
        .encode(
            x=x_axis, y=y_enc,
            color=alt.Color("Milestone:N",
                            legend=alt.Legend(orient="bottom", columns=2,
                                              labelLimit=380, title=None)),
        )
    )
    pts = (
        alt.Chart(chart_df)
        .mark_point(size=110, filled=True)
        .encode(
            x=x_axis, y=y_enc,
            color=alt.Color("Milestone:N", legend=None),
            shape=alt.Shape(
                "Status:N",
                scale=alt.Scale(domain=["Forecast", "Actual"],
                                range=["circle", "diamond"]),
                legend=alt.Legend(orient="top", title=None),
            ),
            tooltip=[
                alt.Tooltip("Milestone:N"),
                alt.Tooltip("Data date:T", format="%d %b %Y"),
                alt.Tooltip("Milestone date:T", format="%d %b %Y"),
                alt.Tooltip("Status:N"),
                alt.Tooltip("Delay (days):Q", format="+.0f",
                            title="Delay vs first forecast (d)"),
            ],
        )
    )
    st.altair_chart(
        (line + pts)
        .properties(height=440, padding={"left": 44, "right": 12,
                                         "top": 8, "bottom": 4})
        .interactive(),
        width="stretch",
    )
    st.caption(
        "One line per milestone. Switch the y-axis between the "
        "completion date and its equivalent delay in days — both are "
        "the same trajectory, read on different scales. "
        "◆ = achieved (actual) · ● = forecast. The tooltip always "
        "carries both readings."
    )

    st.subheader("Shift summary")
    summary = pd.DataFrame([
        {
            "Activity ID": s.key,
            "Milestone": s.name,
            "First forecast": s.first_value.strftime("%Y-%m-%d") if s.first_value else "—",
            "Latest": s.last_value.strftime("%Y-%m-%d") if s.last_value else "—",
            "Total shift (days)": round(s.total_shift_days, 1),
            "Achieved": "Yes" if s.is_achieved else "No",
        }
        for s in by_slip
    ])
    st.dataframe(summary, width="stretch", hide_index=True, height=320)

    narrative = ai_narrative_panel(
        "nar_milestones",
        lambda tmpl: build_milestone_prompt(result, selected, tmpl),
        "milestone_shifts",
        DEFAULT_TEMPLATES["milestones"],
    )
    st.download_button(
        "⬇️ Download milestone report (Excel)",
        data=build_milestone_xlsx(result, by_slip, narrative),
        file_name="milestone_shift_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
