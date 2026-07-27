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
    build_gantt_html, build_rollup, build_simple_xlsx,
    extract_actual_trace, extract_longest_path, group_tree,
    keydate_windows, planned_vs_actual,
)
from programme.gantt_html import ASBUILT_CATEGORIES
from programme.narrative import DEFAULT_TEMPLATES
from views._shared import _fkey, ai_narrative_panel, basis_panel, \
    get_parsed_files
from views._umbrella import umbrella_editor

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


# --------------------------------------------------------------------- #
# cached candidate engines
# --------------------------------------------------------------------- #
@st.cache_data(show_spinner=False, max_entries=16)
def cached_longest(key: str, ms: str, _data, label: str):
    cp = extract_longest_path(_data, label, end_task_code=ms)
    return ([(a.task_code, a.name) for a in cp.critical],
            [(lk.pred_code, lk.succ_code) for lk in cp.links])


@st.cache_data(show_spinner=False, max_entries=16)
def cached_sequence(key: tuple, ms: str, _ordered):
    tr = extract_actual_trace(_ordered, end_task_code=ms)
    return ([(a.task_code, a.name) for a in tr.activities],
            [(lk.pred_code, lk.succ_code) for lk in tr.links],
            [f"{lk.pred_code}→{lk.succ_code}" for lk in tr.links
             if not lk.had_logic])


