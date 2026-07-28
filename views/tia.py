"""Time Impact Analysis (stepped)."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

import state as sk
from dcma import DCMAConfig, run_all_checks
from dcma.checks import CheckStatus
from dcma.narrative import NarrativeError, PROVIDERS, stream_narrative
from programme import (
    tia_appendix,
    CLAUSE_SYSTEM_PROMPT, DelayEvent, EXPORT_CAVEAT, EXTRACTION_SYSTEM_PROMPT,
    FRAGNET_SYSTEM_PROMPT, FRAGNET_VARIANTS, FragnetActivity, FragnetLink,
    LOGIC_SYSTEM_PROMPT, NOTICE_CAVEAT, assess_event_scope, assess_notice,
    build_clause_extraction_prompt, build_event_extraction_prompt,
    build_fragnet_variant_prompt, build_gantt_html, build_impacted_xer,
    build_logic_recommendation_prompt, build_tia_prompt, build_tia_xlsx,
    event_from_dict, event_to_dict, find_template_activities,
    find_template_work_packages, group_tree, links_to_text,
    parse_clause_extraction, parse_event_candidates, parse_fragnet_json,
    parse_links, parse_logic_recommendation_json, read_document,
    recommended_analysis_schedule, register_from_json, register_to_json,
    run_cumulative_tia, run_tia, truncation_notes, validate_fragnet,
)
from programme.narrative import DEFAULT_TEMPLATES
from views._shared import (
    ai_credentials_panel, ai_narrative_panel, basis_panel,
    fetch_raw, get_parsed_files, log_ai_use, resolve_ai_credentials,
)
from views._submodules import analysis_submodules


def _tia_event_from_state() -> DelayEvent:
    try:
        d = st.session_state.get("tia_ev_date", "").strip()
        ev_date = datetime.strptime(d, "%Y-%m-%d") if d else None
    except ValueError:
        ev_date = None
    return DelayEvent(
        (st.session_state.get("tia_ev_id") or "EV-001").strip(),
        (st.session_state.get("tia_ev_title") or "").strip(),
        (st.session_state.get("tia_ev_desc") or "").strip(),
        ev_date,
        (st.session_state.get("tia_ev_resp") or "").strip(),
        (st.session_state.get("tia_ev_evid") or "").strip())


def _tia_fragnet_from_state(data) -> list[FragnetActivity]:
    fragnet: list[FragnetActivity] = []
    if st.session_state.get("tia_frag_mode",
                            "Chain builder (simple)").startswith("Chain"):
        rows = [(str(r.get("Step") or "").strip(),
                 float(r.get("Duration (d)") or 0))
                for r in st.session_state.get("tia_chain_steps", [])
                if str(r.get("Step") or "").strip()]
        entry = st.session_state.get("tia_entry", "")
        exit_c = st.session_state.get("tia_exit", "")
        for i, (name, dur) in enumerate(rows):
            preds = ([FragnetLink(f"TIA-{i * 10:03d}")] if i else
                     ([FragnetLink(entry)]
                      if entry and not entry.startswith("—") else []))
            succs = ([FragnetLink(exit_c)]
                     if exit_c and i == len(rows) - 1 else [])
            fragnet.append(FragnetActivity(
                act_id=f"TIA-{(i + 1) * 10:03d}", name=name,
                duration_days=dur, predecessors=preds, successors=succs,
                rationale="chain builder"))
    else:
        for row in st.session_state.get("tia_frag_rows", []):
            fid = str(row.get("ID") or "").strip()
            if not fid:
                continue
            try:
                dur = float(row.get("Duration (d)") or 0)
            except (TypeError, ValueError):
                dur = 0.0
            fragnet.append(FragnetActivity(
                act_id=fid, name=str(row.get("Activity") or "").strip(),
                duration_days=dur,
                predecessors=parse_links(str(row.get("Predecessors") or "")),
                successors=parse_links(str(row.get("Successors") or "")),
                rationale=str(row.get("Source / rationale") or "").strip(),
                assumptions=str(row.get("Assumptions") or "").strip()))
    return fragnet


_TIA_STEPS = ["① Update & AI", "② Event", "③ Fragnet",
              "④ Validate & confirm", "⑤ Run impact", "⑥ Review",
              "⑦ Export & audit"]


def tia_tab() -> None:
    files = get_parsed_files()
    inv = st.session_state.get(sk.INVENTORY)
    if not files or inv is None:
        st.info("Upload the current accepted update (one XER is enough "
                "for a prospective TIA) in the **Data Intake** tab. Two "
                "or more revisions additionally unlock the historical "
                "modules and Explain This Delay.")
        return

    # Streamlit drops widget-backed state once its widget is not
    # rendered; each step renders only its own widgets, so every
    # cross-step key must be re-pinned each run.
    _persist = (sk.AI_KEY, sk.AI_PROVIDER, "tia_prog", "tia_ev_id",
                "tia_ev_title", "tia_ev_desc", "tia_ev_date",
                "tia_ev_resp", "tia_ev_evid", "tia_frag_mode",
                "tia_entry", "tia_exit", "tia_target_ms", "tia_variant",
                "tia_cl_ref", "tia_cl_days", "tia_cl_notice",
                "tia_cl_basis",
                "c_dd", "c_logic", "c_dur", "c_resp", "c_meth",
                "tia_step")
    for _k in _persist:
        if _k in st.session_state:
            st.session_state[_k] = st.session_state[_k]
    if "tia_step_next" in st.session_state:
        st.session_state["tia_step"] = st.session_state.pop(
            "tia_step_next")
    step = st.radio("TIA workflow", _TIA_STEPS, horizontal=True,
                    key="tia_step", label_visibility="collapsed")

    def _nav(idx: int) -> None:
        b, c = st.columns([1, 5])
        if idx > 0 and b.button("← Back", key=f"tia_back_{idx}"):
            st.session_state["tia_step_next"] = _TIA_STEPS[idx - 1]
            st.rerun()
        if idx < len(_TIA_STEPS) - 1 and c.button(
                f"Continue → {_TIA_STEPS[idx + 1]}",
                type="primary", key=f"tia_next_{idx}"):
            st.session_state["tia_step_next"] = _TIA_STEPS[idx + 1]
            st.rerun()
    names = [r.file_name for r in inv.revisions]
    chosen = st.session_state.get("tia_prog", names[-1])
    if chosen not in names:
        chosen = names[-1]
    data = dict(files)[chosen]
    event = _tia_event_from_state()
    # Resolved exactly as the narrative panels resolve credentials —
    # managed key straight from secrets, so jumping directly to a later
    # step in a fresh session still has working AI (the session-state
    # copy only exists once a credentials panel has rendered).
    ai_provider, _ai_model, ai_key = resolve_ai_credentials()
    ai_model = _ai_model or None

    # ---- ① update + AI registration + health gateway --------------------
    if step == _TIA_STEPS[0]:
        st.subheader("① Select the current update & register your AI")
        if st.session_state.get("tia_prog") not in names:
            st.session_state["tia_prog"] = names[-1]
        st.selectbox(
            "Current accepted update (the analysis schedule)", names,
            key="tia_prog",
            help="AACE RP 52R-06: use the last accepted update with a "
                 "data date before the event. The fragnet is inserted "
                 "into an in-memory copy only.")
        dd = data.project.data_date if data.project else None
        st.caption(f"Data date: **{dd:%d %b %Y}**" if dd
                   else "⚠️ No data date in this file.")
        # Schedule-Health gateway
        fails = [r for r in run_all_checks(data, DCMAConfig())
                 if r.status == CheckStatus.FAIL]
        serious = [r for r in fails if r.number in (1, 2, 5, 7, 9, 11)]
        if serious:
            st.warning(
                "**Schedule-Health gateway:** this update fails "
                f"{len(fails)} of 14 DCMA checks, including "
                + ", ".join(f"#{r.number} {r.name}" for r in serious)
                + ". Serious defects (open logic, leads, constraints, "
                "negative float, invalid dates, out-of-sequence) weaken "
                "any TIA built on it — review the Schedule Health tab "
                "before relying on the result.")
        else:
            st.success("Schedule-Health gateway: no serious DCMA "
                       "failures detected.")
        st.markdown("**Register your AI once** — every later step "
                    "(event extraction, fragnet recommendation, "
                    "narrative) reuses it.")
        ai_credentials_panel("tia")
        _nav(0)
        return

    # ---- ② event ---------------------------------------------------------
    if step == _TIA_STEPS[1]:
        st.subheader("② Register the event")
        reg = st.session_state.setdefault(sk.EVENT_REGISTER, {})
        with st.expander(f"📇 Event register ({len(reg)} saved)"):
            for rid, rec in list(reg.items()):
                rc1, rc2, rc3 = st.columns([4, 1, 1])
                last = rec.get("last_result", {})
                delta = last.get("completion_delta_days")
                rc1.write(f"**{rid}** — {rec['event'].get('title', '')}"
                          + (f" · impact {delta:+.1f}d"
                             if delta is not None else " · not yet run"))
                if rc2.button("Load", key=f"tia_load_{rid}"):
                    parsed = event_from_dict(rec)
                    if parsed:
                        ev_l, fr_l = parsed
                        st.session_state["tia_ev_id"] = ev_l.event_id
                        st.session_state["tia_ev_title"] = ev_l.title
                        st.session_state["tia_ev_desc"] = ev_l.description
                        st.session_state["tia_ev_date"] = (
                            f"{ev_l.date_raised:%Y-%m-%d}"
                            if ev_l.date_raised else "")
                        st.session_state["tia_ev_resp"] = (
                            ev_l.responsibility_asserted)
                        st.session_state["tia_ev_evid"] = ev_l.evidence_note
                        st.session_state["tia_frag_rows"] = [{
                            "ID": f.act_id, "Activity": f.name,
                            "Duration (d)": f.duration_days,
                            "Predecessors": links_to_text(f.predecessors),
                            "Successors": links_to_text(f.successors),
                            "Source / rationale": f.rationale,
                            "Assumptions": f.assumptions,
                        } for f in fr_l]
                        st.session_state["tia_frag_mode"] = "Advanced grid"
                        st.session_state.pop("tia_result", None)
                        st.rerun()
                if rc3.button("Delete", key=f"tia_del_{rid}"):
                    reg.pop(rid, None)
                    st.rerun()
            dc1, dc2 = st.columns(2)
            if reg:
                dc1.download_button("⬇️ Download register (JSON)",
                                    data=register_to_json(
                                        list(reg.values())),
                                    file_name="delay_event_register.json",
                                    mime="application/json",
                                    key="tia_reg_dl")
            up = dc2.file_uploader("Load register", type=["json"],
                                   key="tia_reg_up")
            if up is not None:
                loaded = register_from_json(up.getvalue().decode("utf-8"))
                if loaded and st.button(f"Import {len(loaded)} event(s)",
                                        key="tia_reg_imp"):
                    for rec in loaded:
                        reg[rec["event"]["event_id"]] = rec
                    st.rerun()

        with st.expander("📄 From letters or a dated narrative "
                         "(AI extraction, verified quotations)",
                         expanded=not event.title):
            ups = st.file_uploader("Documents (txt, docx, pdf)",
                                   type=["txt", "docx", "pdf"],
                                   accept_multiple_files=True,
                                   key="tia_docs")
            pasted = st.text_area(
                "Or a short dated narrative of the event(s)",
                key="tia_narrative", height=90,
                placeholder="On 12 Mar 2018 the Engineer issued EI-88 "
                            "requiring additional ceiling works …")
            docs: list[tuple[str, str]] = []
            for up in ups or []:
                text = read_document(up.name, up.getvalue())
                if text.strip():
                    docs.append((up.name, text))
                else:
                    st.warning(f"Could not read '{up.name}'.")
            if pasted.strip():
                docs.append(("analyst narrative", pasted.strip()))
            for note in truncation_notes(docs):
                st.warning(note)
            if st.button(f"Extract candidate events from {len(docs)} "
                         "document(s)", key="tia_x_go", type="primary",
                         disabled=not ai_key or not docs):
                try:
                    text = "".join(stream_narrative(
                        ai_provider, ai_key,
                        build_event_extraction_prompt(docs),
                        ai_model, system=EXTRACTION_SYSTEM_PROMPT))
                    cands, dropped = parse_event_candidates(text, docs)
                    log_ai_use("TIA event extraction", ai_provider,
                               ai_model)
                except NarrativeError as exc:
                    cands, dropped = [], 0
                    st.error(exc.message)
                st.session_state["tia_candidates"] = cands
                st.session_state["tia_cand_dropped"] = dropped
                st.rerun()
            if not ai_key:
                st.caption("Register an API key in step ① to enable "
                           "extraction.")
            dropped = st.session_state.get("tia_cand_dropped", 0)
            if dropped:
                st.warning(f"{dropped} candidate(s) DROPPED — quoted "
                           "evidence not found verbatim in the source.")
            for k, c in enumerate(st.session_state.get("tia_candidates",
                                                       [])):
                cc1, cc2 = st.columns([5, 1])
                d = (f"{c.date_start:%Y-%m-%d}" if c.date_start
                     else "no date")
                if c.date_end:
                    d += (f" → {c.date_end:%Y-%m-%d}"
                          + (f", {c.stated_duration_days:.0f}d documented"
                             if c.stated_duration_days is not None else ""))
                cc1.markdown(f"**{c.title}** ({d}, {c.confidence})  \n"
                             f"› *{c.source_doc}*: “{c.source_snippet}”")
                if cc2.button("Use", key=f"tia_use_{k}"):
                    st.session_state["tia_ev_id"] = f"EV-{k + 1:03d}"
                    st.session_state["tia_ev_title"] = c.title
                    desc = c.description
                    if c.stated_duration_days is not None:
                        desc += (f"\nDocumented duration: "
                                 f"{c.stated_duration_days:.0f} days "
                                 f"({c.date_start:%Y-%m-%d} to "
                                 f"{c.date_end:%Y-%m-%d} per source).")
                    if c.other_dates:
                        desc += "\nKey dates: " + ", ".join(c.other_dates)
                    st.session_state["tia_ev_desc"] = desc
                    st.session_state["tia_ev_date"] = (
                        f"{c.date_start:%Y-%m-%d}" if c.date_start else "")
                    st.session_state["tia_ev_resp"] = c.party_asserted
                    st.session_state["tia_ev_evid"] = (
                        f"{c.source_doc}: \"{c.source_snippet}\"")
                    st.rerun()

        ec1, ec2, ec3 = st.columns([1, 2, 1])
        ec1.text_input("Event ID", key="tia_ev_id")
        ec2.text_input("Title", key="tia_ev_title")
        ec3.text_input("Date raised (YYYY-MM-DD)", key="tia_ev_date")
        st.text_area("Description (scope of the instructed / delayed "
                     "work)", key="tia_ev_desc", height=80)
        ec4, ec5 = st.columns(2)
        ec4.text_input("Responsibility asserted (not concluded)",
                       key="tia_ev_resp")
        ec5.text_input("Evidence noted", key="tia_ev_evid")
        event = _tia_event_from_state()
        with st.expander("⚖️ Contractual notice (screening — date "
                         "arithmetic only)", expanded=False):
            n1, n2, n3, n4 = st.columns([1, 1, 1, 1])
            n1.text_input("Clause ref", key="tia_cl_ref",
                          placeholder="e.g. 20.1")
            n2.text_input("Notice period (days)", key="tia_cl_days")
            n3.text_input("Notice date (YYYY-MM-DD)", key="tia_cl_notice")
            n4.selectbox("Days basis", ["calendar", "business"],
                         key="tia_cl_basis",
                         help="How the clause counts days. Business = "
                              "Mon-Fri; contract-specific holidays are "
                              "not modelled.")
            try:
                _pd_ = float(st.session_state.get("tia_cl_days") or "")
            except ValueError:
                _pd_ = None
            try:
                _nd_ = datetime.strptime(
                    (st.session_state.get("tia_cl_notice") or "").strip(),
                    "%Y-%m-%d")
            except ValueError:
                _nd_ = None
            na = assess_notice(
                event.date_raised, _nd_, _pd_,
                basis=st.session_state.get("tia_cl_basis", "calendar"))
            badge = {"compliant": st.success, "late": st.error,
                     "no_notice": st.warning,
                     "indeterminate": st.info}[na.status]
            badge(f"Status: {na.status.upper()} — {na.detail} "
                  f"(clause {st.session_state.get('tia_cl_ref') or '—'})")
            st.caption(NOTICE_CAVEAT)
            ct = st.text_area("Optional: paste contract extract for AI "
                              "clause mapping (verbatim-verified)",
                              key="tia_cl_text", height=80)
            if st.button("Extract clause mechanics", key="tia_cl_go",
                         disabled=not ai_key or not ct.strip()):
                try:
                    txt = "".join(stream_narrative(
                        ai_provider, ai_key,
                        build_clause_extraction_prompt(ct),
                        ai_model, system=CLAUSE_SYSTEM_PROMPT))
                    st.session_state["tia_clauses"] = (
                        parse_clause_extraction(txt, ct))
                    log_ai_use("TIA clause extraction", ai_provider,
                               ai_model)
                except NarrativeError as exc:
                    st.error(exc.message)
            cl = st.session_state.get("tia_clauses")
            if cl:
                st.dataframe(pd.DataFrame(cl), width="stretch",
                             hide_index=True)
                st.caption("Silent topics carry no quotation; every "
                           "non-silent entry's quotation was verified "
                           "against the pasted text.")
        rec = recommended_analysis_schedule(
            [(r.file_name, r.data_date) for r in inv.revisions],
            event.date_raised)
        if rec and rec != chosen:
            st.info(f"AACE RP 52R-06: the last update before this event "
                    f"is **{rec}** — currently analysing **{chosen}** "
                    "(change in step ①).")
        if event.title:
            scope = assess_event_scope(event)
            with st.expander("🧭 Event understanding (deterministic — "
                             "review before drafting)", expanded=False):
                st.markdown(f"**Nature of work:** {scope.work_nature}")
                st.markdown("**Lifecycle stages indicated:** "
                            + "; ".join(scope.lifecycle_stages))
                if scope.enabling_requirements:
                    st.markdown("**Enabling requirements:** "
                                + "; ".join(scope.enabling_requirements))
                if scope.unanswered_questions:
                    st.markdown("**Unanswered questions "
                                "(answer to improve the draft):**")
                    for q in scope.unanswered_questions:
                        st.write("•", q)
        if not event.title:
            st.caption("Give the event a title to continue.")
        _nav(1)
        return

    if not event.title:
        st.info("Register the event in step ② first.")
        return

    # ---- ③ fragnet -------------------------------------------------------
    if step == _TIA_STEPS[2]:
        st.subheader("③ Build the fragnet")
        fragnet = _tia_fragnet_from_state(data)
        templates = find_template_activities(
            data, f"{event.title} {event.description}")
        packages = find_template_work_packages(
            data, f"{event.title} {event.description}")
        with st.expander(f"Comparable activities & work packages "
                         f"({len(templates)} / {len(packages)})",
                         expanded=False):
            for pkg in packages:
                st.markdown(f"**{pkg['wbs_name']}** — "
                            f"{pkg['activity_count']} activities, matched "
                            f"on {pkg['matched'] or '—'}; existing "
                            "sequence:")
                st.caption(" → ".join(
                    f"{a['code']} {a['name'][:30]}"
                    for a in pkg["activities"][:6]))
            if templates:
                st.dataframe(pd.DataFrame([{
                    "Activity ID": t["code"], "Activity": t["name"],
                    "Duration (d)": (round(t["duration_days"], 1)
                                     if t["duration_days"] is not None
                                     else None),
                } for t in templates]), width="stretch",
                    hide_index=True)
        with st.expander("🤖 Evidence-assisted fragnet recommendation "
                         "(AI drafts — the planner verifies)",
                         expanded=False):
            variant = st.radio("Discipline",
                               list(FRAGNET_VARIANTS.keys()), index=1,
                               horizontal=True, key="tia_variant")
            if st.button(f"Draft {variant} fragnet", key="tia_ai_go",
                         type="primary",
                         disabled=not ai_key):
                try:
                    text = "".join(stream_narrative(
                        ai_provider, ai_key,
                        build_fragnet_variant_prompt(
                            event, templates, data, variant),
                        ai_model, system=FRAGNET_SYSTEM_PROMPT))
                    draft = parse_fragnet_json(text, data)
                    log_ai_use("TIA fragnet draft", ai_provider, ai_model)
                except NarrativeError as exc:
                    draft = []
                    st.error(exc.message)
                if draft:
                    st.session_state["tia_frag_rows"] = [{
                        "ID": f.act_id, "Activity": f.name,
                        "Duration (d)": f.duration_days,
                        "Predecessors": links_to_text(f.predecessors),
                        "Successors": links_to_text(f.successors),
                        "Source / rationale": f.rationale,
                        "Assumptions": f.assumptions,
                    } for f in draft]
                    st.session_state["tia_frag_mode"] = "Advanced grid"
                    st.rerun()
                elif ai_key:
                    st.warning("No valid fragnet returned — add detail "
                               "to the event description.")
            if not ai_key:
                st.caption("Register an API key in step ① to enable the "
                           "recommendation.")

        st.radio("Builder", ["Chain builder (simple)", "Advanced grid"],
                 horizontal=True, key="tia_frag_mode")
        inc_acts = sorted(
            (t for t in data.tasks
             if not t.is_loe_or_wbs and t.is_incomplete),
            key=lambda t: (t.act_finish or t.early_finish
                           or t.early_start or datetime.max))
        act_label = {t.task_code: f"{t.task_code} — {t.name}"
                     for t in inc_acts}
        ms_codes = [t.task_code for t in reversed(inc_acts)
                    if t.is_milestone]
        if st.session_state["tia_frag_mode"].startswith("Chain"):
            NO_ENTRY = "— none (chain starts at the data date) —"
            c1, c2 = st.columns(2)
            c1.selectbox("Where does the event work start from?",
                         [NO_ENTRY] + list(act_label.keys()),
                         format_func=lambda c: act_label.get(c, c),
                         key="tia_entry")
            exit_opts = ms_codes + [c for c in act_label
                                    if c not in ms_codes]
            c2.selectbox("What does it delay?", exit_opts,
                         format_func=lambda c: act_label.get(c, c),
                         key="tia_exit")
            if "tia_chain_steps" not in st.session_state:
                st.session_state["tia_chain_steps"] = [
                    {"Step": "", "Duration (d)": 0.0}]
            steps_df = st.data_editor(
                pd.DataFrame(st.session_state["tia_chain_steps"]),
                num_rows="dynamic", width="stretch",
                key="tia_chain_editor")
            st.session_state["tia_chain_steps"] = steps_df.to_dict(
                "records")
            st.caption("Steps link finish-to-start automatically.")
        else:
            if "tia_frag_rows" not in st.session_state:
                st.session_state["tia_frag_rows"] = [{
                    "ID": "TIA-010", "Activity": "",
                    "Duration (d)": 0.0, "Predecessors": "",
                    "Successors": "", "Source / rationale": "",
                    "Assumptions": ""}]
            edited = st.data_editor(
                pd.DataFrame(st.session_state["tia_frag_rows"]),
                num_rows="dynamic", width="stretch",
                key="tia_grid_editor")
            st.session_state["tia_frag_rows"] = edited.to_dict("records")
            st.caption("Links: `ACTIVITYID:FS:0; TIA-010:SS:5`.")
        fragnet = _tia_fragnet_from_state(data)
        if fragnet:
            from datetime import timedelta as _td
            es = (data.project.data_date if data.project
                  and data.project.data_date else datetime.now())
            prev_lid, pacts = None, []
            for f in fragnet:
                ef = es + _td(days=max(f.duration_days, 0.0))
                lid = f"pv:{f.act_id}"
                pacts.append({"id": f.act_id, "name": f.name,
                              "start": es, "finish": ef,
                              "status": "fragnet", "lid": lid,
                              "links": []})
                if prev_lid:
                    pacts[-2]["links"] = [lid]
                prev_lid, es = lid, ef
            st.iframe(
                build_gantt_html(
                    group_tree([{"name": "Fragnet preview (sequential, "
                                 "from the data date)",
                                 "activities": pacts}]),
                    data_date=(f"{data.project.data_date:%Y-%m-%d}"
                               if data.project
                               and data.project.data_date else None),
                    title="Fragnet preview",
                    categories=[{"key": "fragnet", "label": "fragnet",
                                 "color": "#B07A24"}]),
                height=170 + 26 * len(pacts))
            st.caption("Preview only — sequential FS chain from the data "
                       "date; the impact run applies the real tie-ins "
                       "and calendars.")
        with st.expander("🧩 Recommend tie-ins & impacted sections "
                         "(AI ranks — the planner applies)",
                         expanded=False):
            if st.button("Recommend logic for this fragnet",
                         key="tia_logic_go", type="primary",
                         disabled=not ai_key or not fragnet):
                try:
                    text = "".join(stream_narrative(
                        ai_provider, ai_key,
                        build_logic_recommendation_prompt(
                            event, fragnet, data),
                        ai_model, system=LOGIC_SYSTEM_PROMPT))
                    st.session_state["tia_logic_rec"] = (
                        parse_logic_recommendation_json(text, data))
                    log_ai_use("TIA logic recommendation", ai_provider,
                               ai_model)
                except NarrativeError as exc:
                    st.error(exc.message)
            if not ai_key:
                st.caption("Register an API key in step ① to enable "
                           "recommendations.")
            rec_l = st.session_state.get("tia_logic_rec") or {}
            for key_r, label_r in (("predecessors", "Predecessor tie-in "
                                    "candidates"),
                                   ("successors", "Successor tie-in "
                                    "candidates"),
                                   ("impacted_sections",
                                    "Potentially impacted sections / "
                                    "milestones")):
                items = rec_l.get(key_r) or []
                if items:
                    st.markdown(f"**{label_r}** (ranked)")
                    st.dataframe(pd.DataFrame(items),
                                 width="stretch",
                                 hide_index=True)
            for w in rec_l.get("warnings", []):
                st.warning(w)
            if rec_l:
                st.caption("Apply your chosen tie-ins via the chain "
                           "builder pickers or the advanced grid — "
                           "recommendations are never auto-inserted.")
        st.caption(f"{len(fragnet)} fragnet activities."
                   if fragnet else "Add at least one step to continue.")
        _nav(2)
        return

    fragnet = _tia_fragnet_from_state(data)
    if not fragnet:
        st.info("Build the fragnet in step ③ first.")
        return

    # ---- ④ validate & confirm -------------------------------------------
    if step == _TIA_STEPS[3]:
        st.subheader("④ Validate the logic & confirm the basis")
        issues = validate_fragnet(data, fragnet)
        if issues:
            st.warning("**Validation findings:**\n\n"
                       + "\n".join(f"- {i}" for i in issues))
        else:
            st.success("Fragnet passes the screening checks.")
        st.dataframe(pd.DataFrame([{
            "ID": f.act_id, "Activity": f.name,
            "Duration (d)": f.duration_days,
            "Predecessors": links_to_text(f.predecessors),
            "Successors": links_to_text(f.successors),
        } for f in fragnet]), width="stretch", hide_index=True)
        ms_opts = [t.task_code for t in sorted(
            (x for x in data.tasks if x.is_milestone
             and not x.is_loe_or_wbs and x.is_incomplete),
            key=lambda x: (x.early_finish or x.early_start
                           or datetime.max), reverse=True)]
        ms_names = {t.task_code: f"{t.task_code} — {t.name}"
                    for t in data.tasks}
        if ms_opts:
            st.selectbox("Impacted milestone to prioritise in the "
                         "results", ms_opts,
                         format_func=lambda c: ms_names.get(c, c),
                         key="tia_target_ms")
        st.markdown("**Analyst confirmation** — required before the run:")
        dd = data.project.data_date if data.project else None
        checks = {
            "c_dd": f"Data date ({dd:%d %b %Y}) and analysis schedule "
                    f"('{chosen}') are the correct 52R-06 basis"
                    if dd else f"Analysis schedule ('{chosen}') confirmed",
            "c_logic": "Fragnet predecessors/successors reviewed and "
                       "represent the event realistically",
            "c_dur": "Durations are reasonable forecasts (calendars "
                     "approximated as elapsed days — see caveats)",
            "c_resp": "Responsibility is recorded as ASSERTED, not "
                      "determined",
            "c_meth": "Method understood: simplified-CPM delta per "
                      "AACE RP 52R-06; absolute dates to be confirmed "
                      "in P6",
        }
        all_ok = all(st.checkbox(lbl, key=k) for k, lbl in checks.items())
        st.session_state["tia_confirmed"] = all_ok
        if not all_ok:
            st.caption("Tick every confirmation to unlock the run.")
        _nav(3)
        return

    if not st.session_state.get("tia_confirmed"):
        st.info("Complete the confirmation checklist in step ④ first.")
        return

    # ---- ⑤ run ------------------------------------------------------------
    if step == _TIA_STEPS[4]:
        st.subheader("⑤ Run the impact")
        if st.button("⚡ Run time impact analysis", type="primary",
                     key="tia_run"):
            res = run_tia(data, chosen, event, fragnet,
                          target_milestone=st.session_state.get(
                              'tia_target_ms'))
            st.session_state["tia_result"] = res
            st.session_state["tia_audit"] = {
                "analysed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "source_file": chosen,
                "source_sha256": st.session_state.get(
                    sk.XER_HASHES, {}).get(chosen, "not recorded"),
                "data_date": (f"{res.data_date:%Y-%m-%d}"
                              if res.data_date else "—"),
                "event_id": event.event_id,
                "fragnet_activities": len(fragnet),
                "method": "Simplified-CPM forward pass (elapsed-day "
                          "calendars), pre/post delta per AACE RP 52R-06",
                "ai_provider": (PROVIDERS[ai_provider]["label"]
                                if ai_key else "none (manual)"),
            }
            st.success("Run complete.")
        elif st.session_state.get("tia_result") is not None:
            st.info("A result exists — re-run to refresh it, or "
                    "continue.")
        _nav(4)
        return

    res = st.session_state.get("tia_result")
    if res is None:
        st.info("Run the impact in step ⑤ first.")
        return

    # ---- ⑥ review ----------------------------------------------------------
    if step == _TIA_STEPS[5]:
        st.subheader("⑥ Review the results")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Completion (pre)", f"{res.completion_pre:%d %b %Y}"
                  if res.completion_pre else "—")
        m2.metric("Completion (post)", f"{res.completion_post:%d %b %Y}"
                  if res.completion_post else "—")
        m3.metric("Forecast impact",
                  f"{res.completion_delta_days:+.1f} days"
                  if res.completion_delta_days is not None else "—")
        m4.metric("Calibration vs P6",
                  f"{res.calibration_days:+.1f} d"
                  if res.calibration_days is not None else "—")
        for w in res.warnings:
            (st.success if w.startswith("Favourable")
             else st.warning)(w)
        affected = [m for m in res.milestone_impacts
                    if (m.delta_days or 0) != 0
                    or (m.float_consumed_days or 0) != 0]
        st.dataframe(pd.DataFrame([{
            "Milestone": m.code, "Name": m.name,
            "Pre": f"{m.pre:%Y-%m-%d}" if m.pre else "—",
            "Post": f"{m.post:%Y-%m-%d}" if m.post else "—",
            "Delta (d)": m.delta_days,
            "TF pre (d)": m.float_pre,
            "TF post (d)": m.float_post,
            "TF consumed (d)": m.float_consumed_days,
        } for m in (affected or res.milestone_impacts)]),
            width="stretch", hide_index=True)
        if res.tie_in_float:
            st.markdown("**Float at the fragnet tie-ins** (screening "
                        "backward pass)")
            st.dataframe(pd.DataFrame([{
                "Tie-in": r["code"], "Name": r["name"],
                "TF pre (d)": r["float_pre"],
                "TF post (d)": r["float_post"],
                "Consumed (d)": r["consumed"],
            } for r in res.tie_in_float]),
                width="stretch", hide_index=True)
        # --- longest-path comparison: pre vs post impact ---------------
        if res.path_pre or res.path_post:
            st.subheader("Longest-path comparison — pre vs post impact")

            def _path_acts(path, prefix, frag_cat=False):
                out = []
                for i, p in enumerate(path):
                    cat = ("fragnet" if (frag_cat and p["fragnet"])
                           else prefix)
                    out.append({
                        "id": p["id"], "name": p["name"],
                        "start": p["start"], "finish": p["finish"],
                        "status": cat, "lid": f"{prefix}:{p['id']}",
                        "links": ([f"{prefix}:{path[i + 1]['id']}"]
                                  if i + 1 < len(path) else []),
                    })
                return out

            pre_acts = _path_acts(res.path_pre, "pre")
            post_all = _path_acts(res.path_post, "post", frag_cat=True)
            frag_acts = [a for a in post_all if a["status"] == "fragnet"]
            main_acts = [a for a in post_all if a["status"] != "fragnet"]
            post_children = ([{"name": f"Fragnet — {event.event_id}",
                               "activities": frag_acts}]
                             if frag_acts else [])
            tree = group_tree([
                {"name": f"Pre-impact longest path "
                         f"(completes {res.completion_pre:%d %b %Y})"
                 if res.completion_pre else "Pre-impact longest path",
                 "activities": pre_acts},
                {"name": f"Post-impact longest path "
                         f"(completes {res.completion_post:%d %b %Y})"
                 if res.completion_post else "Post-impact longest path",
                 "children": post_children,
                 "activities": main_acts},
            ])
            dd_t = (f"{res.data_date:%Y-%m-%d}"
                    if res.data_date else None)
            st.iframe(
                build_gantt_html(
                    tree, data_date=dd_t,
                    title=f"TIA {event.event_id} — driving paths",
                    categories=[
                        {"key": "pre", "label": "pre-impact path",
                         "color": "#14324A"},
                        {"key": "post", "label": "post-impact path",
                         "color": "#9B3227"},
                        {"key": "fragnet", "label": "fragnet (event)",
                         "color": "#B07A24"},
                    ]),
                height=430)
            st.caption("Arrows = driving logic along each path · the "
                       "fragnet sits as its own group inside the "
                       "post-impact path · dashed red line = data date.")

        with st.expander("Standing caveats (always apply)"):
            for c in res.caveats:
                st.write("•", c)
        _nav(5)
        return

    # ---- ⑦ export & audit ---------------------------------------------------
    st.subheader("⑦ Export & audit trail")
    audit = st.session_state.get("tia_audit", {})
    if audit:
        st.markdown("**Audit trail**")
        st.table(pd.DataFrame([{"Item": k.replace("_", " ").title(),
                                "Value": v} for k, v in audit.items()]))
        basis_panel("Time Impact Analysis", data, [
            "Method: prospective TIA aligned to AACE RP 52R-06 — fragnet "
            "inserted into the current accepted update at the data date",
            "CPM: calendar-exact simplified forward/backward pass run "
            "IDENTICALLY pre- and post-insertion, so the impact DELTA is "
            "method-consistent; calibration vs P6's own forecast "
            "disclosed per run",
            "Statusing: retained logic; remaining durations as stored",
        ])
    reg7 = st.session_state.get(sk.EVENT_REGISTER, {})
    with st.expander(f"Σ Cumulative impact across the register "
                     f"({len(reg7)} event(s))", expanded=False):
        recs = []
        for rec in reg7.values():
            parsed = event_from_dict(rec)
            if parsed and parsed[1]:
                recs.append(parsed)
        if len(recs) < 1:
            st.caption("Save events with fragnets to the register to "
                       "compute the chronological cumulative position.")
        elif st.button(f"Compute cumulative impact ({len(recs)} events, "
                       "date order)", key="tia_cum_go"):
            st.session_state["tia_cum"] = run_cumulative_tia(
                data, chosen, recs)
        cum = st.session_state.get("tia_cum")
        if cum and cum.get("rows"):
            c1, c2 = st.columns(2)
            c1.metric("Cumulative impact",
                      f"{cum['total_delta_days']:+.1f} days"
                      if cum["total_delta_days"] is not None else "—")
            c2.metric("Final completion",
                      f"{cum['completion_final']:%d %b %Y}"
                      if cum.get("completion_final") else "—")
            st.dataframe(pd.DataFrame([{
                "Event": r["event_id"], "Title": r["title"],
                "Date": (f"{r['date_raised']:%Y-%m-%d}"
                         if r["date_raised"] else "—"),
                "Incremental (d)": r["incremental_delta_days"],
                "Completion after": (f"{r['completion_after']:%Y-%m-%d}"
                                     if r["completion_after"] else "—"),
            } for r in cum["rows"]]), width="stretch",
                hide_index=True)
            for w in cum.get("warnings", []):
                st.error(w)
            for w in cum["concurrency"]:
                st.warning(w)
            st.caption(cum["caveat"])

    narrative = ai_narrative_panel(
        f"nar_tia_{event.event_id}",
        lambda tmpl, r=res: build_tia_prompt(r, tmpl),
        "tia", DEFAULT_TEMPLATES["tia"],
        appendix_builder=lambda: tia_appendix(res))
    sc1, sc2 = st.columns(2)
    if sc1.button("💾 Save event + fragnet to register", key="tia_save"):
        st.session_state.setdefault(sk.EVENT_REGISTER, {})[
            event.event_id] = event_to_dict(event, fragnet, res)
        st.success(f"Saved '{event.event_id}'.")
    raw = fetch_raw(chosen)
    if raw is not None:
        try:
            impacted = build_impacted_xer(
                raw.decode("utf-8", errors="replace"), data, fragnet, res)
            st.download_button(
                "⬇️ Impacted programme (.xer) — import to P6 and "
                "reschedule (F9)",
                data=impacted.encode("utf-8"),
                file_name=f"impacted_{event.event_id}_{chosen}",
                mime="application/octet-stream", key="tia_xer_dl",
                help=EXPORT_CAVEAT)
        except (ValueError, KeyError) as exc:
            st.warning(f"Impacted XER not available: {exc}")
    sc2.download_button(
        "⬇️ Download TIA report (Excel)",
        data=build_tia_xlsx(res, narrative, audit=audit),
        file_name=f"tia_{event.event_id}.xlsx",
        mime="application/vnd.openxmlformats-officedocument."
             "spreadsheetml.sheet")
    analysis_submodules("tia")
