"""Collapsed As-Built."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import state as sk
from dcma.narrative import NarrativeError, stream_narrative
from programme import (
    GROUPING_SYSTEM_PROMPT, build_grouping_prompt, build_simple_xlsx,
    collapse_asbuilt, parse_grouping,
)
from views._shared import (
    _fkey, ai_provider_block, basis_panel, cached_oos_flags, log_ai_use,
    get_parsed_files,
)
from views._submodules import analysis_submodules


def collapsed_asbuilt_tab() -> None:
    st.caption(
        "Collapsed as-built (but-for): only the as-built programme is "
        "needed. Identify the event activities, remove them from the "
        "sequence, and see where the programme collapses to — the "
        "difference is the delay attributable to the extracted events."
    )
    files = get_parsed_files()
    inv = st.session_state.get(sk.INVENTORY)
    if not files or inv is None:
        st.info("Upload the as-built programme in **Data Intake** first.")
        return
    names = [r.file_name for r in inv.revisions]
    chosen = st.selectbox("As-built programme", names,
                          index=len(names) - 1, key="cab_file")
    data = dict(files)[chosen]

    step = st.radio("Method step",
                    ["① Identify candidate events",
                     "② Confirm extraction set", "③ Collapse & measure"],
                    horizontal=True, key="cab_step")

    if step.startswith("①"):
        st.subheader("① Identify candidate event activities")
        st.caption("Group by name / WBS / activity codes — AI proposes, "
                   "the analyst decides. These usually sit on the "
                   "longest path.")
        c1, c2 = st.columns([1, 1])
        with c1:
            st.markdown("**AI-assisted grouping**")
            # The same provider/model/key block the narrative panels
            # render — one code path for every AI feature.
            provider, model, ai_key = ai_provider_block("cab_ai")
            if st.button("Propose event groups from activity names",
                         disabled=not ai_key, key="cab_ai_go"):
                try:
                    text = "".join(stream_narrative(
                        provider, ai_key, build_grouping_prompt(data),
                        model or None,
                        system=GROUPING_SYSTEM_PROMPT))
                    groups, dropped = parse_grouping(text, data)
                    st.session_state[sk.CAB_GROUPS] = groups
                    log_ai_use("CAB grouping", provider, model)
                    if dropped:
                        st.warning(f"{dropped} proposed code(s) were "
                                   "not verbatim in the file and were "
                                   "dropped.")
                except NarrativeError as exc:
                    st.error(exc.message)
        with c2:
            st.markdown("**Deterministic fallback** — keyword filter")
            kw = st.text_input("Name contains", key="cab_kw",
                               placeholder="e.g. Review & Approval")
            if kw.strip():
                hits = [t.task_code for t in data.tasks
                        if not t.is_loe_or_wbs and t.act_start
                        and kw.lower() in t.name.lower()]
                st.write(f"**{len(hits)}** started activities match.")
                if st.button("Add matches as a group", key="cab_kw_add",
                             disabled=not hits):
                    gs = st.session_state.setdefault(sk.CAB_GROUPS, [])
                    gs.append({"label": f"Keyword: {kw}",
                               "codes": hits,
                               "rationale": "deterministic keyword "
                                            "match"})
        # Reuse a work-package breakdown already defined for APvAB —
        # one grouping, defined once. Extraction candidates and
        # presentation umbrellas are different questions, so this is an
        # explicit import, never automatic.
        _umb = st.session_state.get(sk.UMBRELLAS) or {}
        if _umb:
            st.caption(f"{len(_umb)} umbrella activity(ies) are defined "
                       "in As-Planned vs As-Built.")
            if st.button("Import them as candidate groups",
                         key="cab_umb_import"):
                gs = st.session_state.setdefault(sk.CAB_GROUPS, [])
                have = {g["label"] for g in gs}
                for name, codes in _umb.items():
                    if name not in have:
                        gs.append({"label": name, "codes": list(codes),
                                   "rationale": "imported from the "
                                                "as-built work-package "
                                                "breakdown"})
                st.rerun()
        for g in st.session_state.get(sk.CAB_GROUPS, []):
            with st.expander(f"{g['label']} — {len(g['codes'])} "
                             "activities"):
                st.write(g.get("rationale", ""))
                st.code(", ".join(g["codes"][:40])
                        + (" …" if len(g["codes"]) > 40 else ""))

    elif step.startswith("②"):
        st.subheader("② Confirm the extraction set (analyst decision)")
        groups = st.session_state.get(sk.CAB_GROUPS, [])
        pre = [c for g in groups for c in g["codes"]]
        started = {t.task_code: t.name for t in data.tasks
                   if not t.is_loe_or_wbs and t.act_start is not None}
        picked = st.multiselect(
            "Activities to EXTRACT (remove from the sequence)",
            options=sorted(started),
            default=[c for c in dict.fromkeys(pre) if c in started],
            format_func=lambda c: f"{c} — {started[c][:60]}",
            key="cab_pick")
        st.session_state[sk.CAB_EXTRACT] = picked
        st.write(f"**{len(picked)}** activities in the extraction set.")

    else:
        st.subheader("③ Collapse and measure")
        picked = set(st.session_state.get(sk.CAB_EXTRACT, []))
        if not picked:
            st.info("Confirm an extraction set in step ② first.")
            return
        # HARD GATE: collapsing a file whose logic contradicts its own
        # actuals produces a meaningless but-for date. Found empirically
        # on the samples; enforced here, not just caveated.
        _oos_n = len(cached_oos_flags(_fkey(chosen), data))
        _rel_n = max(len(data.relationships), 1)
        if _oos_n / _rel_n > 0.05:
            st.error(
                f"This file carries {_oos_n} out-of-sequence records "
                f"({100 * _oos_n / _rel_n:.0f}% of its relationships). "
                "Re-imposing this logic unstatused serialises work that "
                "actually overlapped — the collapse would be unreliable. "
                "Repair the as-built logic first (Out-of-Sequence "
                "Repair → download the repaired .xer → load it at "
                "intake) and collapse THAT file.")
            if not st.checkbox(
                    "Override: run the collapse anyway (the validation "
                    "gap and this override will be disclosed)",
                    key="cab_oos_override"):
                return
        if st.button(f"Collapse ({len(picked)} activities extracted)",
                     type="primary", key="cab_go"):
            st.session_state[sk.CAB_RES] = collapse_asbuilt(
                data, chosen, picked,
                anchor_code=st.session_state.get(sk.CONTRACT_MS))
        res = st.session_state.get(sk.CAB_RES)
        if not res:
            return
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("As-built completion (recorded)",
                  f"{res.asbuilt_completion:%d %b %Y}"
                  if res.asbuilt_completion else "—")
        m2.metric("Unstatused model", f"{res.model_completion:%d %b %Y}"
                  if res.model_completion else "—",
                  help="Validation run BEFORE extraction — see the "
                       "calibration below.")
        m3.metric("Collapsed completion",
                  f"{res.collapsed_completion:%d %b %Y}"
                  if res.collapsed_completion else "—")
        m4.metric("DELAY ATTRIBUTABLE", f"{res.delta_days:+.1f} d"
                  if res.delta_days is not None else "—")
        st.caption(f"Model validation: unstatused model vs recorded "
                   f"as-built completion = "
                   f"{res.calibration_days:+.1f} calendar days "
                   f"({res.n_modelled} activities modelled, "
                   f"{res.n_excluded_unstarted} unstarted excluded).")
        for w in res.warnings:
            st.warning(w)
        if res.critical_chain or res.model_chain:
            def _chain_df(chain):
                return pd.DataFrame([{
                    "Activity ID": a.task_code, "Activity": a.name[:50],
                    "Duration (d)": a.duration_days,
                    "Start": f"{a.start:%Y-%m-%d}" if a.start else "—",
                    "Finish": f"{a.finish:%Y-%m-%d}" if a.finish else "—",
                    "Extracted": "YES" if a.removed else "",
                } for a in chain])
            with st.expander("Controlling chains — with events vs "
                             "collapsed (the trace behind the delta)"):
                st.caption(
                    "The delay attributable figure is the difference "
                    "between these two runs. Left: the chain governing "
                    "the model WITH the events in. Right: the chain the "
                    "model collapses onto once they are extracted.")
                c_model, c_collapsed = st.tabs(
                    ["With events (model)", "Collapsed (but-for)"])
                with c_model:
                    if res.model_chain:
                        st.dataframe(_chain_df(res.model_chain),
                                     width="stretch", hide_index=True)
                    else:
                        st.caption("No model chain derived.")
                with c_collapsed:
                    if res.critical_chain:
                        st.dataframe(_chain_df(res.critical_chain),
                                     width="stretch", hide_index=True)
                    else:
                        st.caption("No collapsed chain derived.")
        basis_panel("Collapsed As-Built", data, [
            "Method: collapsed as-built (but-for) — unstatused model on "
            "actual durations and the file's logic; extraction by "
            "zero-duration; delta between the two model runs",
            f"Extraction set: {len(res.removed_codes)} activities, "
            "analyst-confirmed",
            f"Model calibration vs recorded completion: "
            f"{res.calibration_days:+.1f} calendar days (disclosed)",
        ])
        with st.expander("Method caveats (always apply)"):
            for c in res.caveats:
                st.write("•", c)
        st.download_button(
            "⬇️ Download collapsed as-built workbook (Excel)",
            data=build_simple_xlsx(
                "Collapsed As-Built",
                {"Summary": [{
                    "Measure": k, "Value": v} for k, v in [
                    ("As-built completion (recorded)",
                     res.asbuilt_completion),
                    ("Unstatused model completion",
                     res.model_completion),
                    ("Collapsed completion", res.collapsed_completion),
                    ("Delay attributable (d)", res.delta_days),
                    ("Model calibration (d)", res.calibration_days),
                    ("Activities modelled", res.n_modelled),
                    ("Extracted", len(res.removed_codes))]],
                 "Extraction set": [{"Activity ID": c}
                                    for c in res.removed_codes],
                 "Chain with events": [{
                     "Activity ID": a.task_code, "Activity": a.name,
                     "Duration (d)": a.duration_days,
                     "Start": a.start, "Finish": a.finish,
                     "Extracted": "YES" if a.removed else ""}
                     for a in res.model_chain],
                 "Chain collapsed": [{
                     "Activity ID": a.task_code, "Activity": a.name,
                     "Duration (d)": a.duration_days,
                     "Start": a.start, "Finish": a.finish,
                     "Extracted": "YES" if a.removed else ""}
                     for a in res.critical_chain]},
                notes=res.warnings + res.caveats),
            file_name="collapsed_asbuilt.xlsx",
            mime="application/vnd.openxmlformats-officedocument."
                 "spreadsheetml.sheet",
            key="cab_dl")

    analysis_submodules("cab")
