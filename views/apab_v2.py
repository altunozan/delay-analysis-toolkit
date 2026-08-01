"""As-Planned vs As-Built v2 — Retrospective Longest Path.

The same four steps as the As-Planned vs As-Built method, with one
extension in step ①: alongside the two computed candidates (recorded
logic and actual sequence), the AI proposes dependencies that were
never linked in the programme — blockwork before first-fix electrical
— from a deterministically screened list, over multiple independent
runs, and the longest path is re-derived over the combined network.

① Determine the retrospective longest path — three candidates per
  elected milestone, up to three inferred-logic options; the analyst
  adopts one. Confidence is a word (strong / medium / poor), never a
  number, and every inferred link is disclosed in its own section.
② Planned vs as-built bars on the adopted path.
③ Analysis windows from key dates.
④ Full gantt + AI narrative + workbook.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import state as sk
from dcma.narrative import NarrativeError, stream_narrative
from programme import (
    build_apab_gantt_html, build_apab_report_prompt, build_simple_xlsx,
    extract_actual_trace, extract_asbuilt_longest_path, keydate_windows,
    planned_vs_actual,
)
from programme.narrative import DEFAULT_TEMPLATES
from programme.rlpa import (
    RLPA_CAVEATS, aggregate_votes, build_inference_prompt, derive_paths,
    parse_inference, path_idle_gaps, screen_missing_links,
)
from views._shared import (
    ai_credentials_panel, ai_narrative_panel, basis_panel,
    gantt_fullscreen_button, get_parsed_files, resolve_ai_credentials,
)

_PATHS = "apab2_paths"          # ms -> list[(code, name)]
_BASIS = "apab2_basis"          # ms -> basis label
_MS = "apab2_ms"                # elected milestone code
_RLPA = "apab2_rlpa"            # RLPAResult of the last inference run
_KD = "apab2_keydates"          # code -> why
_DATE_BASIS = "apab2_date_basis"

_RUNS = 3


def _trace_table(trace, inferred=frozenset()):
    rows = []
    for a in trace.activities:
        rows.append({
            "Activity ID": a.task_code, "Activity": a.name[:52],
            "As-built start": (f"{a.act_start:%Y-%m-%d}"
                               if a.act_start else "—"),
            "As-built finish": (f"{a.act_finish:%Y-%m-%d}"
                                if a.act_finish else "—"),
            "Basis": a.basis,
        })
    link_in = {lk.succ_code: lk for lk in trace.links}
    for r in rows:
        lk = link_in.get(r["Activity ID"])
        r["Hand-off"] = ("INFERRED" if lk and (
            lk.kind == "inferred"
            or (lk.pred_code, lk.succ_code) in inferred)
            else "recorded logic" if lk and lk.had_logic
            else "sequence" if lk else "")
    return pd.DataFrame(rows)


def _ms_delay(rows):
    pf = [r["planned_finish"] for r in rows if r.get("planned_finish")]
    af = [r["actual_finish"] for r in rows if r.get("actual_finish")]
    if pf and af:
        return round((max(af) - max(pf)).total_seconds() / 86400, 1)
    return None


def apab_v2_tab() -> None:
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
        ["① Retrospective longest path", "② As-planned vs as-built",
         "③ Windows", "④ Gantt & report"],
        horizontal=True, key="apab2_step")

    paths: dict = st.session_state.get(_PATHS) or {}
    basis_by: dict = st.session_state.get(_BASIS) or {}
    date_basis = st.session_state.get(_DATE_BASIS, "late")

    def _rows_for(ms):
        codes = {c for c, _ in paths.get(ms, [])}
        return sorted(
            planned_vs_actual(baseline, latest, codes,
                              date_basis=date_basis),
            key=lambda r: (r["actual_start"] is None,
                           r["actual_start"]))

    # ========= ① determine the retrospective longest path =========== #
    if step.startswith("①"):
        st.subheader("① Determine the retrospective longest path")
        milestones = [t.task_code for t in latest.tasks
                      if t.is_milestone and not t.is_loe_or_wbs]
        if not milestones:
            st.warning("No milestones in the latest programme.")
            return
        default = st.session_state.get(_MS)
        ms = st.selectbox(
            "Trace to (elected completion milestone)", milestones,
            index=(milestones.index(default) if default in milestones
                   else len(milestones) - 1),
            format_func=lambda c: f"{c} — {by_code[c].name[:50]}",
            key="apab2_ms_pick")
        st.session_state[_MS] = ms

        cand_logic = extract_asbuilt_longest_path(
            latest, end_task_code=ms)
        cand_seq = extract_actual_trace(ordered, end_task_code=ms,
                                        max_gap_days=60)

        st.markdown("**Candidate A — recorded logic** (the as-built "
                    "longest path over the programme's own links)")
        st.dataframe(_trace_table(cand_logic), width="stretch",
                     hide_index=True, height=230)
        st.markdown("**Candidate B — actual sequence** (recorded dates; "
                    "un-evidenced hops disclosed)")
        st.dataframe(_trace_table(cand_seq), width="stretch",
                     hide_index=True, height=230)

        # ---- candidate C: analyst-logic (AI-inferred) path ---------- #
        st.markdown("**Candidate C — analyst logic** (dependencies the "
                    "programme never linked, AI-proposed from a "
                    "deterministic screen, majority-voted over "
                    f"{_RUNS} independent runs)")
        pairs = screen_missing_links(latest)
        st.caption(f"{len(pairs)} unlinked pair(s) survive the "
                   "deterministic screen (finish-before-start, shared "
                   "work-area context, physically possible order). The "
                   "AI can only select from these.")
        ai_credentials_panel("apab2")
        provider, model, api_key = resolve_ai_credentials()
        if st.button(f"Run inference ({_RUNS} passes)", type="primary",
                     disabled=not (api_key and pairs), key="apab2_go"):
            prompt = build_inference_prompt(pairs)
            runs, rejected = [], []
            progress = st.progress(0.0, "Running inference…")
            for i in range(_RUNS):
                try:
                    text = "".join(stream_narrative(
                        provider, api_key, prompt, model or None))
                except NarrativeError as exc:
                    st.error(f"AI pass {i + 1} failed: {exc}")
                    break
                accepted, bad = parse_inference(text, pairs)
                runs.append(accepted)
                rejected.extend(bad)
                progress.progress((i + 1) / _RUNS,
                                  f"Pass {i + 1} of {_RUNS} done")
            progress.empty()
            if runs:
                links = aggregate_votes(runs)
                res = derive_paths(latest, links, end_task_code=ms)
                res.candidates = pairs
                res.rejected = rejected
                st.session_state[_RLPA] = (ms, res)

        stored = st.session_state.get(_RLPA)
        res = stored[1] if stored and stored[0] == ms else None
        option_traces = {}
        if res:
            for label, note, trace in res.options:
                option_traces[label] = (note, trace)
            inferred_set = {(l.pred_code, l.succ_code)
                            for l in res.links}
            for label, (note, trace) in option_traces.items():
                on_path = sum(1 for lk in trace.links
                              if lk.kind == "inferred")
                st.markdown(f"**{label}** — {note}; {on_path} inferred "
                            "hand-off(s) on the path")
                st.dataframe(_trace_table(trace, inferred_set),
                             width="stretch", hide_index=True,
                             height=230)

        # ---- adoption ------------------------------------------------
        choices = {"A — recorded logic": ("as-built longest path "
                                          "(recorded logic)",
                                          cand_logic),
                   "B — actual sequence": ("actual recorded sequence",
                                           cand_seq)}
        for label, (note, trace) in option_traces.items():
            choices[f"C — {label}"] = (
                f"retrospective longest path with inferred links "
                f"({note})", trace)
        pick = st.radio("Adopt as the as-built critical path",
                        list(choices), key="apab2_adopt_pick")
        if st.button("Adopt for this milestone", key="apab2_adopt"):
            basis, trace = choices[pick]
            paths[ms] = [(a.task_code, a.name) for a in trace.activities]
            basis_by[ms] = basis
            st.session_state[_PATHS] = paths
            st.session_state[_BASIS] = basis_by
            st.success(f"Adopted for {ms}: {basis}. Continue to step ②.")

        # ---- qualification (separate section, words not numbers) ---- #
        if res:
            st.divider()
            st.subheader("Qualification — inferred links")
            if res.links:
                st.dataframe(pd.DataFrame([{
                    "Confidence": l.confidence.upper(),
                    "Votes": f"{l.votes} of {l.runs} runs",
                    "Predecessor": f"{l.pred_code} — "
                    + by_code[l.pred_code].name[:38]
                    if l.pred_code in by_code else l.pred_code,
                    "Successor": f"{l.succ_code} — "
                    + by_code[l.succ_code].name[:38]
                    if l.succ_code in by_code else l.succ_code,
                    "AI reasoning": " / ".join(l.reasons)[:160],
                } for l in res.links]), width="stretch",
                    hide_index=True)
            else:
                st.info("No missing dependencies proposed.")
            if res.rejected:
                with st.expander(f"{len(res.rejected)} AI proposal(s) "
                                 "discarded by verbatim verification"):
                    for r in res.rejected:
                        st.write("•", r)
            adopted_trace = res.options[0][2] if res.options else None
            if adopted_trace:
                gaps = path_idle_gaps(adopted_trace, latest)
                if gaps:
                    st.markdown("**Largest unexplained hand-off gaps "
                                "on the path** (the workfront stood "
                                "idle — often the finding itself):")
                    st.dataframe(pd.DataFrame([{
                        "After": g["after"], "Before": g["before"],
                        "From": f"{g['from']:%Y-%m-%d}",
                        "To": f"{g['to']:%Y-%m-%d}",
                        "Working days": g["working_days"],
                    } for g in gaps]), width="stretch",
                        hide_index=True)
            with st.expander("Standing caveats (always apply)"):
                for c in RLPA_CAVEATS:
                    st.write("•", c)

    # ========= ② as-planned vs as-built ============================= #
    elif step.startswith("②"):
        st.subheader("② As-planned vs as-built")
        if not paths:
            st.info("Adopt a retrospective longest path in step ① "
                    "first.")
            return
        basis_pick = st.radio(
            "Planned dates from the baseline",
            ["Late dates (LS/LF) — default", "Early dates (ES/EF)"],
            horizontal=True, key="apab2_basis_dates",
            index=0 if date_basis == "late" else 1)
        date_basis = "late" if basis_pick.startswith("Late") else "early"
        st.session_state[_DATE_BASIS] = date_basis
        display, mets = [], []
        for ms in paths:
            rows = _rows_for(ms)
            mets.append((ms, _ms_delay(rows)))
            display.append({"task_code": "", "row_kind": "section",
                            "name": f"PATH TO {ms} — "
                            + (by_code[ms].name[:44]
                               if ms in by_code else "")})
            display.extend(rows)
        cols = st.columns(max(len(mets), 1))
        for col, (ms, delay) in zip(cols, mets):
            col.metric(f"Delay to {ms}",
                       f"{delay:+.0f} d" if delay is not None else "—")
        _g2 = build_apab_gantt_html(
            display,
            title=f"As-planned ({date_basis} dates) vs as-built "
                  "(retrospective longest path)",
            data_date=dd)
        st.iframe(_g2, height=560)
        st.caption("Per row: as-planned dimension line BELOW, as-built "
                   "bar ABOVE. Planned dates are the baseline's "
                   f"{date_basis.upper()} dates. The path basis "
                   "(including any inferred links) is recorded in "
                   "step ① and the report.")
        gantt_fullscreen_button(_g2, "apab2_step2_gantt", "apab2_fs2")

    # ========= ③ windows ============================================ #
    elif step.startswith("③"):
        st.subheader("③ Analysis windows from key dates")
        if not paths:
            st.info("Adopt a retrospective longest path in step ① "
                    "first.")
            return
        saved = st.session_state.get(_KD, {})
        pickable, seen = [], set()
        for ms in paths:
            for r in _rows_for(ms):
                if r["task_code"] not in seen:
                    seen.add(r["task_code"])
                    pickable.append(r)
        edited = st.data_editor(pd.DataFrame([{
            "Key date": r["task_code"] in saved,
            "ID": r["task_code"],
            "Activity": r["name"][:56],
            "As-built finish": (f"{r['actual_finish']:%Y-%m-%d}"
                                if r.get("actual_finish") else "—"),
            "Why it is key": saved.get(r["task_code"], ""),
        } for r in pickable]), width="stretch", hide_index=True,
            height=340, disabled=["ID", "Activity", "As-built finish"],
            key="apab2_kd_ed")
        kd = {str(r["ID"]): str(r["Why it is key"] or "")
              for _, r in edited.iterrows() if bool(r["Key date"])}
        st.session_state[_KD] = kd
        if not kd:
            st.info("Tick at least ONE key date — the first window "
                    "runs from the PROJECT START to it.")
        for ms in paths:
            rows = _rows_for(ms)
            kwin = keydate_windows(rows, [c for c in kd
                                          if c in {r["task_code"]
                                                   for r in rows}])
            if kwin:
                st.markdown(f"**Windows on the path to {ms}:**")
                st.dataframe(pd.DataFrame([{
                    "Window": f"W{i}: {w['from_code']} → {w['to_code']}",
                    "Planned finish": f"{w['planned_finish']:%Y-%m-%d}",
                    "Actual finish": f"{w['actual_finish']:%Y-%m-%d}",
                    "Delay at key date (d)": w["cumulative_delay_days"],
                    "Accrued in window (d)": w["window_delay_days"],
                    "Resequenced": ("⚠️ order differs from plan"
                                    if w.get("resequenced") else ""),
                } for i, w in enumerate(kwin, start=1)]),
                    width="stretch", hide_index=True)

    # ========= ④ gantt & report ===================================== #
    else:
        st.subheader("④ Gantt & report")
        if not paths:
            st.info("Adopt a retrospective longest path in step ① "
                    "first.")
            return
        kd = st.session_state.get(_KD, {})
        display, mets, windows_by_ms, all_windows = [], [], {}, []
        sections_data = []
        for ms in paths:
            rows = _rows_for(ms)
            delay = _ms_delay(rows)
            mets.append((ms, delay))
            display.append({"task_code": "", "row_kind": "section",
                            "name": f"PATH TO {ms} — "
                            + (by_code[ms].name[:44]
                               if ms in by_code else "")})
            display.extend(rows)
            kwin = keydate_windows(rows, [c for c in kd
                                          if c in {r["task_code"]
                                                   for r in rows}])
            windows_by_ms[ms] = kwin
            for i, w in enumerate(kwin, start=1):
                all_windows.append({
                    "label": f"W{i}", "start": w.get("window_start"),
                    "end": w.get("window_end"),
                    "delay_days": w["window_delay_days"]})
            sections_data.append({
                "ms": ms,
                "ms_name": by_code[ms].name if ms in by_code else ms,
                "basis": basis_by.get(ms, ""),
                "delay_days": delay,
                "achieved": bool(ms in by_code
                                 and by_code[ms].act_finish),
                "rows": rows})
        cols = st.columns(max(len(mets), 1))
        for col, (ms, delay) in zip(cols, mets):
            col.metric(f"Delay to {ms}",
                       f"{delay:+.0f} d" if delay is not None else "—")
        _first = next((d for _, d in mets if d is not None), None)
        _g4 = build_apab_gantt_html(
            display, keydates=kd, overall_delay_days=_first,
            title=f"As-planned ({date_basis} dates) vs as-built "
                  "(retrospective longest path)",
            windows=all_windows, data_date=dd)
        st.iframe(_g4, height=620)
        gantt_fullscreen_button(_g4, "apab2_final_gantt", "apab2_fs4")

        stored = st.session_state.get(_RLPA)
        res = stored[1] if stored else None
        inferred_rows = ([{
            "Confidence": l.confidence.upper(),
            "Votes": f"{l.votes} of {l.runs}",
            "Predecessor": l.pred_code, "Successor": l.succ_code,
            "AI reasoning": " / ".join(l.reasons)[:160],
        } for l in res.links] if res else [])

        basis_panel("As-Planned vs As-Built v2 (RLPA)", latest, [
            "Adopted path basis per milestone: "
            + ("; ".join(f"{m}: {b}" for m, b in basis_by.items())
               or "not adopted"),
            f"Planned dates: baseline {date_basis.upper()} dates",
            f"{len(inferred_rows)} inferred link(s) proposed by AI "
            "over the deterministic screen; confidence stated in "
            "words from cross-run agreement" if inferred_rows else
            "No inferred links in play — recorded programme data only",
        ])
        with st.expander("Method caveats (always apply)"):
            for c in RLPA_CAVEATS:
                st.write("•", c)

        _caveats = RLPA_CAVEATS + [
            "Inferred hand-offs on the adopted path (if any) are "
            "listed with the AI's reasoning and a word confidence; "
            "they are analyst-proposed logic for review."]
        ai_narrative_panel(
            "nar_apab2",
            lambda tmpl, sd=sections_data, db=date_basis,
            wbm=windows_by_ms, ir=inferred_rows:
            build_apab_report_prompt(sd, db, wbm, _caveats, tmpl)
            + (("\n\nINFERRED LINKS (analyst-proposed, confidence in "
                "words):\n" + "\n".join(
                    f"- {r['Predecessor']} → {r['Successor']} "
                    f"[{r['Confidence']}, {r['Votes']} runs]: "
                    f"{r['AI reasoning']}" for r in ir))
               if ir else ""),
            "apab_v2",
            DEFAULT_TEMPLATES["apab"],
        )
        st.download_button(
            "⬇️ Download workbook (Excel)",
            data=build_simple_xlsx(
                "As-Planned vs As-Built v2 (RLPA)",
                sheets={"Comparison": [
                    {k: v for k, v in r.items() if k != "row_kind"}
                    for r in display],
                    "Windows": [w for ws in windows_by_ms.values()
                                for w in ws] or [{}],
                    "Inferred links": inferred_rows or [{}],
                    "Key dates": [{"ID": c, "Why key": why}
                                  for c, why in kd.items()] or [{}]},
                notes=["Adopted path basis: "
                       + ("; ".join(f"{m}: {b}"
                                    for m, b in basis_by.items())
                          or "not adopted")] + list(RLPA_CAVEATS)),
            file_name="apvab_v2_rlpa.xlsx",
            mime="application/vnd.openxmlformats-officedocument."
                 "spreadsheetml.sheet",
            key="apab2_dl")
