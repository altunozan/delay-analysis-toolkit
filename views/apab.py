"""As-Planned vs As-Built (stepped)."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

import state as sk
from programme import (
    analyse_asbuilt_path, build_apab_gantt_html, build_simple_xlsx,
    extract_actual_trace, keydate_windows, planned_vs_actual,
    trace_end_candidates, triangulate,
)
from views._shared import _fkey, basis_panel, get_parsed_files
from views._submodules import analysis_submodules
from views.hierarchy import hierarchy_tab
from views.variance import variance_tab


@st.cache_data(show_spinner=False, max_entries=8)
def cached_stitch(key: tuple, core_freq: float, _ordered):
    return analyse_asbuilt_path(_ordered, core_min_frequency=core_freq)


@st.cache_data(show_spinner=False, max_entries=8)
def cached_trace(key: tuple, end_code, _ordered):
    return extract_actual_trace(_ordered, end_task_code=end_code)


def apab_tab() -> None:
    st.caption(
        "The classic retrospective method, run as explicit steps: "
        "reconstruct what actually happened, define the as-built "
        "critical path, compare the as-built section against the "
        "planned dates, fix key dates, measure the delay. Jump between "
        "steps freely — each records what you chose."
    )
    files = get_parsed_files()
    inv = st.session_state.get(sk.INVENTORY)
    if not files or inv is None or len(files) < 2:
        st.info("Upload at least two programmes (baseline + as-built "
                "update) in **Data Intake** first.")
        return
    pool = dict(files)
    ordered = [(r.file_name, pool[r.file_name]) for r in inv.revisions]
    baseline = (pool[inv.baseline.file_name]
                if inv.baseline else ordered[0][1])
    latest_label, latest = ordered[-1]
    okey = tuple(_fkey(n) for n, _ in ordered)

    step = st.radio(
        "Method step",
        ["① Structure the works", "② As-built critical path",
         "③ Planned-dates comparison", "④ Key dates",
         "⑤ Windows & delay"],
        horizontal=True, key="apab_step")

    # ---------------- ① structure the works (hierarchy rebuild) -------- #
    if step.startswith("①"):
        st.subheader("① Structure the works — rebuild the hierarchy")
        st.caption(
            "Before any comparison, organise the as-built programme "
            "into the sections the works were actually delivered in "
            "(any mix of WBS levels and activity codes) and review the "
            "real sequence section by section. This structure carries "
            "no analytical assumption — it is a read-only lens, and the "
            "same breakdown is used for the grouped comparison in "
            "step ③.")
        hierarchy_tab()

    # ---------------- ② define the as-built critical path -------------- #
    elif step.startswith("②"):
        st.subheader("② Define the as-built critical path")
        basis = st.radio(
            "Basis — the analyst's definitional choice, recorded in the "
            "measurement",
            ["Activity-level (backward trace through actual dates)",
             "Reconstructed sequence (stitched contemporaneous paths)"],
            key="apab_basis_pick")
        if basis.startswith("Activity"):
            cands = trace_end_candidates(ordered)
            labels = {c: f"{c} — {n}" + (f" (AF {d:%Y-%m-%d})" if d
                                         else "")
                      for c, n, d in cands}
            end = st.selectbox("Trace backward from", list(labels),
                               format_func=lambda k: labels[k],
                               key="apab_end")
            tr = cached_trace(okey, end, ordered)
            for w in tr.warnings:
                st.warning(w)
            path = [(a.task_code, a.name) for a in tr.activities]
            st.dataframe(pd.DataFrame([{
                "Activity ID": a.task_code, "Activity": a.name,
                "Actual start": (f"{a.act_start:%Y-%m-%d}"
                                 if a.act_start else "—"),
                "Actual finish": (f"{a.act_finish:%Y-%m-%d}"
                                  if a.act_finish else "—"),
            } for a in tr.activities]), width="stretch",
                hide_index=True)
            with st.expander("Cross-check: where do the two independent "
                             "reconstructions agree?"):
                stitch = cached_stitch(
                    okey, st.session_state.get(sk.APAB_STITCH_FREQ, 0.5),
                    ordered)
                tri = triangulate(stitch, tr)
                both = getattr(tri, "agreed_codes", None) or [
                    c for c in tr.codes
                    if c in {a.task_code for a in stitch.stitched}]
                st.write(f"**{len(both)}** activities identified by "
                         "BOTH methods (method-invariant findings).")
        else:
            core_freq = st.slider(
                "Persistence threshold (fraction of revisions an "
                "activity must have been on the forecast path)",
                0.2, 1.0, 0.5, 0.05, key="apab_freq")
            st.session_state[sk.APAB_STITCH_FREQ] = core_freq
            stitch = cached_stitch(okey, core_freq, ordered)
            for w in stitch.warnings:
                st.warning(w)
            path = [(a.task_code, a.name) for a in stitch.stitched]
            st.write(f"Reconstructed-sequence basis: **{len(path)}** "
                     "activities, stitched from the contemporaneous "
                     "forecast paths:")
            st.dataframe(pd.DataFrame([{
                "Activity ID": a.task_code, "Activity": a.name,
                "Actual start": (f"{a.act_start:%Y-%m-%d}"
                                 if a.act_start else "—"),
                "Actual finish": (f"{a.act_finish:%Y-%m-%d}"
                                  if a.act_finish else "—"),
                "On forecast path of": a.forecast_by,
            } for a in stitch.stitched[:400]]), width="stretch",
                hide_index=True)
        if st.button("Use this as the as-built critical path →",
                     type="primary", key="apab_adopt"):
            st.session_state[sk.APAB_PATH] = path
            st.session_state[sk.APAB_PATH_BASIS] = basis
            st.success(f"Adopted: {len(path)} activities. Steps ③-⑤ "
                       "now use this path.")

    # ---------------- ③ planned-dates comparison ----------------------- #
    elif step.startswith("③"):
        st.subheader("③ As-built section vs PLANNED dates")
        path = st.session_state.get(sk.APAB_PATH)
        scope = st.radio(
            "Comparison scope",
            ["As-built critical path (adopted in step ②)",
             "All matched activities"],
            key="apab_scope",
            help="The comparison need not be the critical path — choose "
                 "the as-built section you want compared on planned "
                 "dates.")
        codes = ({c for c, _ in path} if path and scope.startswith("As")
                 else None)
        if scope.startswith("As") and not path:
            st.info("No path adopted yet — showing all matched "
                    "activities. Adopt a path in step ②.")
        rows = planned_vs_actual(baseline, latest, codes)
        matched = [r for r in rows if r["in_baseline"]]
        fv = [r["finish_var_days"] for r in matched
              if r["finish_var_days"] is not None]
        m1, m2, m3 = st.columns(3)
        m1.metric("Activities compared", len(rows))
        m2.metric("Mean finish variance",
                  f"{sum(fv)/len(fv):+.0f} d" if fv else "—")
        m3.metric("Worst finish variance",
                  f"{max(fv):+.0f} d" if fv else "—")
        st.iframe(
            build_apab_gantt_html(
                rows, keydates=st.session_state.get(sk.APAB_KEYDATES),
                title="As-planned vs as-built — comparison"),
            height=560)
        with st.expander("Comparison table (all columns)"):
            st.dataframe(pd.DataFrame([{
                "Activity ID": r["task_code"], "Activity": r["name"][:50],
                "Planned start": (f"{r['planned_start']:%Y-%m-%d}"
                                  if r["planned_start"] else "—"),
                "Planned finish": (f"{r['planned_finish']:%Y-%m-%d}"
                                   if r["planned_finish"] else "—"),
                "Actual start": (f"{r['actual_start']:%Y-%m-%d}"
                                 if r["actual_start"] else "—"),
                "Actual finish": (f"{r['actual_finish']:%Y-%m-%d}"
                                  if r["actual_finish"] else "—"),
                "Start var (d)": r["start_var_days"],
                "Finish var (d)": r["finish_var_days"],
            } for r in rows[:400]]), width="stretch", hide_index=True)
        st.session_state[sk.APAB_CMP_ROWS] = rows
        with st.expander("Breakdown view (by activity code / WBS — the "
                         "grouped comparison tool)"):
            variance_tab()

    # ---------------- ④ key dates from the as-built CP ----------------- #
    elif step.startswith("④"):
        st.subheader("④ Define the key dates")
        path = st.session_state.get(sk.APAB_PATH)
        if not path:
            st.info("Adopt an as-built critical path in step ② first.")
            return
        saved = st.session_state.get(sk.APAB_KEYDATES, {})
        kd_df = pd.DataFrame([{
            "Key date": c in saved,
            "Activity ID": c, "Activity": n[:60],
            "Why it is key (contractual / logic significance)":
                saved.get(c, ""),
        } for c, n in path])
        edited = st.data_editor(
            kd_df, width="stretch", hide_index=True,
            disabled=["Activity ID", "Activity"], key="apab_kd_ed")
        kd = {}
        for _, r in edited.iterrows():
            if bool(r["Key date"]):
                kd[r["Activity ID"]] = str(
                    r["Why it is key (contractual / logic "
                      "significance)"] or "")
        st.session_state[sk.APAB_KEYDATES] = kd
        st.success(f"{len(kd)} key date(s) defined."
                   if kd else "Tick the activities that carry key dates.")

    # ---------------- ⑤ windows from key dates + measurement ----------- #
    else:
        st.subheader("⑤ Analysis windows & delay measurement")
        rows = st.session_state.get(sk.APAB_CMP_ROWS) or planned_vs_actual(
            baseline, latest,
            {c for c, _ in st.session_state.get(sk.APAB_PATH, [])} or None)
        kd = st.session_state.get(sk.APAB_KEYDATES, {})
        by_code = {r["task_code"]: r for r in rows}
        kd_rows = []
        for c, why in kd.items():
            r = by_code.get(c)
            if r:
                kd_rows.append({
                    "Key date": c, "Activity": r["name"][:50],
                    "Planned finish": r["planned_finish"],
                    "Actual finish": r["actual_finish"],
                    "Delay (d)": r["finish_var_days"], "Why key": why})

        # windows are bounded by the analyst's key dates (step ④) —
        # distinct from the standalone Windows Analysis tool, whose
        # windows are bounded by revision data dates.
        kwin = keydate_windows(rows, list(kd)) if len(kd) >= 2 else []
        if kwin:
            st.markdown("**Analysis windows — bounded by your key "
                        "dates, in as-built order:**")
            st.dataframe(pd.DataFrame([{
                "Window": f"W{i}: {w['from_code']} → {w['to_code']}",
                "Planned interval (d)": w["planned_interval_days"],
                "Actual interval (d)": w["actual_interval_days"],
                "Window delay (d)": w["window_delay_days"],
                "Resequenced": ("⚠️ YES — excluded from cumulative"
                                if w.get("resequenced") else ""),
                "Cumulative (d)": w["cumulative_delay_days"],
            } for i, w in enumerate(kwin, start=1)]),
                width="stretch", hide_index=True)
            st.caption(
                "Window delay = actual interval minus planned interval "
                "between consecutive key dates (calendar days); "
                "positive = the works through that window took longer "
                "than planned.")
        elif kd:
            st.info("Define at least TWO key dates in step ④ to bound "
                    "analysis windows between them.")
        planned_fin = max((r["planned_finish"] for r in rows
                           if r["planned_finish"]), default=None)
        actual_fin = max((r["actual_finish"] for r in rows
                          if r["actual_finish"]), default=None)
        overall = ((actual_fin - planned_fin).days
                   if planned_fin and actual_fin else None)
        st.iframe(
            build_apab_gantt_html(
                rows, keydates=kd,
                overall_delay_days=float(overall)
                if overall is not None else None,
                title="As-built (above) vs as-planned (below)"),
            height=560)
        m1, m2, m3 = st.columns(3)
        m1.metric("Planned completion (section)",
                  f"{planned_fin:%d %b %Y}" if planned_fin else "—")
        m2.metric("Actual completion (section)",
                  f"{actual_fin:%d %b %Y}" if actual_fin else "—")
        m3.metric("MEASURED DELAY", f"{overall:+d} d"
                  if overall is not None else "—")
        if kd_rows:
            st.markdown("**Key-date delays:**")
            st.dataframe(pd.DataFrame([{
                **{k: (f"{v:%Y-%m-%d}" if isinstance(v, datetime)
                       else v) for k, v in r.items()}}
                for r in kd_rows]), width="stretch", hide_index=True)
        else:
            st.caption("No key dates defined (step ④) — measuring on "
                       "the section's completion only.")
        basis_panel("As-Planned vs As-Built", latest, [
            f"As-built critical path basis: "
            f"{st.session_state.get('apab_path_basis', 'not adopted')}",
            "Planned dates from the flagged contract baseline; actual "
            "dates from the latest revision as recorded; variances in "
            "calendar days",
            f"{len(kd)} analyst-defined key date(s)",
        ])
        st.download_button(
            "⬇️ Download as-planned vs as-built workbook (Excel)",
            data=build_simple_xlsx(
                "As-Planned vs As-Built",
                {"Comparison": [{k: v for k, v in r.items()}
                                for r in rows],
                 "Key dates": kd_rows or [{}],
                 "Key-date windows": kwin or [{}]},
                notes=["Method: as-planned vs as-built, stepped. "
                       "As-built path basis: "
                       + st.session_state.get(sk.APAB_PATH_BASIS,
                                              "not adopted"),
                       "Variances in calendar days; positive = later "
                       "than planned. 'As-recorded' caveat applies: "
                       "actual dates are as recorded in the file, not "
                       "independently verified."]),
            file_name="as_planned_vs_as_built.xlsx",
            mime="application/vnd.openxmlformats-officedocument."
                 "spreadsheetml.sheet",
            key="apab_dl")

    analysis_submodules("apab")
