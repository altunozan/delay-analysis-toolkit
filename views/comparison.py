"""Revision Comparison."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import state as sk
from programme import (
    assess_comparison_impact, build_comparison_prompt, build_comparison_xlsx,
    build_impact_xlsx, build_provenance,
)
from programme.narrative import DEFAULT_TEMPLATES
from views._shared import (
    _fkey, ai_narrative_panel, cached_compare, get_parsed_files,
)


def comparison_tab() -> None:
    st.caption(
        "A change log between two programme revisions: scope, logic, "
        "durations, constraints, calendars — and retrospective changes to "
        "actualised dates."
    )
    files = get_parsed_files()
    inv = st.session_state.get(sk.INVENTORY)
    if not files or inv is None or len(files) < 2:
        st.info("Upload at least two programmes in the **Data Intake** tab "
                "first.")
        return

    names = [r.file_name for r in inv.revisions]     # data-date order
    c1, c2 = st.columns(2)
    old_name = c1.selectbox("Earlier revision", names, index=0,
                            help="Defaults to the baseline.")
    new_default = len(names) - 1 if names[-1] != old_name else 0
    new_name = c2.selectbox("Later revision", names, index=new_default)
    if old_name == new_name:
        st.warning("Pick two different revisions.")
        return

    pool = dict(files)
    cmp = cached_compare(_fkey(old_name), _fkey(new_name),
                         old_name, new_name,
                         pool[old_name], pool[new_name])

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total changes", cmp.total_changes)
    m2.metric("Added / deleted",
              f"{len(cmp.added)} / {len(cmp.deleted)}")
    m3.metric("Logic added / removed",
              f"{len(cmp.logic_added)} / {len(cmp.logic_removed)}")
    m4.metric("Actuals changed retrospectively",
              len(cmp.actual_date_changes))
    if cmp.old_finish and cmp.new_finish:
        moved = (cmp.new_finish - cmp.old_finish).days
        st.markdown(
            f"Scheduled completion: **{cmp.old_finish:%d %b %Y}** → "
            f"**{cmp.new_finish:%d %b %Y}** ({moved:+d} calendar days)"
        )

    for w in cmp.warnings:
        st.warning(w)

    counts = {k: v for k, v in cmp.category_counts.items() if v}
    if not counts:
        st.success("No differences found between the two revisions.")
        return
    chart_df = pd.DataFrame(
        [{"Category": k, "Count": v} for k, v in counts.items()])
    _cc_base = alt.Chart(chart_df).encode(
        x=alt.X("Count:Q", title=None),
        y=alt.Y("Category:N", sort="-x", title=None,
                axis=alt.Axis(labelLimit=280)))
    st.altair_chart(
        (_cc_base.mark_bar(cornerRadius=2).encode(
            color=alt.condition(
                "datum.Category == 'Actual dates changed retrospectively'",
                alt.value("#9B3227"), alt.value("#14324A")),
            tooltip=["Category", "Count"])
         + _cc_base.mark_text(align="left", dx=5, fontSize=10.5)
           .encode(text="Count:Q")
         ).properties(height=28 * len(chart_df)),
        width="stretch",
    )

    def _acts_table(refs):
        return pd.DataFrame([{
            "Activity ID": a.task_code, "Activity": a.name,
            "Type": "Milestone" if a.is_milestone else "Task",
            "Start": a.start.strftime("%Y-%m-%d") if a.start else "—",
            "Finish": a.finish.strftime("%Y-%m-%d") if a.finish else "—",
            "Duration (d)": a.duration_days,
        } for a in refs])

    def _changes_table(changes):
        return pd.DataFrame([{
            "Activity / Link": c.task_code, "Name": c.name,
            "Was": c.old_value, "Now": c.new_value,
            "Delta (d)": c.delta_days,
        } for c in changes])

    def _logic_table(links):
        return pd.DataFrame([{
            "Predecessor": lk.pred_code, "Pred name": lk.pred_name,
            "Type": lk.link_type, "Successor": lk.succ_code,
            "Succ name": lk.succ_name, "Lag (d)": lk.lag_days,
        } for lk in links])

    if cmp.actual_date_changes:
        with st.expander(
            f"🚩 Actual dates changed retrospectively "
            f"({len(cmp.actual_date_changes)})", expanded=True,
        ):
            st.dataframe(_changes_table(cmp.actual_date_changes),
                         width="stretch", hide_index=True)

    sections = [
        (f"Activities added ({len(cmp.added)})", _acts_table, cmp.added),
        (f"Activities deleted ({len(cmp.deleted)})", _acts_table,
         cmp.deleted),
        (f"Duration changes ({len(cmp.duration_changes)})", _changes_table,
         cmp.duration_changes),
        (f"Logic added ({len(cmp.logic_added)})", _logic_table,
         cmp.logic_added),
        (f"Logic removed ({len(cmp.logic_removed)})", _logic_table,
         cmp.logic_removed),
        (f"Lag changes ({len(cmp.lag_changes)})", _changes_table,
         cmp.lag_changes),
        (f"Constraint changes ({len(cmp.constraint_changes)})",
         _changes_table, cmp.constraint_changes),
        (f"Calendar reassignments ({len(cmp.calendar_changes)})",
         _changes_table, cmp.calendar_changes),
        (f"🚩 Calendar definitions changed "
         f"({len(cmp.calendar_def_changes)})",
         _changes_table, cmp.calendar_def_changes),
        (f"🚩 Scheduling options changed "
         f"({len(cmp.sched_options_changes)})",
         _changes_table, cmp.sched_options_changes),
        (f"Renamed activities ({len(cmp.renamed)})", _changes_table,
         cmp.renamed),
    ]
    for label, fn, items in sections:
        if items:
            with st.expander(label):
                st.dataframe(fn(items), width="stretch",
                             hide_index=True)

    # ------------------------------------------------------------------ #
    # Module 6b — impact & materiality screening
    # ------------------------------------------------------------------ #
    st.divider()
    st.subheader("Impact & materiality screening")
    st.caption(
        "Places every change on the driving (longest) path of each "
        "revision, ranks changes by a disclosed screening score, and "
        "screens the later revision for out-of-sequence progress. "
        "A screening for analyst attention — not a causation finding."
    )
    if st.toggle("Run impact screening",
                 key=f"impact_on_{old_name}_{new_name}"):
        with st.spinner("Tracing driving paths and ranking changes…"):
            imp = assess_comparison_impact(
                pool[old_name], pool[new_name], old_name, new_name,
                comparison=cmp,
                end_task_code=st.session_state.get(sk.CONTRACT_MS))
        i1, i2, i3, i4 = st.columns(4)
        i1.metric("Changes on / near driving path",
                  f"{imp.band_counts.get('critical', 0)} / "
                  f"{imp.band_counts.get('near-critical', 0)}")
        i2.metric("Completion moved (cal. days)",
                  f"{imp.completion_moved_days:+.0f}"
                  if imp.completion_moved_days is not None else "—")
        i3.metric("Red-flag changes",
                  sum(1 for c in imp.ranked if c.red_flag))
        i4.metric("Out-of-sequence records", len(imp.oos_flags))
        for w in imp.warnings:
            st.warning(w)

        _BAND_ICON = {"critical": "🔴 critical",
                      "near-critical": "🟠 near-critical",
                      "off-path": "⚪ off-path",
                      "completed": "✅ completed",
                      "absent": "◌ absent"}
        top_n = 50
        rank_df = pd.DataFrame([{
            "Score": c.score,
            "Path position": _BAND_ICON.get(c.band, c.band),
            "Category": c.category,
            "Activity / Link": c.ref,
            "Name": c.name,
            "Change": c.detail,
            "Delta (d)": c.delta_days,
            "TF now (d)": c.total_float_new,
        } for c in imp.ranked[:top_n]])
        st.markdown(f"**Materiality rank** — top {min(top_n, len(imp.ranked))} "
                    f"of {len(imp.ranked)} changes:")
        st.dataframe(rank_df, width="stretch", hide_index=True)

        if imp.oos_flags:
            st.caption(
                f"ℹ️ {len(imp.oos_flags)} out-of-sequence record(s) "
                f"detected in '{new_name}' — screening, as-built "
                "relation fits and the repaired-.xer export live in the "
                "**Out-of-Sequence Repair** tab.")

        with st.expander("Screening caveats (always apply)"):
            for c in imp.caveats:
                st.write("•", c)
        st.download_button(
            "⬇️ Download impact screening (Excel)",
            data=build_impact_xlsx(imp),
            file_name="comparison_impact_screening.xlsx",
            mime="application/vnd.openxmlformats-officedocument."
                 "spreadsheetml.sheet",
            key=f"impact_dl_{old_name}_{new_name}",
        )

    # ------------------------------------------------------------------ #
    # Change provenance across the whole revision set
    # ------------------------------------------------------------------ #
    if len(files) >= 3:
        st.divider()
        st.subheader("Change provenance across revisions")
        st.caption(
            "Attributes each category of change to the update window "
            "that introduced it — the timeline of programme editing."
        )
        if st.toggle("Build provenance timeline", key="prov_on"):
            ordered = [(r.file_name, pool[r.file_name])
                       for r in inv.revisions if r.file_name in pool]
            with st.spinner("Diffing consecutive revisions…"):
                prov = build_provenance(ordered)
            for w in prov.warnings:
                st.warning(w)
            if prov.windows:
                col_labels = [
                    f"{w.old_data_date:%d %b %y} → "
                    f"{w.new_data_date:%d %b %y}"
                    if w.old_data_date and w.new_data_date
                    else f"{w.old_label} → {w.new_label}"
                    for w in prov.windows]
                matrix = {"Category": prov.categories}
                for lbl, w in zip(col_labels, prov.windows):
                    matrix[lbl] = [w.counts.get(c, 0)
                                   for c in prov.categories]
                mat_df = pd.DataFrame(matrix)
                move_row = {"Category": "Completion moved (cal. days)"}
                for lbl, w in zip(col_labels, prov.windows):
                    move_row[lbl] = (round(w.completion_moved_days)
                                     if w.completion_moved_days is not None
                                     else None)
                mat_df = pd.concat(
                    [mat_df, pd.DataFrame([move_row])], ignore_index=True)
                st.dataframe(mat_df, width="stretch", hide_index=True)
                st.caption(
                    "Drill into any window by selecting that revision "
                    "pair above; red-flag windows (retrospective actual "
                    "changes) deserve first attention.")
            with st.expander("Provenance caveats"):
                for c in prov.caveats:
                    st.write("•", c)

    with st.expander("Standing caveats (always apply)"):
        for c in cmp.caveats:
            st.write("•", c)

    narrative = ai_narrative_panel(
        f"nar_cmp_{old_name}_{new_name}",
        lambda tmpl: build_comparison_prompt(cmp, tmpl),
        "comparison",
        DEFAULT_TEMPLATES["comparison"],
    )
    st.download_button(
        "⬇️ Download comparison report (Excel)",
        data=build_comparison_xlsx(cmp, narrative),
        file_name="revision_comparison_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
