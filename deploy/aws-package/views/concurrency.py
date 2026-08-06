"""Concurrent-Delay Screening (embedded sub-analysis)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import state as sk
from programme import build_concurrency_xlsx, screen_concurrency
from views._shared import (
    _fkey, _register_records, cached_windows, get_parsed_files,
)


def concurrency_tab() -> None:
    st.caption(
        "The most-litigated question in delay disputes: per analysis "
        "window, do Employer-asserted and Contractor-asserted events "
        "overlap while completion moved? Screening only — overlap is "
        "necessary but not sufficient for concurrency; the contractual "
        "test is the analyst's."
    )
    files = get_parsed_files()
    inv = st.session_state.get(sk.INVENTORY)
    if not files or inv is None or len(files) < 2:
        st.info("Upload at least two programmes in **Data Intake** "
                "first — the screening works per analysis window.")
        return
    recs = _register_records()
    if not recs:
        st.info(
            "No delay events in the shared register yet. Save events "
            "from **Impacted As-Planned** step ① or **Time Impact "
            "Analysis** — this screening reads whatever the analyses "
            "have registered.")
        return

    pool = dict(files)
    ordered = [(r.file_name, pool[r.file_name]) for r in inv.revisions]
    wres = cached_windows(
        (tuple(_fkey(n) for n, _ in ordered),
         st.session_state.get(sk.CONTRACT_MS)), ordered,
        st.session_state.get(sk.CONTRACT_MS))
    res = screen_concurrency(wres, recs)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Windows screened", len(res.windows))
    m2.metric("Events screened", len(res.events))
    m3.metric("Concurrent candidates",
              sum(1 for w in res.windows if w.concurrent_candidate))
    m4.metric("Pacing flags",
              sum(1 for w in res.windows if w.pacing_flag))
    for w in res.warnings:
        st.warning(w)

    st.markdown("**Screening matrix** — asserted-event overlap per "
                "window:")
    st.dataframe(pd.DataFrame([{
        "Window": f"W{w.index}: {w.from_label} → {w.to_label}",
        "Movement (d)": w.movement_days,
        "Employer (d)": w.employer_days,
        "Contractor (d)": w.contractor_days,
        "Both (d)": w.both_days,
        "Unclassified (d)": w.unclassified_days,
        "Concurrent candidate": "🚩 YES" if w.concurrent_candidate else "",
        "Pacing": "❓ enquire" if w.pacing_flag else "",
        "Events": ", ".join((w.employer_events + w.contractor_events
                             + w.unclassified_events)[:6]),
    } for w in res.windows]), width="stretch", hide_index=True)

    with st.expander("Events as screened (spans and asserted party)"):
        st.dataframe(pd.DataFrame([{
            "Event": e.event_id, "Title": e.title,
            "Asserted": e.asserted, "Party": e.party,
            "From": f"{e.start:%Y-%m-%d}", "To": f"{e.end:%Y-%m-%d}",
            "Days": e.duration_days,
            "Note": ("no fragnet — single day" if e.single_day else ""),
        } for e in res.events]), width="stretch", hide_index=True)

    with st.expander("Screening caveats (always apply)"):
        for c in res.caveats:
            st.write("•", c)

    st.download_button(
        "⬇️ Download concurrency screening (Excel)",
        data=build_concurrency_xlsx(res),
        file_name="concurrency_screening.xlsx",
        mime="application/vnd.openxmlformats-officedocument."
             "spreadsheetml.sheet",
        key="conc_dl",
    )
