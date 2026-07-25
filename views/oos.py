"""Out-of-Sequence Repair."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import state as sk
from programme import (
    OOS_CAVEATS, REPAIR_CAVEATS, apply_asbuilt_repairs, build_oos_xlsx,
)
from views._shared import (
    _fkey, cached_oos_evolution, cached_oos_flags, cached_repair_plan,
    get_parsed_files,
)


def oos_tab() -> None:
    st.caption(
        "Out-of-sequence screening: recorded actuals that contradict the "
        "network logic — each with the as-built relation the record "
        "evidences, and a repaired COPY of the .xer with the analyst-"
        "confirmed fits applied. The source file is never modified."
    )
    files = get_parsed_files()
    inv = st.session_state.get(sk.INVENTORY)
    if not files or inv is None:
        st.info("Upload programmes in the **Data Intake** tab first.")
        return

    names = [r.file_name for r in inv.revisions]
    chosen = st.selectbox(
        "Programme to screen", names, index=len(names) - 1,
        key="oos_file",
        help="Defaults to the latest revision — the file with the most "
             "recorded progress.")
    data = dict(files)[chosen]

    flags = cached_oos_flags(_fkey(chosen), data)
    if not flags:
        st.success("No out-of-sequence progress detected in "
                   f"'{chosen}' — recorded actuals are consistent with "
                   "the network logic.")
        return
    plan = cached_repair_plan(_fkey(chosen), data)
    blocked = [r for r in plan if r.blocked]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("OOS records", len(flags))
    m2.metric("Concrete as-built fits", len(plan) - len(blocked),
              help="The recorded dates evidence a relation in the "
                   "planned direction — applicable to the repaired copy.")
    m3.metric("Review class", len(flags) - len(plan),
              help="As-built order reversed, or actuals too thin. Never "
                   "auto-applied — the reversed candidate is stated for "
                   "the analyst.")
    m4.metric("Blocked", len(blocked),
              help="The pair already carries a link of the target type; "
                   "P6 bars duplicates.")

    st.markdown("**Out-of-sequence records** — ranked by overlap:")
    st.dataframe(pd.DataFrame([{
        "Predecessor": f.pred_code, "Link": f.link_type,
        "Successor": f.succ_code, "Succ name": f.succ_name,
        "Overlap (d)": f.overlap_days,
        "As-built fix": f.rec_link, "Basis": f.rec_basis,
    } for f in flags[:300]]), width="stretch", hide_index=True)
    if len(flags) > 300:
        st.caption(f"Showing 300 of {len(flags)} — the Excel export "
                   "carries the full list.")

    # ---------------- repair plan (analyst confirms) ------------------- #
    st.subheader("As-built repair plan")
    st.caption(
        "Untick any fit you do not accept. Blocked rows are never "
        "applied. Lags are observed calendar-day offsets converted at "
        "the successor's calendar; reschedule (F9) in P6 after import."
    )
    plan_df = pd.DataFrame([{
        "Apply": r.apply and not r.blocked,
        "Predecessor": r.pred_code, "Successor": r.succ_code,
        "Old link": r.old_link,
        "New link": f"{r.new_type.replace('PR_', '')} "
                    f"{r.new_lag_days_cal:+.0f}d",
        "Lag (hr)": r.new_lag_hr,
        "Blocked": r.blocked,
        "Basis": r.basis,
    } for r in plan])
    edited = st.data_editor(
        plan_df, width="stretch", hide_index=True,
        disabled=["Predecessor", "Successor", "Old link", "New link",
                  "Lag (hr)", "Blocked", "Basis"],
        key=f"oos_plan_{chosen}")
    for r, apply_sel in zip(plan, edited["Apply"].tolist()):
        r.apply = bool(apply_sel) and not r.blocked
    n_sel = sum(1 for r in plan if r.apply)

    raw = st.session_state.get(sk.XER_RAW, {}).get(chosen)
    report = None
    if raw is None:
        st.warning("Raw file text unavailable for this file — reload it "
                   "at Data Intake to enable the repaired-.xer export.")
    elif st.toggle(f"Build repaired .xer ({n_sel} fits selected)",
                   key=f"oos_build_{chosen}"):
        out_text, report = apply_asbuilt_repairs(raw, data, plan)
        if report.qa_passed:
            st.success(
                f"Round-trip QA passed — {len(report.applied)} TASKPRED "
                f"row(s) re-typed/re-lagged; relationship count "
                f"unchanged at {report.rel_count_after:,}.")
        else:
            st.error("Round-trip QA FAILED — do not use this export: "
                     + "; ".join(report.qa_notes[:3]))
        st.caption(
            f"Chain of custody — source SHA-256 "
            f"`{report.source_sha256[:16]}…` → repaired copy SHA-256 "
            f"`{report.output_sha256[:16]}…`")
        if report.not_found:
            st.warning(f"{len(report.not_found)} selected fit(s) could "
                       "not be located in the file: "
                       + ", ".join(report.not_found[:5]))
        if report.qa_passed:
            st.download_button(
                "⬇️ Download repaired .xer (as-built logic)",
                data=out_text.encode("latin-1", "replace"),
                file_name=chosen.replace(".xer", "") + "_asbuilt_repair.xer",
                mime="application/octet-stream",
                key=f"oos_xer_dl_{chosen}",
            )

    # ---------------- evolution across the revision set ---------------- #
    if len(files) >= 2:
        ordered = [(r.file_name, dict(files)[r.file_name])
                   for r in inv.revisions]
        ev = cached_oos_evolution(tuple(_fkey(n) for n, _ in ordered),
                                  ordered)
        with st.expander(
            "When did each contradiction appear? — "
            + " → ".join(f"{l}: {n}" for l, n in ev.per_revision)
        ):
            for w in ev.warnings:
                st.warning(w)
            st.dataframe(pd.DataFrame([{
                "Window": f"{w.from_label} → {w.to_label}",
                "New OOS": len(w.new_flags),
                "Resolved": w.resolved_count,
                "Total after": w.total_after,
            } for w in ev.windows]), width="stretch", hide_index=True)
            for c in ev.caveats[-1:]:
                st.caption(f"• {c}")
    else:
        ev = None

    st.download_button(
        "⬇️ Download OOS screening & repair register (Excel)",
        data=build_oos_xlsx(chosen, flags, plan, report, ev),
        file_name="oos_screening_repair.xlsx",
        mime="application/vnd.openxmlformats-officedocument."
             "spreadsheetml.sheet",
        key=f"oos_xlsx_dl_{chosen}",
    )

    with st.expander("Repair & screening caveats (always apply)"):
        for c in REPAIR_CAVEATS + OOS_CAVEATS:
            st.write("•", c)
