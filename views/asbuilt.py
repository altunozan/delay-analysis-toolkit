"""As-Built Critical Path.

The step-① breakdown, standalone: per elected milestone the toolkit
computes BOTH candidate paths — the as-built programme's own longest
path vs the actual recorded sequence — the analyst adopts one, may
hand-edit it, and may group it into umbrella work packages. The adopted
election is the SAME state APvAB step ① reads, so the two pages can
never disagree about the as-built critical path. Beneath it: the logic
links along the adopted path(s), the path as a table, and the original
report generator (AI narrative + Excel workbook).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import state as sk
from programme import (
    build_asbuilt_multi_prompt, build_asbuilt_xlsx, build_rollup,
    internal_links, planned_vs_actual, trace_from_election,
    umbrella_links,
)
from programme.narrative import DEFAULT_TEMPLATES
from views._asbuilt_cp import cp_definition_block, link_table
from views._shared import ai_narrative_panel, get_parsed_files


def asbuilt_tab() -> None:
    files = get_parsed_files()
    inv = st.session_state.get(sk.INVENTORY)
    if not files or inv is None:
        st.info("Upload at least one programme in the **Data Intake** "
                "tab first.")
        return
    pool = dict(files)
    ordered = [(r.file_name, pool[r.file_name]) for r in inv.revisions]
    baseline = (pool[inv.baseline.file_name] if inv.baseline
                else ordered[0][1])

    # ---- ① define the as-built critical path ------------------------
    st.subheader("Define the as-built critical path")
    # THE shared step-① breakdown — the very same function APvAB step ①
    # renders, adopted state included.
    paths, basis_by, groups, chosen_ms = cp_definition_block(
        ordered, baseline, key_prefix="ab",
        date_basis=st.session_state.get(sk.APAB_DATE_BASIS, "late"))
    adopted = [ms for ms in chosen_ms if ms in paths]
    if not adopted:
        st.info("Adopt a path above to unlock the logic links and the "
                "report.")
        return

    traces = {ms: trace_from_election(
        ordered, paths[ms],
        basis_label=basis_by.get(ms, "analyst election"))
        for ms in adopted}
    union = {c for ms in adopted for c, _ in paths[ms]}
    umb_rows = planned_vs_actual(baseline, ordered[-1][1], None)
    roll = build_rollup(umb_rows, groups, union) if groups else None

    # ---- logic links -------------------------------------------------
    st.subheader("Logic links along the path")
    for ms in adopted:
        trace = traces[ms]
        if len(adopted) > 1:
            st.markdown(f"##### Path to **{ms}**")
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
                    } for r in ulinks]), width="stretch",
                        hide_index=True)
                    st.caption(
                        "One row per link BETWEEN packages, aggregated "
                        "from the activity hand-offs that cross the "
                        "boundary. 'Basis' is logic where every "
                        "crossing hand-off was programmed, sequence "
                        "only where none was, mixed otherwise.")
                else:
                    st.caption("No links cross a package boundary — "
                               "the whole path sits inside one "
                               "package.")
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
        for ms in adopted:
            if len(adopted) > 1:
                st.markdown(f"**Path to {ms}**")
            st.dataframe(pd.DataFrame([{
                "#": i, "Basis": a.basis,
                "Activity ID": a.task_code, "Activity": a.name,
                "Start": (f"{a.act_start:%Y-%m-%d}"
                          if a.act_start else "—"),
                "Finish": (f"{a.act_finish:%Y-%m-%d}"
                           if a.act_finish else "—"),
            } for i, a in enumerate(traces[ms].activities, start=1)]),
                width="stretch", hide_index=True, height=340)

    with st.expander("Standing caveats (always apply)"):
        seen: set[str] = set()
        for c in ([c for ms in adopted for c in traces[ms].caveats]
                  + (list(roll.caveats) if roll is not None else [])):
            if c not in seen:
                seen.add(c)
                st.write("•", c)

    # ---- the original report generator -------------------------------
    def _path_pngs():
        """(caption, png) per adopted path; a figure failure never
        blocks the report."""
        from programme.report_charts import asbuilt_gantt_chart, \
            chart_png
        out = []
        for ms in adopted:
            ch = asbuilt_gantt_chart(traces[ms])
            if ch is not None:
                out.append((f"As-built critical path — {ms}",
                            chart_png(ch)))
        return out or None

    try:
        _pngs = dict(_path_pngs() or [])
    except Exception:
        _pngs = {}

    narrative = ai_narrative_panel(
        "nar_asbuilt",
        lambda tmpl, trs=[traces[ms] for ms in adopted], rl=roll:
            build_asbuilt_multi_prompt(trs, rl, tmpl),
        "asbuilt_path",
        DEFAULT_TEMPLATES["asbuilt_path"],
        chart_png_builder=lambda: (list(_pngs.items()) or None),
    )
    for ms in adopted:
        st.download_button(
            f"⬇️ Download as-built path report — {ms} (Excel)",
            data=build_asbuilt_xlsx(
                traces[ms], narrative, roll=roll,
                links=(umbrella_links(traces[ms].links, groups)
                       if groups else None),
                gantt_png=_pngs.get(f"As-built critical path — {ms}")),
            file_name=f"asbuilt_critical_path_{ms}.xlsx",
            mime="application/vnd.openxmlformats-officedocument."
                 "spreadsheetml.sheet",
            key=f"ab_dl_{ms}",
        )
