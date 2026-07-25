"""As-Planned vs As-Built variance by mapping (embedded in APvAB)."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import state as sk
from programme import (
    activity_code_types, build_gantt_html, build_variance_prompt,
    build_variance_xlsx, combine_mappings, compute_variance_by_mapping,
    group_tree, max_wbs_depth, task_code_assignments, task_wbs_assignments,
)
from programme.narrative import DEFAULT_TEMPLATES
from programme.variance import DIMENSION_SEPARATOR
from views._shared import (
    GAIN_COLOR, PLANNED_COLOR, RECORDED_COLOR, SLIP_COLOR, ai_narrative_panel,
    get_parsed_files,
)


def variance_tab() -> None:
    st.caption(
        "Screening view of where slippage clusters: the programme re-broken "
        "down by activity code or WBS level, planned vs recorded bands per "
        "group. Preliminary and indicative only."
    )
    files = get_parsed_files()
    inv = st.session_state.get(sk.INVENTORY)
    if not files or inv is None:
        st.info("Upload programmes in the **Data Intake** tab first.")
        return
    if len(files) < 2:
        st.info("Need at least two programmes (baseline + update).")
        return

    data_by_name = dict(files)
    names = [r.file_name for r in inv.revisions]
    default_base = inv.baseline.file_name if inv.baseline else names[0]
    default_cur = inv.current.file_name if inv.current else names[-1]

    c1, c2 = st.columns(2)
    base_name = c1.selectbox("Baseline (as-planned)", names,
                             index=names.index(default_base))
    cur_name = c2.selectbox("Current (as-recorded)", names,
                            index=names.index(default_cur))
    if base_name == cur_name:
        st.info("Choose two different programmes.")
        return

    base_data = data_by_name[base_name]
    cur_data = data_by_name[cur_name]

    # Breakdown dimensions: any mix of activity codes and WBS levels, up to 4,
    # combined in the order selected (e.g. "Zone A › Structure › Level 03").
    options: list[tuple[str, str]] = []  # (kind:id, label)
    for t in activity_code_types(base_data):
        options.append((f"code:{t.type_id}",
                        f"Activity code — {t.name} ({t.assigned_task_count} acts)"))
    depth = min(max_wbs_depth(base_data), max_wbs_depth(cur_data))
    for lvl in range(1, min(depth, 4) + 1):
        options.append((f"wbs:{lvl}", f"WBS Level {lvl}"))
    if not options:
        st.warning("Neither activity codes nor a WBS exist in these files — "
                   "no breakdown dimension available.")
        return

    dim_keys = st.multiselect(
        "Breakdown dimension(s) — combined in the order selected, max 4",
        options=[k for k, _ in options],
        default=[options[0][0]],
        format_func=lambda k: dict(options)[k],
        max_selections=4,
        key="var_dims",
        help="One dimension gives a flat breakdown; several nest, e.g. "
             "an Area code combined with WBS Level 2.",
    )
    if not dim_keys:
        st.info("Select at least one breakdown dimension.")
        return

    def _maps_for(key: str) -> tuple[str, dict, dict]:
        kind, _, ident = key.partition(":")
        if kind == "code":
            name = next(t.name for t in activity_code_types(base_data)
                        if t.type_id == ident)
            return (name,
                    task_code_assignments(base_data, ident),
                    task_code_assignments(cur_data, ident))
        lvl = int(ident)
        return (f"WBS L{lvl}",
                task_wbs_assignments(base_data, lvl),
                task_wbs_assignments(cur_data, lvl))

    names_maps = [_maps_for(k) for k in dim_keys]
    dim_name = " › ".join(n for n, _, _ in names_maps)
    base_map = combine_mappings([bm for _, bm, _ in names_maps])
    cur_map = combine_mappings([cm for _, _, cm in names_maps])

    var = compute_variance_by_mapping(base_data, cur_data, base_map, cur_map,
                                      dim_name)
    if len(var.groups) > 80:
        st.warning(
            f"{len(var.groups)} groups — this combination is too granular to "
            "read as a screening view. Consider fewer/coarser dimensions."
        )
    plotted = [g for g in var.groups if g.in_both]

    # With combined dimensions, colour everything by the FIRST (outermost)
    # dimension so sibling groups share a hue.
    multi_dim = len(names_maps) > 1
    first_dim_name = names_maps[0][0]

    def _first_part(label: str) -> str:
        return label.split(DIMENSION_SEPARATOR)[0]

    # --- Finish-slippage bar chart: instantly shows where delay clusters ---
    delta_rows = [
        {
            "Group": g.code_value,
            "Δ finish (days)": round(g.finish_delta_days, 1),
            first_dim_name: _first_part(g.code_value),
        }
        for g in plotted if g.finish_delta_days is not None
    ]
    if delta_rows:
        st.subheader("Finish slippage by group")
        delta_df = pd.DataFrame(delta_rows).sort_values(
            "Δ finish (days)", ascending=False)
        if multi_dim:
            bar_color = alt.Color(
                f"{first_dim_name}:N",
                scale=alt.Scale(scheme="tableau10"),
                legend=alt.Legend(orient="top", title=first_dim_name,
                                  labelLimit=300),
            )
            tooltip = [first_dim_name, "Group",
                       alt.Tooltip("Δ finish (days):Q", format="+.0f")]
        else:
            bar_color = alt.condition(
                alt.datum["Δ finish (days)"] > 0,
                alt.value(SLIP_COLOR), alt.value(GAIN_COLOR))
            tooltip = ["Group", alt.Tooltip("Δ finish (days):Q", format="+.0f")]
        bar = (
            alt.Chart(delta_df)
            .mark_bar(cornerRadiusEnd=3)
            .encode(
                x=alt.X("Δ finish (days):Q", title="Finish delta (days) — "
                        "positive = later than planned"),
                y=alt.Y("Group:N", sort="-x", title=None,
                        axis=alt.Axis(labelLimit=320)),
                color=bar_color,
                tooltip=tooltip,
            )
            .properties(height=max(140, 26 * len(delta_df)))
        )
        _v_base = alt.Chart(delta_df).encode(
            y=alt.Y("Group:N", sort="-x", title=None),
            x=alt.X("Δ finish (days):Q"))
        _v_lp = (_v_base.transform_filter("datum['Δ finish (days)'] >= 0")
                 .mark_text(align="left", dx=5, fontSize=10.5)
                 .encode(text=alt.Text("Δ finish (days):Q",
                                       format="+.0f")))
        _v_ln = (_v_base.transform_filter("datum['Δ finish (days)'] < 0")
                 .mark_text(align="right", dx=-5, fontSize=10.5)
                 .encode(text=alt.Text("Δ finish (days):Q",
                                       format="+.0f")))
        st.altair_chart(bar + _v_lp + _v_ln, width="stretch")
        if multi_dim:
            st.caption(f"Bar colour = {first_dim_name} (first selected "
                       "dimension). Bar direction shows slip (right) vs "
                       "gain (left).")

    # --- Gantt: planned vs recorded band per group (think-cell view) ----
    nested: dict[str, dict] = {}
    flat_groups: list[dict] = []
    for g in plotted:
        acts = []
        if g.planned.start and g.planned.finish:
            acts.append({"id": "Planned",
                         "name": f"{g.planned.activity_count} activities",
                         "start": g.planned.start,
                         "finish": g.planned.finish, "status": "planned"})
        if g.recorded.start and g.recorded.finish:
            acts.append({"id": "As-recorded",
                         "name": f"{g.recorded.activity_count} activities",
                         "start": g.recorded.start,
                         "finish": g.recorded.finish, "status": "recorded"})
        if not acts:
            continue
        if multi_dim and DIMENSION_SEPARATOR in g.code_value:
            head, _, tail = g.code_value.partition(DIMENSION_SEPARATOR)
            parent = nested.setdefault(
                head.strip(), {"name": head.strip(), "children": [],
                               "activities": []})
            parent["children"].append({"name": tail.strip(),
                                       "activities": acts})
        else:
            flat_groups.append({"name": g.code_value, "activities": acts})
    var_groups = list(nested.values()) + flat_groups
    if var_groups:
        st.subheader("Planned vs as-recorded bands")
        dd_v = (f"{cur_data.project.data_date:%Y-%m-%d}"
                if cur_data.project and cur_data.project.data_date else None)
        st.iframe(
            build_gantt_html(
                group_tree(var_groups), data_date=dd_v,
                title=f"Planned vs as-recorded — {dim_name}",
                categories=[
                    {"key": "planned", "label": "planned",
                     "color": PLANNED_COLOR},
                    {"key": "recorded", "label": "as-recorded",
                     "color": RECORDED_COLOR},
                ]),
            height=520)
        st.caption("Each group carries its planned and as-recorded band; "
                   "navy brackets span both. Expand/collapse"
                   + (f" by {first_dim_name}," if multi_dim else ",")
                   + " search, and zoom in the chart · dashed red line = "
                   "update data date.")

    st.subheader("Variance table")
    table = pd.DataFrame([
        {
            dim_name: g.code_value,
            "Planned start": g.planned.start.strftime("%Y-%m-%d") if g.planned.start else "—",
            "Planned finish": g.planned.finish.strftime("%Y-%m-%d") if g.planned.finish else "—",
            "Recorded start": g.recorded.start.strftime("%Y-%m-%d") if g.recorded.start else "—",
            "Recorded finish": g.recorded.finish.strftime("%Y-%m-%d") if g.recorded.finish else "—",
            "Δ start (days)": round(g.start_delta_days, 1) if g.start_delta_days is not None else None,
            "Δ finish (days)": round(g.finish_delta_days, 1) if g.finish_delta_days is not None else None,
        }
        for g in var.groups
    ])
    st.dataframe(table, width="stretch", hide_index=True)

    for w in var.warnings:
        st.warning(w)
    with st.expander("Standing caveats (always apply)"):
        for c in var.caveats:
            st.write("•", c)

    narrative = ai_narrative_panel(
        "nar_variance",
        lambda tmpl: build_variance_prompt(var, tmpl),
        "planned_vs_recorded",
        DEFAULT_TEMPLATES["variance"],
    )
    st.download_button(
        "⬇️ Download variance report (Excel)",
        data=build_variance_xlsx(var, narrative),
        file_name="planned_vs_recorded_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
