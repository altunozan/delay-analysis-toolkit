"""Baseline Critical Path."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import state as sk
from programme import (
    build_critical_path_prompt, build_critical_path_xlsx, build_gantt_html,
    end_activity_candidates, group_tree,
)
from programme.narrative import DEFAULT_TEMPLATES
from views._shared import (
    _fkey, ai_narrative_panel, basis_panel, cached_float_path,
    cached_longest_path, get_parsed_files,
)


BAND_COLORS = {"critical": "#9B3227", "near-critical": "#B07A24"}


def critical_path_tab() -> None:
    st.caption(
        "The planned critical path of a single programme: the chain of "
        "activities at or below the float tolerance, its continuity, and the "
        "near-critical band behind it."
    )
    files = get_parsed_files()
    inv = st.session_state.get(sk.INVENTORY)
    if not files or inv is None:
        st.info("Upload programmes in the **Data Intake** tab first.")
        return

    names = [r.file_name for r in inv.revisions]
    default_idx = (names.index(inv.baseline.file_name)
                   if inv.baseline else 0)
    c1, c2 = st.columns([2, 2])
    chosen = c1.selectbox("Programme", names, index=default_idx,
                          help="Defaults to the baseline.")
    method = c2.radio(
        "Identification method",
        ["Longest path (backward driving trace)", "Float-based (TF ≤ tolerance)"],
        horizontal=True,
        help="Longest path is an INDEPENDENT driving-logic trace computed "
             "by this tool from the file's dates — robust with multiple "
             "calendars. Float-based reads the STORED total float that P6 "
             "wrote into the submitted file (it reflects the file's own "
             "scheduling options, including any must-finish date). The "
             "two can legitimately disagree; the basis panel below "
             "records which definition this analysis used.",
    )
    data = dict(files)[chosen]

    if method.startswith("Longest"):
        cands = end_activity_candidates(data, limit=40)
        if not cands:
            st.warning("No incomplete activities with early dates to trace from.")
            return
        cand_labels = {
            code: f"{code} — {name}" + (f"  (EF {ef:%Y-%m-%d})" if ef else "")
            for code, name, ef in cands
        }
        cc1, cc2, cc3 = st.columns([3, 1, 1])
        _cms = st.session_state.get(sk.CONTRACT_MS)
        _cands = list(cand_labels.keys())
        end_code = cc1.selectbox(
            "Trace backward from",
            options=_cands,
            index=(_cands.index(_cms) if _cms in _cands else 0),
            format_func=lambda c: cand_labels[c],
            help="Defaults to the latest finisher (completion milestone "
                 "preferred). Pick a sectional milestone to isolate its "
                 "individual driving chain.",
        )
        near = cc2.number_input("Near-critical ≤ (days)", 0.0, 200.0, 10.0, 1.0)
        show_near = cc3.toggle("Show near-critical", value=False)
        branch_tol = st.slider(
            "Driving-DAG branch tolerance (hours of slack)", 0.0, 48.0,
            1.0, 1.0, key="cpath_branch_tol",
            help="Every predecessor within this many hours of the "
                 "tightest is followed. Widen (e.g. 8h or 24h) to "
                 "surface NEAR-PARALLEL driving chains — the width a "
                 "concurrency case turns on. The tolerance used is "
                 "disclosed in the basis.")
        if st.checkbox(
            "Treat this as the CONTRACTUAL completion milestone",
            value=(st.session_state.get(sk.CONTRACT_MS)
                   == end_code),
            help="Recorded in the Basis of Analysis and offered as the "
                 "default trace terminal across the toolkit.",
        ):
            st.session_state[sk.CONTRACT_MS] = end_code
        cp = cached_longest_path(_fkey(chosen), chosen, end_code,
                                 near, data, branch_tol)
        if cp.branch_points:
            st.info(f"Driving DAG forks at "
                    f"{len(cp.branch_points)} activity(ies) — "
                    "parallel driving chains present: "
                    + ", ".join(cp.branch_points[:8])
                    + (" …" if len(cp.branch_points) > 8 else "")
                    + ". A single-chain reading would "
                    "understate concurrency here.")
        basis_panel("Baseline Critical Path", data, [
            "Criticality definition: INDEPENDENT longest-path trace "
            "(backward driving-logic walk computed by this tool), not "
            "the file's stored total float",
            f"Trace terminal: {end_code}"
            + (" (contractual completion milestone)"
               if st.session_state.get(sk.CONTRACT_MS)
               == end_code else ""),
            f"Near-critical band: stored total float ≤ {near:.0f} "
            "working days",
            f"Driving-DAG branch tolerance: {branch_tol:.0f} h — all "
            "predecessors within this slack of the tightest are "
            "followed (parallel chains captured)",
        ])
    else:
        cc1, cc2, cc3 = st.columns([1, 1, 1])
        tol = cc1.number_input("Critical float ≤ (days)", -100.0, 100.0, 0.0, 1.0)
        near = cc2.number_input("Near-critical ≤ (days)", 0.0, 200.0, 10.0, 1.0)
        show_near = cc3.toggle("Show near-critical", value=False)
        cp = cached_float_path(_fkey(chosen), chosen, tol, near, data)
        basis_panel("Baseline Critical Path", data, [
            "Criticality definition: STORED total float as written by P6 "
            "into the submitted file (reflects the file's own scheduling "
            "options, including any must-finish date)",
            f"Critical threshold: total float ≤ {tol:.0f} working days; "
            f"near-critical ≤ {near:.0f}",
        ])

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Path activities" if cp.method == "longest_path"
              else "Critical activities", len(cp.critical))
    m2.metric("Near-critical", len(cp.near_critical))
    if cp.method == "longest_path":
        m3.metric("Driving links", len(cp.links))
        m4.metric("Traced from", cp.end_choice or "—")
    else:
        m3.metric("Chain segments", cp.chain_segments)
        m4.metric("Continuous", "Yes ✅" if cp.is_continuous else "No ⚠️")

    for w in cp.warnings:
        st.warning(w)
    if not cp.critical:
        return

    # --- Chain visual (think-cell view): critical + near-critical groups
    def _cp_act(a):
        return {"id": a.task_code, "name": a.name,
                "start": a.early_start or a.early_finish,
                "finish": a.early_finish or a.early_start,
                "milestone": a.is_milestone, "status": a.band}

    cp_groups = [{
        "name": ("Critical path"
                 if cp.method == "longest_path"
                 else f"Critical (TF ≤ {cp.float_tolerance_days:.0f}d)"),
        "activities": [_cp_act(a) for a in cp.critical
                       if a.early_start or a.early_finish],
    }]
    if show_near and cp.near_critical:
        cp_groups.append({
            "name": f"Near-critical band (TF ≤ {cp.near_critical_days:.0f}d)",
            "activities": [_cp_act(a) for a in cp.near_critical
                           if a.early_start or a.early_finish],
        })
    dd_cp = (f"{data.project.data_date:%Y-%m-%d}"
             if data.project and data.project.data_date else None)
    st.iframe(
        build_gantt_html(
            group_tree(cp_groups), data_date=dd_cp,
            title=f"Critical path — {chosen}",
            categories=[
                {"key": "critical", "label": "critical",
                 "color": BAND_COLORS["critical"]},
                {"key": "near-critical", "label": "near-critical",
                 "color": BAND_COLORS["near-critical"]},
            ]),
        height=560)
    st.caption("Early-start order · ◆ = milestone · expand/collapse, "
               "search and zoom in the chart · chain continuity and the "
               "driving logic links are reported in the warnings above and "
               "the Excel export's links sheet.")

    st.subheader("Path activities")
    table = pd.DataFrame([
        {
            "Activity ID": a.task_code,
            "Activity": a.name,
            "Type": "Milestone" if a.is_milestone else "Task",
            "Band": a.band,
            "Early start": a.early_start.strftime("%Y-%m-%d") if a.early_start else "—",
            "Early finish": a.early_finish.strftime("%Y-%m-%d") if a.early_finish else "—",
            "Duration (d)": a.duration_days,
            "Total float (d)": a.total_float_days,
        }
        for a in (cp.activities if show_near else cp.critical)
    ])
    st.dataframe(table, width="stretch", hide_index=True, height=340)

    with st.expander("Standing caveats (always apply)"):
        for c in cp.caveats:
            st.write("•", c)

    narrative = ai_narrative_panel(
        f"nar_cp_{chosen}",
        lambda tmpl: build_critical_path_prompt(cp, tmpl),
        "critical_path",
        DEFAULT_TEMPLATES["critical_path"],
    )
    st.download_button(
        "⬇️ Download critical path report (Excel)",
        data=build_critical_path_xlsx(cp, narrative),
        file_name="critical_path_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
