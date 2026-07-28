"""Explain This Delay (embedded sub-analysis)."""

from __future__ import annotations

from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

import state as sk
from programme import explain_appendix
from programme import build_explain_prompt, build_explain_xlsx, explain_delay
from programme.narrative import DEFAULT_TEMPLATES
from views._shared import ai_narrative_panel, get_parsed_files


def explain_tab() -> None:
    st.caption(
        "Pick a milestone and ask why it moved: recorded dates per "
        "revision (facts) and the activities that joined its driving path "
        "per window (inferred candidate drivers, flagged where uncertain)."
    )
    files = get_parsed_files()
    inv = st.session_state.get(sk.INVENTORY)
    if not files or inv is None or len(files) < 2:
        st.info("Upload at least two programmes in the **Data Intake** "
                "tab first.")
        return
    pool = dict(files)
    ordered = [(r.file_name, pool[r.file_name]) for r in inv.revisions]
    latest = ordered[-1][1]
    ms = [t for t in latest.tasks
          if t.is_milestone and not t.is_loe_or_wbs]
    ms.sort(key=lambda t: (t.act_finish or t.early_finish
                           or t.early_start or datetime.max), reverse=True)
    if not ms:
        st.warning("No milestones found in the latest revision.")
        return
    labels = {t.task_code: f"{t.task_code} — {t.name}" for t in ms}
    target = st.selectbox(
        "Milestone to explain", options=list(labels.keys()),
        format_func=lambda c: labels[c], key="exp_target",
        help="Latest finishers first — the completion milestone usually "
             "leads the list.")
    res = explain_delay(ordered, target)

    m1, m2, m3 = st.columns(3)
    m1.metric("Total movement",
              f"{res.total_movement_days:+.0f} d"
              if res.total_movement_days is not None else "—")
    m2.metric("Windows analysed", len(res.windows))
    m3.metric("Status", "Achieved ✅" if res.achieved else "Forecast")
    for w in res.warnings:
        (st.success if w.startswith("Favourable") else st.warning)(w)

    pts = [{"Data date": p.data_date, "Milestone date": p.forecast,
            "Revision": p.label,
            "Kind": "Actual" if p.is_actual else "Forecast"}
           for p in res.points if p.data_date and p.forecast]
    if len(pts) >= 2:
        st.altair_chart(
            alt.Chart(pd.DataFrame(pts)).mark_line(point=True,
                                                   color="#9B3227")
            .encode(
                x=alt.X("Data date:T", axis=alt.Axis(format="%b %Y")),
                y=alt.Y("Milestone date:T", scale=alt.Scale(zero=False),
                        axis=alt.Axis(format="%b %Y")),
                tooltip=["Revision", "Kind",
                         alt.Tooltip("Data date:T", format="%d %b %Y"),
                         alt.Tooltip("Milestone date:T",
                                     format="%d %b %Y")],
            ).properties(height=260,
                         title=f"{target} — recorded date by data date "
                               "(facts)"),
            width="stretch")

    st.subheader("Windows: facts and inferred drivers")
    st.dataframe(pd.DataFrame([{
        "Window": f"W{w.index}: {w.from_label} → {w.to_label}",
        "Pre": f"{w.pre:%Y-%m-%d}" if w.pre else "—",
        "Post": f"{w.post:%Y-%m-%d}" if w.post else "—",
        "Movement (d)": w.movement_days,
        "Path similarity": (f"{w.path_similarity:.0f}%"
                            if w.path_similarity is not None else "—"),
        "Attribution": ("reliable" if w.attribution_reliable
                        else "UNCERTAIN"),
        "Joined / left path": f"{len(w.joined)} / {len(w.left)}",
    } for w in res.windows]), width="stretch", hide_index=True)
    st.caption(
        "Movement = the files' scheduled finishes. Performance / "
        "Replanning = the window BIFURCATED: prior schedule re-run "
        "with the later update's progress only. A big replanning "
        "share means the update's edits (not execution) moved the "
        "forecast — recovery or covert re-baselining inside that "
        "window.")

    for w in res.windows:
        if w.shifts:
            with st.expander(
                f"Window {w.index} inferred drivers — {len(w.joined)} "
                f"joined, {len(w.left)} left"
                + ("" if w.attribution_reliable
                   else "  ⚠️ attribution uncertain")):
                st.dataframe(pd.DataFrame([{
                    "Direction": s.direction,
                    "Activity ID": s.task_code,
                    "Activity": s.name,
                } for s in w.shifts]), width="stretch",
                    hide_index=True)

    # ---------------- analyst confirmation of drivers ------------------- #
    st.subheader("Promote candidates to confirmed drivers")
    st.caption(
        "Everything above is INFERENCE — candidates only. Tick a driver "
        "you have verified against the records and say what the evidence "
        "is; unconfirmed rows stay candidates. Confirmations flow into "
        "the Excel export and the assembled report."
    )
    cand_rows = [{
        "Window": f"W{w.index}: {w.from_label} → {w.to_label}",
        "Direction": s.direction,
        "Activity ID": s.task_code,
        "Activity": s.name,
        "Confirmed": False,
        "Evidence note": "",
    } for w in res.windows for s in w.shifts]
    if cand_rows:
        saved = st.session_state.get(f"explain_confirmed_{target}", {})
        for row in cand_rows:
            k = (row["Window"], row["Activity ID"], row["Direction"])
            if k in saved:
                row["Confirmed"] = True
                row["Evidence note"] = saved[k]
        edited = st.data_editor(
            pd.DataFrame(cand_rows), width="stretch", hide_index=True,
            disabled=["Window", "Direction", "Activity ID", "Activity"],
            key=f"explain_ed_{target}")
        confirmed = {}
        missing_note = 0
        for _, row in edited.iterrows():
            if bool(row["Confirmed"]):
                note = str(row["Evidence note"] or "").strip()
                if not note:
                    missing_note += 1
                confirmed[(row["Window"], row["Activity ID"],
                           row["Direction"])] = note
        st.session_state[f"explain_confirmed_{target}"] = confirmed
        if missing_note:
            st.warning(f"{missing_note} confirmed driver(s) have no "
                       "evidence note — a confirmation without evidence "
                       "is just an assertion; add the document/record "
                       "you verified against.")
        if confirmed:
            st.success(f"{len(confirmed)} driver(s) confirmed by the "
                       "analyst (of "
                       f"{len(cand_rows)} candidates). The rest remain "
                       "candidates.")

    with st.expander("Standing caveats (always apply)"):
        for c in res.caveats:
            st.write("•", c)

    narrative = ai_narrative_panel(
        f"nar_explain_{target}",
        lambda tmpl, r=res: build_explain_prompt(r, tmpl),
        "explain",
        DEFAULT_TEMPLATES["explain"],
        appendix_builder=lambda: explain_appendix(res),
    )
    conf_map = st.session_state.get(f"explain_confirmed_{target}", {})
    names_by_code = {s.task_code: s.name
                     for w in res.windows for s in w.shifts}
    conf_rows = [{
        "window": k[0], "task_code": k[1], "direction": k[2],
        "name": names_by_code.get(k[1], ""), "note": note,
    } for k, note in conf_map.items()]
    st.download_button(
        "⬇️ Download 'explain this delay' report (Excel)",
        data=build_explain_xlsx(res, narrative, confirmed=conf_rows),
        file_name=f"explain_delay_{target}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
