"""Windows Analysis."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import state as sk
from programme import build_windows_prompt, build_windows_xlsx
from programme.narrative import DEFAULT_TEMPLATES
from views._shared import (
    _fkey, ai_narrative_panel, basis_panel, cached_windows, get_parsed_files,
)
from views._submodules import analysis_submodules


def windows_tab() -> None:
    st.caption(
        "TIME-SLICE windows analysis: the project timeline is cut into "
        "windows bounded by the REVISION DATA DATES (each submitted "
        "update opens a new slice), and completion movement plus the "
        "driving-path change is measured inside each slice — the "
        "contemporaneous record tells you WHEN the delay arose. This "
        "is distinct from the key-date windows inside As-Planned vs "
        "As-Built, whose boundaries are the analyst's key dates."
    )
    files = get_parsed_files()
    inv = st.session_state.get(sk.INVENTORY)
    if not files or inv is None or len(files) < 2:
        st.info("Upload at least two programmes in the **Data Intake** tab "
                "first.")
        return

    pool = dict(files)
    ordered = [(r.file_name, pool[r.file_name]) for r in inv.revisions]
    res = cached_windows(
        (tuple(_fkey(n) for n, _ in ordered),
         st.session_state.get(sk.CONTRACT_MS)), ordered,
        st.session_state.get(sk.CONTRACT_MS))
    basis_panel("Windows Analysis", ordered[-1][1], [
        "Per-window driving path: independent longest-path trace of "
        "each revision to "
        + (f"the CONTRACTUAL completion milestone "
           f"{st.session_state.get(sk.CONTRACT_MS)}"
           if st.session_state.get(sk.CONTRACT_MS)
           else "its latest incomplete finisher (no contractual "
                "completion milestone elected at intake)"),
        "Completion movement: calendar days between the revisions' "
        "scheduled finish dates as submitted (no recompute)",
    ])
    if not res.windows:
        for w in res.warnings:
            st.warning(w)
        return

    m1, m2, m3 = st.columns(3)
    m1.metric("Windows", len(res.windows))
    m2.metric("Cumulative completion movement",
              f"{res.total_movement_days:+.0f} d"
              if res.total_movement_days is not None else "—")
    worst = max((w for w in res.windows if w.movement_days is not None),
                key=lambda w: w.movement_days, default=None)
    m3.metric("Largest window movement",
              f"{worst.movement_days:+.0f} d (window {worst.index})"
              if worst else "—")

    for w in res.warnings:
        (st.success if w.startswith("Favourable") else st.warning)(w)

    # Completion trajectory: scheduled finish as at each data date.
    traj = []
    for w in res.windows:
        if w.start and w.finish_old:
            traj.append({"Data date": w.start, "Completion": w.finish_old})
    last = res.windows[-1]
    if last.end and last.finish_new:
        traj.append({"Data date": last.end, "Completion": last.finish_new})
    c1, c2 = st.columns(2)
    if len(traj) >= 2:
        c1.altair_chart(
            alt.Chart(pd.DataFrame(traj))
            .mark_line(point=True, interpolate="step-after")
            .encode(
                x=alt.X("Data date:T", axis=alt.Axis(format="%b %Y")),
                y=alt.Y("Completion:T", title="Scheduled completion",
                        scale=alt.Scale(zero=False),
                        axis=alt.Axis(format="%b %Y")),
                tooltip=[alt.Tooltip("Data date:T", format="%d %b %Y"),
                         alt.Tooltip("Completion:T", format="%d %b %Y")],
            ).properties(height=260, title="Completion trajectory"),
            width="stretch",
        )
    mv = [{"Window": f"W{w.index}: {w.from_label} → {w.to_label}",
           "Movement (d)": w.movement_days}
          for w in res.windows if w.movement_days is not None]
    if mv:
        _mv_base = alt.Chart(pd.DataFrame(mv)).encode(
            x=alt.X("Window:N", sort=None, title=None,
                    axis=alt.Axis(labelAngle=-20, labelLimit=200)),
            y=alt.Y("Movement (d):Q"),
            tooltip=["Window", "Movement (d)"])
        _mv_bars = _mv_base.mark_bar(cornerRadius=2).encode(
            color=alt.condition("datum['Movement (d)'] > 0",
                                alt.value("#9B3227"),
                                alt.value("#3F6B4F")))
        # value labels on every bar (AAA rule) — above positive bars,
        # below negative ones
        _mv_lp = (_mv_base.transform_filter("datum['Movement (d)'] >= 0")
                  .mark_text(dy=-7, fontWeight="bold", fontSize=11)
                  .encode(text=alt.Text("Movement (d):Q", format="+.0f")))
        _mv_ln = (_mv_base.transform_filter("datum['Movement (d)'] < 0")
                  .mark_text(dy=13, fontWeight="bold", fontSize=11)
                  .encode(text=alt.Text("Movement (d):Q", format="+.0f")))
        c2.altair_chart(
            (_mv_bars + _mv_lp + _mv_ln)
            .properties(height=260, title="Movement per window"),
            width="stretch",
        )

    # ---- waterfall: the bifurcation arithmetic made visible ----------- #
    bif = [w for w in res.windows
           if w.performance_days is not None
           and w.replanning_days is not None]
    if bif:
        st.subheader("Window decomposition — performance vs replanning")
        _wlbl = [f"W{w.index}: {w.from_label} → {w.to_label}" for w in bif]
        _wi = max(range(len(bif)),
                  key=lambda i: abs(bif[i].movement_days or 0))
        _pick = st.selectbox("Window to decompose", _wlbl, index=_wi,
                             key="win_wf_pick")
        _w = bif[_wlbl.index(_pick)]
        _perf, _rep = _w.performance_days, _w.replanning_days
        _net = (_w.engine_window_days
                if _w.engine_window_days is not None
                else round(_perf + _rep, 1))
        _wf = pd.DataFrame([
            {"Step": "Performance", "start": 0.0, "end": _perf,
             "kind": "perf", "lbl": f"{_perf:+.1f}"},
            {"Step": "Replanning", "start": _perf, "end": _perf + _rep,
             "kind": "replan", "lbl": f"{_rep:+.1f}"},
            {"Step": "Net movement", "start": 0.0, "end": _net,
             "kind": "net", "lbl": f"{_net:+.1f}"},
        ])
        _wf["top"] = _wf[["start", "end"]].max(axis=1)
        _wb = alt.Chart(_wf).encode(
            x=alt.X("Step:N", sort=None, title=None,
                    axis=alt.Axis(labelAngle=0)))
        _bars = _wb.mark_bar(size=52).encode(
            y=alt.Y("start:Q", title="days"), y2="end:Q",
            color=alt.Color("kind:N", legend=None, scale=alt.Scale(
                domain=["perf", "replan", "net"],
                range=["#9B3227", "#3F6B4F", "#14324A"])),
            tooltip=["Step", "lbl"])
        # sign carried in the label — the meaning never rests on colour
        _lbls = _wb.mark_text(dy=-8, fontWeight="bold", fontSize=12).encode(
            y=alt.Y("top:Q"), text="lbl:N")
        _zero = alt.Chart(pd.DataFrame({"y": [0.0]})).mark_rule(
            strokeDash=[4, 3], color="#5B7994").encode(y="y:Q")
        st.altair_chart(
            (_bars + _lbls + _zero).properties(
                height=300, title=f"{_pick} — movement decomposed"),
            width="stretch")
        st.caption(
            f"Execution moved the forecast {_perf:+.1f} d against the "
            f"prior plan; the update's own edits moved it {_rep:+.1f} d; "
            f"net engine movement {_net:+.1f} d vs file-scheduled "
            f"{(_w.movement_days if _w.movement_days is not None else 0):+.0f} d "
            "(difference = disclosed engine calibration). The components "
            "sum exactly — the identity is QA-pinned — which is what "
            "makes a waterfall honest here.")

    st.subheader("Windows")
    st.dataframe(pd.DataFrame([{
        "#": w.index,
        "From": w.from_label,
        "To": w.to_label,
        "Period": (f"{w.start:%Y-%m-%d} → {w.end:%Y-%m-%d}"
                   if w.start and w.end else "—"),
        "Window (d)": w.window_days,
        "Movement (d)": w.movement_days,
        "Performance (d)": w.performance_days,
        "Replanning (d)": w.replanning_days,
        "..logic (d)": w.replan_logic_days,
        "..scope (d)": w.replan_scope_days,
        "Path retained": w.cp_retained,
        "Path similarity": (f"{w.cp_similarity:.0%}"
                            if w.cp_similarity is not None else "—"),
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
                f"Window {w.index} path changes — {len(w.joined)} joined, "
                f"{len(w.left)} left ({w.from_label} → {w.to_label})"
            ):
                st.dataframe(pd.DataFrame([{
                    "Direction": s.direction,
                    "Activity ID": s.task_code,
                    "Activity": s.name,
                } for s in w.shifts]), width="stretch",
                    hide_index=True)

    st.caption(
        "ℹ️ Out-of-sequence progress per window (which update introduced "
        "each contradiction) lives in the **Out-of-Sequence Repair** tab.")

    with st.expander("Standing caveats (always apply)"):
        for c in res.caveats:
            st.write("•", c)

    narrative = ai_narrative_panel(
        "nar_windows",
        lambda tmpl: build_windows_prompt(res, tmpl),
        "windows",
        DEFAULT_TEMPLATES["windows"],
    )
    st.download_button(
        "⬇️ Download windows report (Excel)",
        data=build_windows_xlsx(res, narrative),
        file_name="windows_analysis_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    analysis_submodules("windows")
