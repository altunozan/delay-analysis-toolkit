"""As-Built Critical Path."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import state as sk
from programme import (
    analyse_asbuilt_path, build_asbuilt_prompt, build_asbuilt_xlsx,
    extract_actual_trace, report_charts, trace_end_candidates, triangulate,
)
from programme.narrative import DEFAULT_TEMPLATES
from views._shared import ai_narrative_panel, get_parsed_files


def asbuilt_tab() -> None:
    st.caption(
        "The as-built critical path reconstructed from the contemporaneous "
        "programmes: forecast-critical work confirmed as performed, window "
        "by window, plus the criticality persistence index."
    )
    files = get_parsed_files()
    inv = st.session_state.get(sk.INVENTORY)
    if not files or inv is None or len(files) < 2:
        st.info("Upload at least two programmes in the **Data Intake** tab "
                "first — the reconstruction reads criticality from each "
                "revision in force at the time.")
        return

    pool = dict(files)
    ordered = [(r.file_name, pool[r.file_name]) for r in inv.revisions]
    core_freq = st.slider(
        "Persistent-core threshold (% of eligible revisions critical)",
        10, 100, 50, 5,
        help="An activity joins the persistent core when it was on the "
             "forecast path in at least this share of the revisions in "
             "which it remained to be performed.") / 100.0
    res = analyse_asbuilt_path(ordered, core_min_frequency=core_freq)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Windows", len(res.windows))
    m2.metric("Stitched activities", len(res.stitched))
    m3.metric("Persistent core", len(res.core_codes))
    m4.metric("Remaining on path", res.remaining_path_count)

    for w in res.warnings:
        (st.info if w.startswith("Corroboration") else st.warning)(w)

    chart = report_charts.asbuilt_persistence_chart(res, max_rows=90)
    if chart is not None:
        st.altair_chart(chart, width="stretch")
        st.caption("Bars = actual dates as last recorded; darker red = on "
                   "the forecast critical path in a larger share of "
                   "revisions (the empirical spine of the as-built path).")

    st.subheader("Stitched contemporaneous path")
    core = set(res.core_codes)
    for w in res.windows:
        cov = (f"{w.coverage_pct:.0f}%" if w.coverage_pct is not None
               else "—")
        with st.expander(
            f"Window {w.index}: {w.from_label} → {w.to_label} — "
            f"{len(w.activities)} of {w.forecast_critical_count} "
            f"forecast-critical performed, coverage {cov}",
            expanded=len(res.windows) == 1,
        ):
            if w.activities:
                st.dataframe(pd.DataFrame([{
                    "Activity ID": a.task_code,
                    "Activity": a.name,
                    "Actual start": (f"{a.act_start:%Y-%m-%d}"
                                     if a.act_start else "—"),
                    "Actual finish": (f"{a.act_finish:%Y-%m-%d}"
                                      if a.act_finish else "in progress"),
                    "Persistent core": "✓" if a.task_code in core else "",
                } for a in w.activities]), width="stretch",
                    hide_index=True, height=300)
            else:
                st.write("No forecast-critical work recorded as performed "
                         "in this window.")

    with st.expander("Persistence index (all ever-critical activities)"):
        st.dataframe(pd.DataFrame([{
            "Activity ID": e.task_code,
            "Activity": e.name,
            "On path": f"{e.times_on_path}/{e.times_eligible}",
            "Frequency": f"{e.frequency:.0%}",
            "Actual start": (f"{e.act_start:%Y-%m-%d}"
                             if e.act_start else "—"),
            "Actual finish": (f"{e.act_finish:%Y-%m-%d}"
                              if e.act_finish else "—"),
        } for e in res.persistence]), width="stretch",
            hide_index=True, height=340)

    # ---- independent check: backward trace on actual dates --------------
    st.subheader("Independent check — actual-date backward trace")
    st.caption(
        "A second, methodologically independent reconstruction: walk "
        "backward through recorded actual dates, following only hand-offs "
        "evidenced by a programmed relationship. Where no such hand-off "
        "exists within the gap window, the trace stops and says so."
    )
    cands = trace_end_candidates(ordered)
    trace = tri = None
    if not cands:
        st.info("No actually finished activities in the latest revision — "
                "nothing to trace.")
    else:
        cand_labels = {c: f"{c} — {n}" + (f"  (AF {af:%Y-%m-%d})"
                                          if af else "")
                       for c, n, af in cands}
        tc1, tc2, tc3 = st.columns([3, 1, 1])
        end_code = tc1.selectbox(
            "Trace backward from", options=list(cand_labels.keys()),
            format_func=lambda c: cand_labels[c], key="ab_trace_end",
            help="Defaults to the latest actual finisher (milestones "
                 "within a week of it preferred).")
        max_gap = tc2.number_input("Max hand-off gap (days)",
                                   1.0, 730.0, 60.0, 5.0, key="ab_gap",
                                   help="Widen when work stalled between "
                                        "logically linked activities.")
        fallback = tc3.toggle(
            "Allow un-logic'd hops", value=False, key="ab_fallback",
            help="Continue through the tightest temporal neighbour where "
                 "no programmed relationship exists. Such links are weak "
                 "evidence and flagged as such.")
        trace = extract_actual_trace(
            ordered, end_task_code=end_code, max_gap_days=max_gap,
            allow_temporal_fallback=fallback)

        t1, t2, t3 = st.columns(3)
        t1.metric("Chain length", len(trace.activities))
        logic_n = sum(1 for lk in trace.links if lk.had_logic)
        t2.metric("Logic-evidenced hand-offs",
                  f"{logic_n} / {len(trace.links)}" if trace.links else "—")
        t3.metric("Traced from", trace.terminal_code or "—")
        for w in trace.warnings:
            (st.info if w.startswith("Logic corroboration")
             else st.warning)(w)
        if trace.links:
            st.dataframe(pd.DataFrame([{
                "Predecessor": lk.pred_code,
                "→ Successor": lk.succ_code,
                "Kind": lk.kind,
                "Gap (d)": lk.gap_days,
                "Programmed logic": "✓" if lk.had_logic else "✗",
                "Confidence": lk.score,
                "Alternatives": lk.alternatives,
            } for lk in trace.links]), width="stretch",
                hide_index=True)

        # ---- method agreement -------------------------------------------
        tri = triangulate(res, trace)
        st.subheader("Method agreement")
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Agreement",
                  f"{tri.agreement_pct:.0f}%"
                  if tri.agreement_pct is not None else "—",
                  help="Share of the union of both reconstructions "
                       "identified by both.")
        a2.metric("Both methods", len(tri.both))
        a3.metric("Stitched only", len(tri.stitched_only))
        a4.metric("Trace only", len(tri.trace_only))
        for w in tri.warnings:
            (st.success if w.startswith("Method agreement")
             else st.warning)(w)
        if tri.both or tri.trace_only:
            with st.expander("Membership detail"):
                rows = ([{"Activity ID": c,
                          "Activity": tri.names.get(c, ""),
                          "Identified by": "Both methods"}
                         for c in tri.both]
                        + [{"Activity ID": c,
                            "Activity": tri.names.get(c, ""),
                            "Identified by": "Trace only"}
                           for c in tri.trace_only])
                st.dataframe(pd.DataFrame(rows), width="stretch",
                             hide_index=True)

    with st.expander("Standing caveats (always apply)"):
        for c in res.caveats + (trace.caveats if trace else []):
            st.write("•", c)

    narrative = ai_narrative_panel(
        "nar_asbuilt",
        lambda tmpl, tr=trace, tg=tri: build_asbuilt_prompt(
            res, tr, tg, tmpl),
        "asbuilt_path",
        DEFAULT_TEMPLATES["asbuilt_path"],
    )
    st.download_button(
        "⬇️ Download as-built path report (Excel)",
        data=build_asbuilt_xlsx(res, narrative, trace=trace, tri=tri),
        file_name="asbuilt_critical_path_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