def _basis_of(t) -> str:
    if t.act_finish is not None:
        return "as-built"
    if t.act_start is not None:
        return "in-progress"
    return "forecast"


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
    latest_label, latest = ordered[-1]
    okey = tuple(_fkey(n) for n, _ in ordered)
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
            if ms not in paths:
                continue
            codes = {c for c, _ in paths[ms]}
            disp, roll = _display_rows(_rows_for(ms), groups, codes)
            t = by_code.get(ms)
            out.append((ms, disp, roll, _ms_delay(disp, ms),
                        bool(t and t.act_finish)))
        return out

    # ============ ① define the as-built critical path ================ #
    if step.startswith("①"):
        st.subheader("① Define the as-built critical path")
        st.caption(
            "The as-built CP is in theory the as-built programme's "
            "longest path — but out-of-sequence works or missing links "
            "can put the real driver elsewhere. The toolkit computes "
            "BOTH readings; where they diverge, that is exactly where "
            "the works departed from the programmed sequence. The "
            "decision is yours.")

        ms_opts = [t for t in latest.tasks
                   if t.is_milestone and not t.is_loe_or_wbs]
        ms_opts.sort(key=lambda t: (t.act_finish or t.early_finish
                                    or datetime.min), reverse=True)
        cms = st.session_state.get(sk.CONTRACT_MS)
        if cms in {t.task_code for t in ms_opts}:
            ms_opts.sort(key=lambda t: t.task_code != cms)
        labels = {t.task_code:
                  f"{t.task_code} — {t.name[:48]}"
                  + (f"  (achieved {t.act_finish:%d %b %Y})"
                     if t.act_finish else "  ⚠ not achieved")
                  for t in ms_opts}
        chosen_ms = st.multiselect(
            "Milestone(s) to measure to — each gets its own path, "
            "grouped separately in the gantt",
            options=list(labels), default=st.session_state.get(
                sk.APAB_MS, [cms] if cms in labels else
                list(labels)[:1]),
            format_func=lambda c: labels[c], key="apab_ms_pick")
        st.session_state[sk.APAB_MS] = chosen_ms

        for ms in chosen_ms:
            st.markdown(f"##### Path to **{ms}** — "
                        f"{by_code[ms].name[:60]}")
            lp_path, lp_links = cached_longest(
                _fkey(latest_label), ms, latest, latest_label)
            sq_path, sq_links, sq_seq_only = cached_sequence(
                okey, ms, ordered)
            lp_codes = {c for c, _ in lp_path}
            sq_codes = {c for c, _ in sq_path}
            only_lp = lp_codes - sq_codes
            only_sq = sq_codes - lp_codes
            c1, c2, c3 = st.columns(3)
            c1.metric("Longest path (programme logic)", len(lp_path))
            c2.metric("Actual sequence (recorded dates)", len(sq_path))
            c3.metric("Divergence", f"{len(only_lp | only_sq)} activities",
                      help="Activities on one reading but not the other "
                           "— where the works departed from the "
                           "programmed sequence.")
            if only_lp or only_sq:
                with st.expander(f"Where the two readings diverge "
                                 f"({ms})"):
                    st.caption(
                        "On the LOGIC path but not the recorded "
                        "sequence — the programme says they drove, the "
                        "dates say otherwise (the '2nd floor' case):")
                    st.write(", ".join(sorted(only_lp)[:40]) or "—")
                    st.caption(
                        "In the RECORDED sequence but not the logic "
                        "path — hand-offs the works actually followed "
                        "though the programme never linked them:")
                    st.write(", ".join(sorted(only_sq)[:40]) or "—")
                    if sq_seq_only:
                        st.caption("Sequence-only hand-offs (no "
                                   "programmed relationship in any "
                                   "revision): "
                                   + "; ".join(sq_seq_only[:10]))
            pick = st.radio(
                f"As-built CP basis for {ms}",
                ["Longest path of the as-built programme",
                 "Actual sequence through recorded dates"],
                key=f"apab_cand_{ms}", horizontal=True)
            cand = lp_path if pick.startswith("Longest") else sq_path
            cand_key = "lp" if pick.startswith("Longest") else "sq"
            all_labels = {c: f"{c} — {t.name[:52]}"
                          for c, t in by_code.items()}
            edited = st.multiselect(
                f"Hand-edit the path for {ms} (add or remove "
                "activities; edits are disclosed)",
                options=list(all_labels),
                default=[c for c, _ in cand],
                format_func=lambda c: all_labels[c],
                key=f"apab_edit_{ms}_{cand_key}")
            if st.button(f"Adopt this path for {ms} "
                         f"({len(edited)} activities)",
                         type="primary", key=f"apab_adopt_{ms}"):
                keep = [(c, n) for c, n in cand if c in set(edited)]
                extra = [(c, by_code[c].name) for c in edited
                         if c not in {x for x, _ in cand}
                         and c in by_code]
                extra.sort(key=lambda p: (
                    by_code[p[0]].act_start
                    or by_code[p[0]].early_start or datetime.max))
                paths[ms] = keep + extra
                n_edit = len(set(edited) ^ {c for c, _ in cand})
                basis_by[ms] = (pick + (f" + {n_edit} analyst edit(s)"
                                        if n_edit else ""))
                st.session_state[sk.APAB_PATHS] = paths
                st.session_state[sk.APAB_PATH_BASIS] = basis_by
                st.success(f"Adopted for {ms}: {len(paths[ms])} "
                           f"activities ({basis_by[ms]}).")
            st.divider()

        # ---- umbrella grouping: CP activities ONLY ------------------
        union = {c for ms in chosen_ms for c, _ in paths.get(ms, [])}
        if union:
            st.markdown("##### Group the path into umbrella activities "
                        "(optional)")
            cp_rows = planned_vs_actual(baseline, latest, union,
                                        date_basis=date_basis)
            groups = umbrella_editor(cp_rows, union,
                                     key_prefix="apab_umb")

            # ---- the adopted path(s) as a linked gantt --------------
            st.markdown("##### The as-built critical path")
            roots = []
            for ms in chosen_ms:
                if ms not in paths:
                    continue
                lp_path, lp_links = cached_longest(
                    _fkey(latest_label), ms, latest, latest_label)
                _, sq_links, _ = cached_sequence(okey, ms, ordered)
                links_src = (lp_links if str(st.session_state.get(
                    f"apab_cand_{ms}", "")).startswith("Longest")
                    else sq_links)
                codes = {c for c, _ in paths[ms]}
                succs: dict[str, list[str]] = {}
                for p_, s_ in links_src:
                    if p_ in codes and s_ in codes:
                        succs.setdefault(p_, []).append(s_)

                def act(c, n):
                    t = by_code[c]
                    return {"id": c, "name": n,
                            "start": t.act_start or t.early_start,
                            "finish": t.act_finish or t.early_finish,
                            "milestone": t.is_milestone,
                            "status": _basis_of(t),
                            "lid": f"{ms}:{c}",
                            "links": [f"{ms}:{s}" for s in
                                      succs.get(c, [])]}

                owner = {c: nm for nm, cs in groups.items() for c in cs}
                buckets, order = {}, []
                for c, n in paths[ms]:
                    k = owner.get(c) or c
                    if k not in buckets:
                        buckets[k] = []
                        order.append(k)
                    buckets[k].append((c, n))
                children = []
                for k in order:
                    mem = buckets[k]
                    if k in groups:
                        children.append(
                            {"name": f"▣ {k}",
                             "activities": [act(c, n) for c, n in mem]})
                    else:
                        children.append(
                            {"name": mem[0][1][:44],
                             "activities": [act(c, n) for c, n in mem]})
                roots.append({"name": f"Path to {ms} — "
                              f"{by_code[ms].name[:40]}",
                              "children": children})
            if roots:
                st.iframe(build_gantt_html(
                    group_tree(roots),
                    data_date=f"{dd:%Y-%m-%d}" if dd else None,
                    title="As-built critical path",
                    categories=ASBUILT_CATEGORIES), height=560)
                st.caption(
                    "Dashed line = data date; bars right of it are the "
                    "programme's forecast. Arrows = the path's "
                    "hand-offs. ▣ groups are umbrella work packages — "
                    "members remain visible beneath their header.")

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
        st.iframe(build_apab_gantt_html(
            display,
            title=f"As-planned ({date_basis} dates) vs as-built",
            data_date=dd), height=560)
        st.caption(
            "Per row: as-planned dimension line BELOW, as-built bar "
            "ABOVE. ▣ = umbrella work package (measured on its "
            "critical-path members), ↳ = member. Planned dates are the "
            f"baseline's {date_basis.upper()} dates.")
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
        st.iframe(build_apab_gantt_html(
            display, keydates=kd, overall_delay_days=_first,
            title=f"As-planned ({date_basis} dates) vs as-built",
            windows=all_windows, data_date=dd), height=620)
        st.caption(
            "Shaded curtains = the analysis windows, labelled with each "
            "window's delay. Dashed red line = data date. Key-date rows "
            "carry the planned◇ / actual◆ markers and the measured "
            "gap.")

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
        )
        st.download_button(
            "⬇️ Download as-planned vs as-built workbook (Excel)",
            data=build_simple_xlsx(
                "As-Planned vs As-Built",
                {"Comparison": [
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
