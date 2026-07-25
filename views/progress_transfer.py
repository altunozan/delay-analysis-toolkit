"""Progress Transfer."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import state as sk
from programme import build_transfer_xlsx, run_progress_transfer
from views._shared import basis_panel, get_parsed_files


def progress_transfer_tab() -> None:
    st.caption(
        "Statuses one programme's network with another programme's "
        "recorded progress, then schedules both under the same "
        "calendar-exact engine. With progress held identical, the "
        "difference in forecast completion is attributable to the "
        "NETWORK changes between the files — the quantity a covert "
        "re-sequencing tries to hide."
    )
    files = get_parsed_files()
    inv = st.session_state.get(sk.INVENTORY)
    if not files or inv is None or len(files) < 2:
        st.info("Upload at least two programmes in the **Data Intake** tab "
                "first.")
        return

    names = [r.file_name for r in inv.revisions]     # data-date order
    c1, c2 = st.columns(2)
    net_name = c1.selectbox(
        "Network donor (logic & durations)", names, index=0,
        help="The trusted network — typically the baseline or an earlier "
             "accepted update.")
    prog_default = len(names) - 1 if names[-1] != net_name else 0
    prog_name = c2.selectbox(
        "Progress donor (recorded actuals & data date)", names,
        index=prog_default,
        help="The file whose actual dates and data date are applied.")
    if net_name == prog_name:
        st.info("Same file on both sides gives a self-check: the network "
                "effect should be 0.")

    pool = dict(files)
    if not st.toggle("Run progress transfer", key="ptr_on"):
        return
    with st.spinner("Statusing the network and running both passes…"):
        tr = run_progress_transfer(pool[net_name], pool[prog_name],
                                   net_name, prog_name)

    if tr.data_date is None:
        for w in tr.warnings:
            st.warning(w)
        return

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Data date applied",
              f"{tr.data_date:%d %b %Y}")
    m2.metric("Progress transferred (started / complete)",
              f"{tr.applied_starts} / {tr.applied_finishes}")
    m3.metric(
        "Logic/duration effect (days)",
        f"{tr.network_effect_days:+.0f}"
        if tr.network_effect_days is not None else "—",
        help="Measured on the activities present in BOTH files, with "
             "identical progress — scope change cannot contaminate this "
             "figure. Positive: the progress donor's own network "
             "schedules earlier than the donor network would — its "
             "logic/duration edits improved the forecast.")
    m4.metric(
        "Scope effect (days)",
        f"{tr.scope_effect_days:+.0f}"
        if tr.scope_effect_days is not None else "—",
        help="Further movement from network-donor activities the "
             "progress file no longer carries (modelled unstarted at "
             "full duration). Scope change — NOT re-sequencing.")
    if tr.completion_reference:
        st.markdown(
            f"Forecasts under one engine — `{prog_name}` on its own "
            f"network: **{tr.completion_reference:%d %b %Y}**"
            + (f" (calibration vs P6 {tr.calibration_days:+.0f}d)"
               if tr.calibration_days is not None else "")
            + (f" · shared activities on `{net_name}` network: "
               f"**{tr.completion_logic_only:%d %b %Y}**"
               if tr.completion_logic_only else "")
            + (f" · full transfer incl. unmatched scope: "
               f"**{tr.completion_transferred:%d %b %Y}**"
               if tr.completion_transferred else ""))

    for w in tr.warnings:
        st.warning(w)

    if tr.milestones:
        st.markdown("**Milestones — transferred vs reference forecast:**")
        ms_df = pd.DataFrame([{
            "Milestone": m.code, "Name": m.name,
            "Transferred": (m.transferred.strftime("%Y-%m-%d")
                            if m.transferred else "—"),
            "Reference": (m.reference.strftime("%Y-%m-%d")
                          if m.reference else "—"),
            "Delta (d)": m.delta_days,
        } for m in tr.milestones])
        st.dataframe(ms_df, width="stretch", hide_index=True)

    if tr.driving_chain:
        with st.expander(
            f"Driving chain of the transferred programme "
            f"({len(tr.driving_chain)} activities)"
        ):
            ch_df = pd.DataFrame([{
                "Activity": s["id"], "Name": s["name"],
                "Start": (s["start"].strftime("%Y-%m-%d")
                          if s["start"] else "—"),
                "Finish": (s["finish"].strftime("%Y-%m-%d")
                           if s["finish"] else "—"),
            } for s in tr.driving_chain])
            st.dataframe(ch_df, width="stretch", hide_index=True)

    if tr.oos_flags:
        st.caption(
            f"ℹ️ {len(tr.oos_flags)} out-of-sequence record(s) in the "
            "progress donor qualify the statusing assumption (see "
            "warning above) — the full list, as-built relation fits and "
            "the repaired-.xer export live in the **Out-of-Sequence "
            "Repair** tab.")

    basis_panel("Progress Transfer", pool[prog_name], [
        "Statusing rule: RETAINED LOGIC — the network donor's planned "
        "logic is re-imposed on the transferred actuals (out-of-sequence "
        "records qualify this; see the OOS module)",
        "Both runs scheduled by the same calendar-exact engine; effects "
        "reported as DELTAS between runs, never absolute dates",
        "Logic/duration effect measured on the intersection network "
        "(activities in both files); scope effect reported separately",
    ])
    with st.expander("Statusing choices & standing caveats (always apply)"):
        for c in tr.caveats:
            st.write("•", c)
    st.download_button(
        "⬇️ Download progress-transfer report (Excel)",
        data=build_transfer_xlsx(tr),
        file_name="progress_transfer_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument."
             "spreadsheetml.sheet",
        key="ptr_dl",
    )
