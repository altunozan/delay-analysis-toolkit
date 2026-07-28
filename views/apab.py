"""As-Planned vs As-Built — the 4-step method (Ozan's 2026-07-27 spec).

① Define the as-built critical path: the toolkit computes BOTH candidate
  paths per elected milestone — the longest path of the as-built
  programme on its own logic, and the actual recorded sequence (which
  catches unlinked-but-obvious hand-offs and sequence shifts) — the
  analyst picks one, may hand-edit it, and may group it into umbrella
  work packages (critical-path activities only).
② Compare against the baseline's planned dates (late LS/LF by default,
  early ES/EF on election): planned bar below, as-built bar above.
③ Define analysis windows from key dates; delay auto-computed per
  window from the as-built vs planned intervals.
④ The full gantt (planned + as-built + window curtains + per-window
  delay) with the AI report generator beneath.

Nothing else lives on this page.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

import state as sk
from programme import (
    ROLLUP_CAVEATS, build_apab_gantt_html, build_apab_report_prompt,
    build_rollup, build_simple_xlsx, keydate_windows, planned_vs_actual,
)
from programme.narrative import DEFAULT_TEMPLATES
from views._asbuilt_cp import cp_definition_block
from views._shared import ai_narrative_panel, basis_panel, \
    gantt_fullscreen_button, get_parsed_files

APAB_CAVEATS = [
    "The as-built critical path is an analyst election between computed "
    "candidates (the as-built programme's own longest path vs the actual "
    "recorded sequence), possibly hand-edited; the adopted basis is "
    "recorded and disclosed with every figure.",
    "As-built dates are as recorded in the update, not independently "
    "verified; activities beyond the data date carry the programme's "
    "own forecast and are flagged as forecast.",
    "Planned dates come from the flagged contract baseline under the "
    "elected date basis (late LS/LF by default, early ES/EF on "
    "election); activities absent from the baseline carry no planned "
    "date and are disclosed.",
    "Window delay = as-built interval minus planned interval between "
    "consecutive key dates (calendar days). Windows whose key dates "
    "were resequenced against plan are excluded from the cumulative "
    "and flagged.",
]


def _display_rows(rows: list[dict], groups: dict[str, list[str]],
                  path_codes: set[str]):
    """Measurement rows with umbrella members interleaved beneath their
    group header (row_kind tags for the renderer). Returns
    (display_rows, rollup_or_None)."""
    if not groups:
        rows = sorted(rows, key=lambda r: (r["actual_start"]
                                           or datetime.max))
        return rows, None
    roll = build_rollup(rows, groups, path_codes)
    by_key = {u.key: u for u in roll.umbrellas}
    out = []
    for r in roll.measurement_rows():
        if r.get("is_umbrella"):
            out.append({**r, "row_kind": "umbrella"})
            u = by_key.get(r["task_code"])
            for m in (u.members if u else []):
                out.append({
                    "task_code": m.task_code, "name": m.name,
                    "row_kind": "member",
                    "planned_start": m.planned_start,
                    "planned_finish": m.planned_finish,
                    "actual_start": m.actual_start,
                    "actual_finish": m.actual_finish,
                    "start_var_days": m.start_var_days,
                    "finish_var_days": m.finish_var_days,
                    "in_baseline": m.in_baseline})
        else:
            out.append(r)
    return out, roll


def _ms_delay(rows: list[dict], ms: str):
    """Delay to the milestone: its own row's finish variance, falling
    back to the section max-finish comparison."""
    for r in rows:
        if r["task_code"] == ms and r.get("finish_var_days") is not None:
            return r["finish_var_days"]
    pf = [r["planned_finish"] for r in rows if r.get("planned_finish")]
    af = [r["actual_finish"] for r in rows if r.get("actual_finish")]
    if pf and af:
        return round((max(af) - max(pf)).total_seconds() / 86400, 1)
    return None


def apab_tab() -> None:
    files = get_parsed_files()
    inv = st.session_state.get(sk.INVENTORY)
    if not files or inv is None or len(files) < 2:
        st.info("Upload the contract baseline and the as-built update "
                "in **Data Intake** first.")
        return
    pool = dict(files)
    ordered = [(r.file_name, pool[r.file_name]) for r in inv.revisions]
    baseline = (pool[inv.baseline.file_name]
                if inv.baseline else ordered[0][1])
    _, latest = ordered[-1]
    dd = latest.project.data_date if latest.project else None
    by_code = {t.task_code: t for t in latest.tasks if not t.is_loe_or_wbs}

    step = st.radio(
        "Method step",
        ["① As-built critical path", "② As-planned vs as-built",
         "③ Windows", "④ Gantt & report"],
        horizontal=True, key="apab_step")

    # shared state ----------------------------------------------------
    paths: dict = st.session_state.get(sk.APAB_PATHS) or {}
    basis_by: dict = st.session_state.get(sk.APAB_PATH_BASIS) or {}
    groups = st.session_state.get(sk.UMBRELLAS) or {}
    date_basis = st.session_state.get(sk.APAB_DATE_BASIS, "late")

    def _rows_for(ms: str) -> list[dict]:
        codes = {c for c, _ in paths.get(ms, [])}
        return planned_vs_actual(baseline, latest, codes,
                                 date_basis=date_basis)

    def _sections():
        """(ms, display_rows, roll, delay, achieved) per adopted path."""
        out = []
        for ms in st.session_state.get(sk.APAB_MS, []):
            if ms not in paths or ms not in by_code:
                continue        # elections can outlive their corpus
            codes = {c for c, _ in paths[ms]}
            disp, roll = _display_rows(_rows_for(ms), groups, codes)
            t = by_code.get(ms)
            out.append((ms, disp, roll, _ms_delay(disp, ms),
                        bool(t and t.act_finish)))
        return out

    # ============ ① define the as-built critical path ================ #
    if step.startswith("①"):
        st.subheader("① Define the as-built critical path")
        # THE shared step-① breakdown — the very same function the
        # standalone As-Built Critical Path page renders, adopted state
        # included, so the two pages can never disagree about the path.
        paths, basis_by, groups, _ = cp_definition_block(
            ordered, baseline, key_prefix="apab", date_basis=date_basis)

    # ============ ② as-planned vs as-built =========================== #
    elif step.startswith("②"):
        st.subheader("② As-planned vs as-built")
        if not paths:
            st.info("Adopt an as-built critical path in step ① first.")
            return
        basis_pick = st.radio(
            "Planned dates from the baseline",
            ["Late dates (LS/LF) — default",
             "Early dates (ES/EF)"],
            horizontal=True, key="apab_basis_dates",
            index=0 if date_basis == "late" else 1)
        date_basis = "late" if basis_pick.startswith("Late") else "early"
        st.session_state[sk.APAB_DATE_BASIS] = date_basis

        display, mets = [], []
        for ms, disp, roll, delay, achieved in _sections():
            mets.append((ms, delay, achieved))
            display.append({"task_code": "", "row_kind": "section",
                            "name": f"PATH TO {ms} — "
                                    f"{by_code[ms].name[:44]}"})
            display.extend(disp)
        cols = st.columns(max(len(mets), 1))
        for col, (ms, delay, achieved) in zip(cols, mets):
            col.metric(f"Delay to {ms}",
                       f"{delay:+.0f} d" if delay is not None else "—",
                       help=None if achieved else
                       "Milestone not achieved — the as-built side is "
                       "the programme's own forecast.")
        _g2 = build_apab_gantt_html(
            display,
            title=f"As-planned ({date_basis} dates) vs as-built",
            data_date=dd)
        st.iframe(_g2, height=560)
        st.caption(
            "Per row: as-planned dimension line BELOW, as-built bar "
            "ABOVE. ▣ = umbrella work package (measured on its "
            "critical-path members), ↳ = member. Planned dates are the "
            f"baseline's {date_basis.upper()} dates.")
        gantt_fullscreen_button(_g2, "apab_step2_gantt", "apab_fs2")
        with st.expander("Comparison table"):
            st.dataframe(pd.DataFrame([{
                "": {"umbrella": "▣", "member": "↳"}.get(
                    r.get("row_kind"), ""),
                "Activity ID": r["task_code"],
                "Activity": r["name"][:52],
                "Planned start": (f"{r['planned_start']:%Y-%m-%d}"
                                  if r.get("planned_start") else "—"),
                "Planned finish": (f"{r['planned_finish']:%Y-%m-%d}"
                                   if r.get("planned_finish") else "—"),
                "As-built start": (f"{r['actual_start']:%Y-%m-%d}"
                                   if r.get("actual_start") else "—"),
                "As-built finish": (f"{r['actual_finish']:%Y-%m-%d}"
                                    if r.get("actual_finish") else "—"),
                "Var (d)": r.get("finish_var_days"),
            } for r in display if r.get("row_kind") != "section"]),
                width="stretch", hide_index=True, height=340)
            st.caption("Grouping names are edited in step ① — every "
                       "AI-proposed name stays editable there.")

    # ============ ③ windows ========================================== #
    elif step.startswith("③"):
        st.subheader("③ Analysis windows from key dates")
        if not paths:
            st.info("Adopt an as-built critical path in step ① first.")
            return
        st.caption(
            "Tick the key dates — important activities, interim "
            "milestones or umbrella packages on the path. Consecutive "
            "key dates bound one window each; the window delay is "
            "computed automatically from the as-built vs planned "
            "intervals.")
        saved = st.session_state.get(sk.APAB_KEYDATES, {})
        seen, pickable = set(), []
        for ms, disp, roll, delay, achieved in _sections():
            for r in disp:
                if (r.get("row_kind") != "member"
                        and r["task_code"] not in seen):
                    seen.add(r["task_code"])
                    pickable.append(r)
        kd_df = pd.DataFrame([{
            "Key date": r["task_code"] in saved,
            "ID": r["task_code"],
            "Activity": (("▣ " if r.get("row_kind") == "umbrella"
                          else "") + r["name"][:56]),
            "As-built finish": (f"{r['actual_finish']:%Y-%m-%d}"
                                if r.get("actual_finish") else "—"),
            "Why it is key": saved.get(r["task_code"], ""),
        } for r in pickable])
        edited = st.data_editor(
            kd_df, width="stretch", hide_index=True, height=340,
            disabled=["ID", "Activity", "As-built finish"],
            key="apab_kd_ed")
        kd = {}
        for _, r in edited.iterrows():
            if bool(r["Key date"]):
                kd[str(r["ID"])] = str(r["Why it is key"] or "")
        st.session_state[sk.APAB_KEYDATES] = kd

        if len(kd) < 2:
            st.info("Tick at least TWO key dates to bound a window.")
        for ms, disp, roll, delay, achieved in _sections():
            flat = [r for r in disp if r.get("row_kind") != "member"]
            kwin = keydate_windows(flat, [c for c in kd
                                          if c in {r["task_code"]
                                                   for r in flat}])
            if kwin:
                st.markdown(f"**Windows on the path to {ms}:**")
                st.dataframe(pd.DataFrame([{
                    "Window": f"W{i}: {w['from_code']} → {w['to_code']}",
                    "Planned interval (d)": w["planned_interval_days"],
                    "As-built interval (d)": w["actual_interval_days"],
                    "Window delay (d)": w["window_delay_days"],
                    "Resequenced": ("⚠️ excluded from cumulative"
                                    if w.get("resequenced") else ""),
                    "Cumulative (d)": w["cumulative_delay_days"],
                } for i, w in enumerate(kwin, start=1)]),
                    width="stretch", hide_index=True)

    # ============ ④ gantt & report =================================== #
    else:
        st.subheader("④ Gantt & report")
        if not paths:
            st.info("Adopt an as-built critical path in step ① first.")
            return
        kd = st.session_state.get(sk.APAB_KEYDATES, {})
        display, mets, windows_by_ms, all_windows = [], [], {}, []
        sections_data = []
        for ms, disp, roll, delay, achieved in _sections():
            mets.append((ms, delay, achieved))
            display.append({"task_code": "", "row_kind": "section",
                            "name": f"PATH TO {ms} — "
                                    f"{by_code[ms].name[:44]}"})
            display.extend(disp)
            flat = [r for r in disp if r.get("row_kind") != "member"]
            kwin = keydate_windows(flat, [c for c in kd
                                          if c in {r["task_code"]
                                                   for r in flat}])
            windows_by_ms[ms] = kwin
            fin = {r["task_code"]: r.get("actual_finish") for r in flat}
            for i, w in enumerate(kwin, start=1):
                all_windows.append({
                    "label": f"W{i}",
                    "start": fin.get(w["from_code"]),
                    "end": fin.get(w["to_code"]),
                    "delay_days": w["window_delay_days"]})
            sections_data.append({
                "ms": ms, "ms_name": by_code[ms].name,
                "basis": basis_by.get(ms, ""),
                "delay_days": delay, "achieved": achieved,
                "rows": disp})
        cols = st.columns(max(len(mets), 1))
        for col, (ms, delay, achieved) in zip(cols, mets):
            col.metric(f"Delay to {ms}",
                       f"{delay:+.0f} d" if delay is not None else "—",
                       help=None if achieved else
                       "Milestone not achieved — measured on the "
                       "programme's own forecast.")
        _first = next((d for _, d, _a in mets if d is not None), None)
        _g4 = build_apab_gantt_html(
            display, keydates=kd, overall_delay_days=_first,
            title=f"As-planned ({date_basis} dates) vs as-built",
            windows=all_windows, data_date=dd)
        st.iframe(_g4, height=620)
        st.caption(
            "Shaded curtains = the analysis windows, labelled with each "
            "window's delay. Dashed red line = data date. Key-date rows "
            "carry the planned◇ / actual◆ markers and the measured "
            "gap.")
        gantt_fullscreen_button(_g4, "apab_final_gantt", "apab_fs4")

        # the FINAL gantt as a print figure — embedded in the workbook
        # and the Word narrative (a figure failure never blocks either)
        def _final_gantt_png():
            from programme.report_charts import apab_gantt_chart, \
                chart_png
            ch = apab_gantt_chart(display, windows=all_windows,
                                  data_date=dd)
            return chart_png(ch) if ch is not None else None
        try:
            _png4 = _final_gantt_png()
        except Exception:
            _png4 = None

        basis_panel("As-Planned vs As-Built", latest, [
            "As-built CP basis per milestone: "
            + ("; ".join(f"{m}: {b}" for m, b in basis_by.items())
               or "not adopted"),
            f"Planned dates: baseline {date_basis.upper()} dates",
            f"{len(groups)} umbrella work package(s); measured on "
            "critical-path members only" if groups else
            "No umbrella grouping adopted",
            f"{len(kd)} key date(s); window delay = as-built minus "
            "planned interval",
        ])
        with st.expander("Method caveats (always apply)"):
            for c in APAB_CAVEATS + (list(ROLLUP_CAVEATS)
                                     if groups else []):
                st.write("•", c)

        narrative = ai_narrative_panel(
            "nar_apab",
            lambda tmpl, sd=sections_data, db=date_basis,
            wbm=windows_by_ms: build_apab_report_prompt(
                sd, db, wbm,
                APAB_CAVEATS + (list(ROLLUP_CAVEATS) if groups else []),
                tmpl),
            "apab",
            DEFAULT_TEMPLATES["apab"],
            chart_png_builder=lambda p=_png4: (
                [("Final gantt — as-planned vs as-built", p)]
                if p else None),
        )
        st.download_button(
            "⬇️ Download as-planned vs as-built workbook (Excel)",
            data=build_simple_xlsx(
                "As-Planned vs As-Built",
                images=({"Final Gantt": _png4} if _png4 else None),
                sheets={"Comparison": [
                    {k: v for k, v in r.items() if k != "row_kind"}
                    | {"kind": r.get("row_kind", "")}
                    for r in display],
                 "Windows": [w for ws in windows_by_ms.values()
                             for w in ws] or [{}],
                 "Key dates": [{"ID": c, "Why key": why}
                               for c, why in kd.items()] or [{}]},
                notes=[f"As-built CP basis: "
                       + ("; ".join(f"{m}: {b}"
                                    for m, b in basis_by.items()))]
                + APAB_CAVEATS),
            file_name="as_planned_vs_as_built.xlsx",
            mime="application/vnd.openxmlformats-officedocument."
                 "spreadsheetml.sheet",
            key="apab_dl")
