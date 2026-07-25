"""Impacted As-Planned."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

import state as sk
from programme import (
    DelayEvent, FragnetActivity, FragnetLink, build_iap_xlsx, event_to_dict,
    run_impacted_asplanned,
)
from views._shared import _register_records, basis_panel, get_parsed_files
from views._submodules import analysis_submodules


def impacted_asplanned_tab() -> None:
    st.caption(
        "Impacted As-Planned: the event fragnets inserted into the "
        "ORIGINAL BASELINE (no progress), completion movement measured "
        "per event. A recognised but weak, theoretical method — use "
        "where the contract prescribes it, and disclose its limits."
    )
    files = get_parsed_files()
    inv = st.session_state.get(sk.INVENTORY)
    if not files or inv is None:
        st.info("Upload programmes in **Data Intake** first.")
        return

    names = [r.file_name for r in inv.revisions]
    base_idx = (names.index(inv.baseline.file_name)
                if inv.baseline else 0)
    chosen = st.selectbox("Baseline programme", names, index=base_idx,
                          help="Defaults to the flagged contract "
                               "baseline.")
    data = dict(files)[chosen]
    base_codes = sorted(t.task_code for t in data.tasks
                        if not t.is_loe_or_wbs)

    # ---- ① events captured HERE (standalone — no TIA required) -------- #
    st.subheader("① Delay events for this method")
    st.caption(
        "Define the events directly here: each becomes a single-"
        "activity fragnet between its tie-in activities in the "
        "baseline. (Optionally import richer fragnets already saved to "
        "the shared register — never required.)")
    iap_rows = st.session_state.get(sk.IAP_EVENTS, [{
        "Event ID": "EVT-01", "Title": "", "Date (YYYY-MM-DD)": "",
        "Responsibility (asserted)": "Employer",
        "Duration (working days)": 10.0,
        "Tie-in predecessor (activity ID)": "",
        "Tie-in successor (activity ID)": "",
    }])
    edited = st.data_editor(
        pd.DataFrame(iap_rows), width="stretch", hide_index=True,
        num_rows="dynamic", key="iap_ed")
    st.session_state[sk.IAP_EVENTS] = edited.to_dict("records")

    recs = []
    problems = []
    for r in st.session_state[sk.IAP_EVENTS]:
        eid = str(r.get("Event ID") or "").strip()
        if not eid:
            continue
        try:
            dt = datetime.strptime(
                str(r.get("Date (YYYY-MM-DD)") or "").strip(),
                "%Y-%m-%d")
        except ValueError:
            problems.append(f"{eid}: date must be YYYY-MM-DD")
            continue
        pred = str(r.get("Tie-in predecessor (activity ID)")
                   or "").strip()
        succ = str(r.get("Tie-in successor (activity ID)") or "").strip()
        for c in (pred, succ):
            if c and c not in base_codes:
                problems.append(f"{eid}: tie-in '{c}' is not in the "
                                "baseline")
        if not pred and not succ:
            problems.append(f"{eid}: needs at least one tie-in "
                            "activity ID")
            continue
        ev = DelayEvent(eid, str(r.get("Title") or eid),
                        date_raised=dt,
                        responsibility_asserted=str(
                            r.get("Responsibility (asserted)") or ""))
        frag = [FragnetActivity(
            f"{eid}-F1", str(r.get("Title") or eid),
            float(r.get("Duration (working days)") or 1.0),
            predecessors=[FragnetLink(pred)] if pred else [],
            successors=[FragnetLink(succ)] if succ else [])]
        recs.append((ev, frag))
    for p in problems:
        st.warning(p)

    reg = _register_records(require_fragnet=True)
    use_reg = False
    if reg:
        use_reg = st.toggle(
            f"Also include the {len(reg)} event(s) with confirmed "
            "fragnets from the shared register", key="iap_use_reg")
    if use_reg:
        have = {e.event_id for e, _ in recs}
        recs += [(e, f) for e, f in reg if e.event_id not in have]

    st.subheader("② Insert into the baseline and measure")
    if not recs:
        st.info("Define at least one valid event above.")
        return
    cA, cB = st.columns([2, 1])
    if cA.button(f"Run impacted as-planned ({len(recs)} event(s), "
                 "date order)", type="primary", key="iap_go"):
        st.session_state[sk.IAP_RES] = run_impacted_asplanned(
            data, chosen, recs)
    if cB.button("💾 Save events to the shared register",
                 key="iap_save_reg",
                 help="Makes them available to the concurrency "
                      "sub-module and other methods."):
        for e, f in recs:
            st.session_state.setdefault(sk.EVENT_REGISTER, {})[
                e.event_id] = event_to_dict(e, f, None)
        st.success(f"{len(recs)} event(s) saved.")
        st.session_state[sk.IAP_LABEL] = chosen
    iap = st.session_state.get(sk.IAP_RES)
    if not iap:
        return

    m1, m2, m3 = st.columns(3)
    m1.metric("Baseline completion",
              f"{iap['completion_pre']:%d %b %Y}"
              if iap.get("completion_pre") else "—")
    m2.metric("Impacted completion",
              f"{iap['completion_final']:%d %b %Y}"
              if iap.get("completion_final") else "—")
    m3.metric("Total modelled impact",
              f"{iap['total_delta_days']:+.1f} d"
              if iap.get("total_delta_days") is not None else "—")
    for w in iap.get("warnings", []):
        st.warning(w)
    if iap.get("rows"):
        st.dataframe(pd.DataFrame([{
            "Event": r["event_id"], "Title": r["title"],
            "Date": (f"{r['date_raised']:%Y-%m-%d}"
                     if r["date_raised"] else "—"),
            "Incremental (d)": r["incremental_delta_days"],
            "Completion after": (f"{r['completion_after']:%Y-%m-%d}"
                                 if r["completion_after"] else "—"),
        } for r in iap["rows"]]), width="stretch", hide_index=True)
    for c in iap.get("concurrency", []):
        st.warning(c)
    basis_panel("Impacted As-Planned", data, [
        "Method: impacted as-planned — fragnets inserted into the "
        "ORIGINAL BASELINE in date order; no progress applied",
        "Same calendar-exact engine pre- and post-insertion; movement "
        "reported as the delta between runs",
    ])
    with st.expander("Method caveats (always apply — this method is "
                     "the weakest of the recognised family)"):
        for c in iap.get("caveats", []):
            st.write("•", c)
        if iap.get("caveat"):
            st.write("•", iap["caveat"])
    st.download_button(
        "⬇️ Download impacted as-planned report (Excel)",
        data=build_iap_xlsx(st.session_state.get(sk.IAP_LABEL, chosen),
                            iap),
        file_name="impacted_asplanned_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument."
             "spreadsheetml.sheet",
        key="iap_dl",
    )
    analysis_submodules("iap")
