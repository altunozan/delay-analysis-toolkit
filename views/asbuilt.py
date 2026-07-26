"""As-Built Critical Path.

Pick the milestone, trace backwards to the start of the works, read it
on a gantt with the data date drawn. Optionally group the path into work
packages. That is the whole module.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import state as sk
from programme import (
    ASBUILT_CATEGORIES, asbuilt_path_tree, build_asbuilt_prompt,
    build_asbuilt_xlsx, build_gantt_html, build_rollup, internal_links,
    planned_vs_actual, umbrella_links,
)
from programme.narrative import DEFAULT_TEMPLATES
from views._asbuilt_cp import link_table, trace_basis
from views._shared import ai_narrative_panel, get_parsed_files
from views._umbrella import umbrella_editor


def asbuilt_tab() -> None:
    st.caption(
        "Choose the milestone you are measuring to; the path is traced "
        "back from it, activity by activity, to the start of the works. "
        "Where the programme linked two consecutive activities the link "
        "corroborates the hand-off; where it did not, the recorded "
        "sequence carries the chain and is flagged as such."
    )
    files = get_parsed_files()
    inv = st.session_state.get(sk.INVENTORY)
    if not files or inv is None:
        st.info("Upload at least one programme in the **Data Intake** "
                "tab first.")
        return

    pool = dict(files)
    ordered = [(r.file_name, pool[r.file_name]) for r in inv.revisions]
    trace = trace_basis(ordered, "ab")
    if trace is None or not trace.activities:
        return

    # ---- work packages (optional, shared with APvAB) -----------------
    groups = st.session_state.get(sk.UMBRELLAS) or {}
    roll = None
    path_codes = set(trace.codes)
    base_rev = (pool[inv.baseline.file_name] if inv.baseline
                else ordered[0][1])
    umb_rows = planned_vs_actual(base_rev, ordered[-1][1], None)
    with st.expander(
        "Group the path into work packages — one bar per trade "
        "(Screed, Blockwork, Plastering, First / Second Fix…) instead "
        "of a row per activity",
        expanded=False
    ):
        groups = umbrella_editor(umb_rows, path_codes, key_prefix="ab_umb")
    if groups:
        roll = build_rollup(umb_rows, groups, path_codes)

    # ---- the gantt ---------------------------------------------------
    st.subheader("As-built critical path")
    grouped = bool(groups) and st.toggle(
        "Show as work packages", value=True, key="ab_gantt_grouped",
        help="Umbrella bars bracket their member activities; the "
             "measured dates still come from critical-path members.")
    tree = asbuilt_path_tree(
        trace.activities,
        groups=groups if grouped else None,
        links=trace.links,
        root_name=f"As-built path to {trace.terminal_code}")
    st.iframe(
        build_gantt_html(
            tree,
            data_date=(f"{trace.data_date:%Y-%m-%d}"
                       if trace.data_date else None),
            title=f"As-built critical path — {trace.terminal_code}",
            categories=ASBUILT_CATEGORIES),
        height=620)
    st.caption(
        "The dashed line is the data date: bars to its left are recorded "
        "work, bars to its right are the programme's forecast. Arrows "
        "are the hand-offs along the path.")

    # ---- logic links -------------------------------------------------
    st.subheader("Logic links along the path")
    if roll is not None and groups:
        tabs = st.tabs(["Between work packages", "Activity level"])
        with tabs[0]:
            ulinks = umbrella_links(trace.links, groups)
            internal = internal_links(trace.links, groups)
            if ulinks:
                st.dataframe(pd.DataFrame([{
                    "From": r["from"], "→ To": r["to"],
                    "Basis": r["basis"],
                    "Hand-offs": r["hand_off_count"],
                    "On logic": r["logic_evidenced"],
                    "Sequence only": r["sequence_only"],
                    "Activities": "; ".join(r["hand_offs"][:4]),
                } for r in ulinks]), width="stretch", hide_index=True)
                st.caption(
                    "One row per link BETWEEN packages, aggregated from "
                    "the activity hand-offs that cross the boundary. "
                    "'Basis' is logic where every crossing hand-off was "
                    "programmed, sequence only where none was, mixed "
                    "otherwise.")
            else:
                st.caption("No links cross a package boundary — the "
                           "whole path sits inside one package.")
            if internal:
                st.caption("Hand-offs internal to a package: "
                           + ", ".join(f"{k} ({v})"
                                       for k, v in internal.items()))
        with tabs[1]:
            link_table(trace)
    else:
        link_table(trace)

    # ---- the chain as a table ----------------------------------------
    with st.expander("The path as a table"):
        st.dataframe(pd.DataFrame([{
            "#": i, "Basis": a.basis,
            "Activity ID": a.task_code, "Activity": a.name,
            "Start": f"{a.act_start:%Y-%m-%d}" if a.act_start else "—",
            "Finish": f"{a.act_finish:%Y-%m-%d}" if a.act_finish else "—",
        } for i, a in enumerate(trace.activities, start=1)]),
            width="stretch", hide_index=True, height=340)

    with st.expander("Standing caveats (always apply)"):
        for c in (list(trace.caveats)
                  + (list(roll.caveats) if roll is not None else [])):
            st.write("•", c)

    narrative = ai_narrative_panel(
        "nar_asbuilt",
        lambda tmpl, tr=trace, rl=roll: build_asbuilt_prompt(tr, rl, tmpl),
        "asbuilt_path",
        DEFAULT_TEMPLATES["asbuilt_path"],
    )
    st.download_button(
        "⬇️ Download as-built path report (Excel)",
        data=build_asbuilt_xlsx(
            trace, narrative, roll=roll,
            links=umbrella_links(trace.links, groups) if groups else None),
        file_name="asbuilt_critical_path_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
