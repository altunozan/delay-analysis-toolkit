"""Sequence Coding."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import state as sk
from dcma.narrative import NarrativeError, stream_narrative
from programme import (
    sequence_appendix,
    REVIEW_SYSTEM_PROMPT, STAGE_ORDER, UNCLASSIFIED,
    VIEW_ADVISOR_SYSTEM_PROMPT, analyse_sequence, build_gantt_html,
    build_mapping_review_prompt, build_sequence_prompt, build_sequence_xlsx,
    build_view_advice_prompt, group_tree, parse_mapping_review,
    parse_view_advice, propose_sequence_mapping, report_charts,
)
from programme.narrative import DEFAULT_TEMPLATES
from views._shared import (ai_narrative_panel, ai_provider_block,
                           get_parsed_files)


def sequence_tab() -> None:
    st.caption(
        "Recode the programme into work fronts × construction stages when "
        "activity codes and WBS fall short. The tool proposes the coding "
        "with evidence per assignment; you confirm or amend it — the final "
        "mapping is disclosed with the report."
    )
    files = get_parsed_files()
    inv = st.session_state.get(sk.INVENTORY)
    if not files or inv is None:
        st.info("Upload programmes in the **Data Intake** tab first.")
        return

    names = [r.file_name for r in inv.revisions]
    default_idx = len(names) - 1          # latest revision: most actuals
    chosen = st.selectbox("Programme", names, index=default_idx,
                          key="seq_prog",
                          help="Defaults to the latest revision (the one "
                               "with the most actual dates).")
    data = dict(files)[chosen]

    map_key = f"seq_rows_{chosen}"
    if map_key not in st.session_state or st.button(
            "↺ Re-propose mapping from file evidence", key="seq_repropose"):
        prop = propose_sequence_mapping(data, chosen)
        st.session_state[map_key] = prop
        st.session_state.pop(f"{map_key}_confirmed", None)
    prop = st.session_state[map_key]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Activities mapped", len(prop.rows))
    m2.metric("Work fronts", len(prop.fronts))
    m3.metric("Stage coverage", f"{prop.stage_coverage_pct:.0f}%")
    m4.metric("Front coverage", f"{prop.front_coverage_pct:.0f}%")
    for w in prop.warnings:
        st.warning(w)

    confirmed = st.session_state.get(f"{map_key}_confirmed", False)
    editor_ver = st.session_state.get(f"{map_key}_ver", 0)
    with st.expander(
        "Review & amend the proposed mapping"
        + (" — ✅ confirmed" if confirmed else " — ⚠️ not yet confirmed"),
        expanded=not confirmed,
    ):
        # --- AI review pass: the model proposes corrections; you confirm.
        st.markdown("**🤖 AI review of the coding** — the model reads "
                    "every activity and proposes corrections; they land "
                    "in the table below marked *AI review* and still "
                    "require your confirmation.")
        # THE shared provider block — managed default (Gemini), model
        # dropdown, own-key switch. The same function every other AI
        # feature renders; the page-local block it replaces read only
        # environment variables, so the managed key never reached it.
        r_provider, r_model, r_key = ai_provider_block("seq_rev_ai")
        scope = st.radio(
            "Rows to review", ["Unclassified / General only",
                               "All activities"],
            horizontal=True, key="seq_ai_scope")
        targets = [r for r in prop.rows
                   if scope.startswith("All")
                   or r.stage == UNCLASSIFIED or r.front == "General"]
        if st.button(f"Run AI review ({len(targets)} activities)",
                     disabled=not r_key or not targets, key="seq_ai_go"):
            BATCH = 120
            prog_bar = st.progress(0.0)
            applied = 0
            failures = []
            batches = [targets[i:i + BATCH]
                       for i in range(0, len(targets), BATCH)]
            by_code = {r.task_code: r for r in prop.rows}
            for j, batch in enumerate(batches):
                try:
                    text = "".join(stream_narrative(
                        r_provider, r_key,
                        build_mapping_review_prompt(batch),
                        r_model or None, system=REVIEW_SYSTEM_PROMPT))
                    changes = parse_mapping_review(
                        text, {r.task_code for r in batch})
                    for code, (front, stage) in changes.items():
                        row = by_code[code]
                        if front and front != row.front:
                            row.front, row.front_evidence = front, "AI review"
                            applied += 1
                        if stage and stage != row.stage:
                            row.stage, row.stage_evidence = stage, "AI review"
                            applied += 1
                except NarrativeError as exc:
                    failures.append(exc.message)
                    break
                prog_bar.progress((j + 1) / len(batches))
            if failures:
                st.error("AI review stopped: " + failures[0])
            else:
                # New proposals invalidate any previous confirmation and
                # need a fresh editor to show through.
                st.session_state.pop(f"{map_key}_confirmed", None)
                st.session_state[f"{map_key}_ver"] = editor_ver + 1
                st.session_state["seq_ai_summary"] = (
                    f"AI review proposed {applied} change(s) across "
                    f"{len(targets)} activities — review below and "
                    "Confirm.")
                st.rerun()
        if st.session_state.get("seq_ai_summary"):
            st.success(st.session_state.pop("seq_ai_summary"))

        st.caption(
            "Edit any Work front or Stage cell. Every row shows the "
            "evidence behind the proposal (rules, WBS, AI review, or "
            "analyst). Click Confirm to adopt the mapping for the "
            "analysis below and the report."
        )
        df = pd.DataFrame([{
            "Activity ID": r.task_code,
            "Activity": r.name,
            "Work front": r.front,
            "Stage": r.stage,
            "Front evidence": r.front_evidence,
            "Stage evidence": r.stage_evidence,
        } for r in prop.rows])
        edited = st.data_editor(
            df,
            column_config={
                "Activity ID": st.column_config.TextColumn(disabled=True),
                "Activity": st.column_config.TextColumn(disabled=True),
                "Work front": st.column_config.TextColumn(),
                "Stage": st.column_config.SelectboxColumn(
                    options=STAGE_ORDER),
                "Front evidence": st.column_config.TextColumn(
                    disabled=True),
                "Stage evidence": st.column_config.TextColumn(
                    disabled=True),
            },
            hide_index=True, width="stretch", height=360,
            key=f"seq_editor_{chosen}_v{editor_ver}",
        )
        if st.button("✅ Confirm mapping", type="primary",
                     key="seq_confirm"):
            for r, (_, row) in zip(prop.rows, edited.iterrows()):
                new_front = str(row["Work front"]).strip() or r.front
                new_stage = row["Stage"] or r.stage
                if new_front != r.front:
                    r.front, r.front_evidence = new_front, "analyst"
                if new_stage != r.stage:
                    r.stage, r.stage_evidence = new_stage, "analyst"
            st.session_state[f"{map_key}_confirmed"] = True
            st.rerun()

    seq = analyse_sequence(prop.rows, chosen, mapping_confirmed=confirmed)
    if not confirmed:
        st.info("The analysis below uses the auto-proposed mapping. "
                "Confirm the mapping above to remove this caveat from the "
                "report.")

    for w in seq.warnings:
        (st.info if w.startswith("Last-finishing") else st.warning)(w)

    # ---- configurable sequence chart -------------------------------------
    VIEW_MODES = {
        "Front × stage bands": "bands",
        "Stage timeline": "stage_timeline",
        "Sequence gantt (Front › Stage)": "sequence_gantt",
    }
    # the AI advisor sets these AFTER its own widgets rendered, which
    # Streamlit forbids for an instantiated widget key — stage the
    # values and apply them here, before the widgets are created
    for _k in ("seq_view", "seq_colour", "seq_maxfronts"):
        if f"{_k}_next" in st.session_state:
            st.session_state[_k] = st.session_state.pop(f"{_k}_next")
    vc1, vc2, vc3 = st.columns([2, 1, 1])
    view_label = vc1.radio("View", list(VIEW_MODES.keys()),
                           horizontal=True, key="seq_view")
    mode = VIEW_MODES[view_label]
    colour_by = vc2.selectbox("Colour by", ["Stage", "Front"],
                              key="seq_colour")
    max_fronts = vc3.slider("Fronts shown", 5, 40, 20, key="seq_maxfronts",
                            help="Last-finishing work fronts included.")
    with st.expander("🤖 Let the AI recommend the clearest view"):
        s_provider, s_model, s_key = ai_provider_block("seq_view_ai")
        if st.button("Recommend the best view", key="seq_vgo",
                     disabled=not s_key):
            try:
                text = "".join(stream_narrative(
                    s_provider, s_key,
                    build_view_advice_prompt(seq, len(prop.fronts)),
                    s_model or None, system=VIEW_ADVISOR_SYSTEM_PROMPT))
                advice = parse_view_advice(text)
            except NarrativeError as exc:
                advice = None
                st.error(exc.message)
            if advice:
                inv_modes = {v: k for k, v in VIEW_MODES.items()}
                # staged: the live widget keys cannot be written after
                # their widgets rendered this run
                st.session_state["seq_view_next"] = inv_modes[
                    advice["mode"]]
                st.session_state["seq_colour_next"] = advice["colour"]
                st.session_state["seq_maxfronts_next"] = \
                    advice["max_fronts"]
                st.session_state["seq_view_rationale"] = advice["rationale"]
                st.rerun()
            elif advice is None and s_key:
                st.warning("The model returned no usable recommendation.")
    if st.session_state.get("seq_view_rationale"):
        st.caption("🤖 " + st.session_state["seq_view_rationale"])

    keep = [f for f, _ in seq.fronts_by_finish[:max_fronts]]
    stage_domain = [s for s in seq.stage_order]
    stage_range = [report_charts.STAGE_COLORS.get(s, "#9e9e9e")
                   for s in stage_domain]

    def _colour_enc(field_fronts: list[str]):
        if colour_by == "Stage":
            return alt.Color("Stage:N",
                             scale=alt.Scale(domain=stage_domain,
                                             range=stage_range),
                             legend=alt.Legend(orient="bottom", columns=3,
                                               title=None))
        return alt.Color("Front:N",
                         scale=alt.Scale(domain=field_fronts,
                                         scheme="tableau20"),
                         legend=alt.Legend(orient="bottom", columns=4,
                                           title=None))

    chart = None
    if mode == "bands":
        rows_c = [{"Front": b.front, "Stage": b.stage, "Start": b.act_start,
                   "Finish": b.act_finish or b.act_start,
                   "Activities": b.activity_count}
                  for b in seq.bands
                  if b.front in keep and b.act_start]
        if rows_c:
            chart = (alt.Chart(pd.DataFrame(rows_c))
                     .mark_bar(height=7, cornerRadius=2, opacity=0.9)
                     .encode(
                         x=alt.X("Start:T", title=None,
                                 axis=alt.Axis(format="%b %Y")),
                         x2="Finish:T",
                         y=alt.Y("Front:N", sort=list(reversed(keep)),
                                 title=None,
                                 axis=alt.Axis(labelLimit=220,
                                               labelOverlap=False)),
                         color=_colour_enc(keep),
                         tooltip=["Front", "Stage", "Activities",
                                  alt.Tooltip("Start:T", format="%d %b %Y"),
                                  alt.Tooltip("Finish:T",
                                              format="%d %b %Y")])
                     .properties(height=max(220, 16 * len(keep))))
    elif mode == "stage_timeline":
        agg: dict[str, list] = {}
        for b in seq.bands:
            if b.front not in keep or b.act_start is None:
                continue
            agg.setdefault(b.stage, []).append(b)
        rows_c = [{"Stage": s,
                   "Start": min(b.act_start for b in bs),
                   "Finish": max((b.act_finish or b.act_start) for b in bs),
                   "Activities": sum(b.activity_count for b in bs),
                   "Front": f"{len({b.front for b in bs})} fronts"}
                  for s, bs in agg.items()]
        if rows_c:
            s_order = [s for s in seq.stage_order if s in agg]
            chart = (alt.Chart(pd.DataFrame(rows_c))
                     .mark_bar(height=14, cornerRadius=3, opacity=0.9)
                     .encode(
                         x=alt.X("Start:T", title=None,
                                 axis=alt.Axis(format="%b %Y")),
                         x2="Finish:T",
                         y=alt.Y("Stage:N", sort=s_order, title=None,
                                 axis=alt.Axis(labelLimit=260,
                                               labelOverlap=False)),
                         color=alt.Color(
                             "Stage:N",
                             scale=alt.Scale(domain=stage_domain,
                                             range=stage_range),
                             legend=None),
                         tooltip=["Stage", "Front", "Activities",
                                  alt.Tooltip("Start:T", format="%d %b %Y"),
                                  alt.Tooltip("Finish:T",
                                              format="%d %b %Y")])
                     .properties(height=30 * len(rows_c),
                                 title="Stage timeline across the works"))
    else:                        # sequence gantt at CODE level: Front › Stage
        by_front: dict[str, list] = {}
        for b in seq.bands:
            if b.front in keep and b.act_start:
                by_front.setdefault(b.front, []).append(b)
        # Fronts in chronological order of their first recorded start so
        # the gantt reads start -> finish down the page.
        front_seq = sorted(by_front,
                           key=lambda f: min(b.act_start
                                             for b in by_front[f]))
        seq_groups = []
        for front in front_seq:
            bands_f = sorted(
                by_front[front],
                key=lambda b: (seq.stage_order.index(b.stage)
                               if b.stage in seq.stage_order else 99))
            seq_groups.append({
                "name": front,
                "activities": [{
                    "id": b.stage,
                    "name": f"{b.activity_count} activities, "
                            f"{b.complete_count} complete",
                    "start": b.act_start,
                    "finish": b.act_finish or b.act_start,
                    "status": b.stage,
                } for b in bands_f],
            })
        if seq_groups:
            stages_present = [s for s in seq.stage_order
                              if any(b.stage == s
                                     for bs in by_front.values()
                                     for b in bs)]
            dd_sq = (f"{data.project.data_date:%Y-%m-%d}"
                     if data.project and data.project.data_date else None)
            st.iframe(
                build_gantt_html(
                    group_tree(seq_groups), data_date=dd_sq,
                    title=f"Sequence — Front › Stage ({chosen})",
                    categories=[
                        {"key": s, "label": s,
                         "color": report_charts.STAGE_COLORS.get(
                             s, "#9e9e9e")}
                        for s in stages_present]),
                height=620)
            st.caption("Code-level gantt: each work front expands into its "
                       "stage bands, coloured by stage · fronts in "
                       "start → finish order · dashed red line = data "
                       "date. (Colour-by applies to the other two views.)")
    if chart is not None:
        st.altair_chart(chart, width="stretch")
        st.caption("Bars = actual dates as recorded. Switch view, colour, "
                   "and front count above — or let the AI recommend the "
                   "clearest configuration.")

    with st.expander("Front × stage bands (table)"):
        st.dataframe(pd.DataFrame([{
            "Work front": b.front,
            "Stage": b.stage,
            "Activities": b.activity_count,
            "Complete": b.complete_count,
            "Actual start": (f"{b.act_start:%Y-%m-%d}"
                             if b.act_start else "—"),
            "Actual finish": (f"{b.act_finish:%Y-%m-%d}"
                              if b.act_finish else "—"),
        } for b in seq.bands]), width="stretch",
            hide_index=True, height=340)

    with st.expander("Standing caveats (always apply)"):
        for c in seq.caveats:
            st.write("•", c)

    narrative = ai_narrative_panel(
        f"nar_seq_{chosen}",
        lambda tmpl, s=seq: build_sequence_prompt(s, tmpl),
        "sequence",
        DEFAULT_TEMPLATES["sequence"],
        appendix_builder=lambda s=seq, r=prop.rows: sequence_appendix(
            s, mapping_rows=r),
    )
    st.download_button(
        "⬇️ Download sequence report (Excel, incl. disclosed mapping)",
        data=build_sequence_xlsx(seq, prop.rows, narrative),
        file_name="sequence_coding_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
