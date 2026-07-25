"""Report Assembler."""

from __future__ import annotations

import os

import streamlit as st

import state as sk
from dcma import DCMAConfig, run_all_checks
from dcma.checks import CheckStatus
from dcma.narrative import (
    DEFAULT_TEMPLATE as DCMA_DEFAULT_TEMPLATE, NarrativeError, PROVIDERS,
    build_report_prompt, stream_narrative,
)
from programme import (
    BasisOfAnalysis, ReportSection, SourceFile, analyse_asbuilt_path,
    analyse_float_erosion, analyse_sequence, build_asbuilt_prompt,
    build_assembled_report, build_comparison_prompt,
    build_critical_path_prompt, build_float_erosion_prompt,
    build_inventory_prompt, build_milestone_prompt, build_progress_prompt,
    build_resources_prompt, build_sequence_prompt, build_tia_prompt,
    build_variance_prompt, build_windows_prompt, compute_progress,
    compute_variance_by_mapping, extract_actual_trace,
    extract_resource_loading, propose_sequence_mapping, report_charts,
    task_wbs_assignments, triangulate,
)
from views._shared import (
    _fkey, cached_compare, cached_longest_path, cached_milestone_shifts,
    cached_windows, get_parsed_files, model_selector,
)


def _stored_narrative(exact_or_prefix: str) -> str | None:
    """Fetch an analyst-generated narrative from session state.

    Accepts the exact panel key or a prefix (for keys parameterised by the
    chosen programme). Widget keys carry suffixes and are excluded.
    """
    suffixes = ("_tmpl", "_provider", "_model", "_key", "_go", "_dl")
    if exact_or_prefix in st.session_state:
        v = st.session_state[exact_or_prefix]
        if isinstance(v, str):
            return v
    for k, v in st.session_state.items():
        if (isinstance(k, str) and k.startswith(exact_or_prefix)
                and not k.endswith(suffixes) and isinstance(v, str)):
            return v
    return None


def report_tab() -> None:
    st.caption(
        "Assemble the module analyses into one Word report: narratives you "
        "have generated, key figures, a single aggregated Limitations "
        "section, and a Basis of Analysis appendix (files, hashes, "
        "settings)."
    )
    files = get_parsed_files()
    inv = st.session_state.get(sk.INVENTORY)
    if not files or inv is None:
        st.info("Upload programmes in the **Data Intake** tab first.")
        return

    pool = dict(files)
    base_name = (inv.baseline.file_name if inv.baseline
                 else inv.revisions[0].file_name)
    curr_name = (inv.current.file_name
                 if getattr(inv, "current", None) else
                 inv.revisions[-1].file_name)
    ordered = [(r.file_name, pool[r.file_name]) for r in inv.revisions]
    multi = len(files) >= 2

    c1, c2, c3 = st.columns(3)
    title = c1.text_input("Report title",
                          "Preliminary Delay Analysis Report")
    project = c2.text_input(
        "Project", (pool[base_name].project.short_name
                    if pool[base_name].project else ""))
    author = c3.text_input("Prepared by", "")

    # ---- build candidate sections (deterministic findings + narrative) ---
    def fmt_d(d):
        return f"{d:%d %b %Y}" if d else "—"

    # Each candidate: label, section, settings, canonical narrative key,
    # prompt builder (for batch AI generation), chart builders.
    candidates: list[dict] = []

    # Inventory
    sec = ReportSection("Information Relied Upon")
    span = [r.data_date for r in inv.revisions if r.data_date]
    sec.key_findings = [
        f"{len(inv.revisions)} programme revision(s) received, data dates "
        f"{fmt_d(min(span)) if span else '—'} to "
        f"{fmt_d(max(span)) if span else '—'}.",
        f"Baseline: {base_name}; current: {curr_name}.",
    ]
    sec.caveats = list(inv.missing) + list(inv.warnings)
    candidates.append(dict(
        label="Data inventory", sec=sec, settings=[],
        nar_key="nar_inventory",
        prompt=lambda inv=inv: build_inventory_prompt(inv),
        charts=[]))

    # DCMA on baseline
    results = run_all_checks(pool[base_name], DCMAConfig())
    fails = [r for r in results if r.status == CheckStatus.FAIL]
    passes = [r for r in results if r.status == CheckStatus.PASS]
    sec = ReportSection("Programme Examination (DCMA 14-Point)")
    sec.key_findings = [
        f"Baseline '{base_name}': {len(passes)} of 14 checks passed.",
        "Checks not met: " + ", ".join(f"{r.number} {r.name}"
                                       for r in fails) + "."
        if fails else "All checks met.",
    ]
    candidates.append(dict(
        label="DCMA 14-point", sec=sec,
        settings=[f"DCMA — programme: {base_name}; standard thresholds"],
        nar_key=f"nar_dcma_{base_name}",
        prompt=lambda d=pool[base_name], r=results:
            build_report_prompt(d, r, DCMA_DEFAULT_TEMPLATE),
        charts=[]))

    # Baseline critical path (longest path, default terminal)
    cp = cached_longest_path(_fkey(base_name), base_name, None, 10.0,
                             pool[base_name])
    sec = ReportSection("Baseline Planned Critical Path")
    sec.key_findings = [
        f"Longest path traced backward from {cp.end_choice}: "
        f"{len(cp.critical)} activities, {len(cp.links)} driving links.",
        f"Near-critical band (TF ≤ {cp.near_critical_days:.0f}d): "
        f"{len(cp.near_critical)} activities.",
    ]
    sec.caveats = list(cp.caveats) + list(cp.warnings)
    candidates.append(dict(
        label="Critical path", sec=sec,
        settings=[f"Critical path — method: backward driving-logic trace "
                  f"from {cp.end_choice} (programme: {base_name})"],
        nar_key=f"nar_cp_{base_name}",
        prompt=lambda cp=cp: build_critical_path_prompt(cp),
        charts=[(lambda cp=cp: report_charts.critical_path_chart(cp),
                 "Planned critical path, early-start order")]))

    if multi:
        # Milestones
        ms = cached_milestone_shifts(
            tuple(_fkey(n) for n, _ in ordered),
            [(n, d.project.data_date if d.project else None, d)
             for n, d in ordered])
        tracked = [s for s in ms.series if s.total_shift_days is not None]
        slipped = [s for s in tracked if s.total_shift_days > 7]
        worst = max(tracked, key=lambda s: s.total_shift_days, default=None)
        top_series = sorted(tracked, key=lambda s: -s.total_shift_days)[:10]
        sec = ReportSection("Milestone Slippage")
        sec.key_findings = [
            f"{len(tracked)} milestones tracked across revisions; "
            f"{len(slipped)} slipped by more than 7 days.",
        ]
        if worst:
            sec.key_findings.append(
                f"Largest shift: {worst.key} '{worst.name}' "
                f"({worst.total_shift_days:+.0f} days).")
        sec.caveats = list(ms.warnings)
        candidates.append(dict(
            label="Milestone shifts", sec=sec,
            settings=["Milestones — matched by Activity ID with fuzzy-name "
                      "proposals excluded unless confirmed"],
            nar_key="nar_milestones",
            prompt=lambda ms=ms, ts=top_series:
                build_milestone_prompt(ms, ts),
            charts=[(lambda s=ms.series: report_charts.milestone_chart(s),
                     "Forecast movement of the most-slipped milestones")]))

        # As-planned vs as-recorded (WBS level 1)
        wbs_map_b = task_wbs_assignments(pool[base_name], level=1)
        wbs_map_c = task_wbs_assignments(pool[curr_name], level=1)
        var = compute_variance_by_mapping(
            pool[base_name], pool[curr_name], wbs_map_b, wbs_map_c,
            "WBS level 1")
        worst_g = max((g for g in var.groups
                       if g.finish_delta_days is not None),
                      key=lambda g: g.finish_delta_days, default=None)
        sec = ReportSection("As-Planned vs As-Recorded (by WBS)")
        if worst_g:
            sec.key_findings.append(
                f"Worst group by finish slippage: '{worst_g.code_value}' "
                f"({worst_g.finish_delta_days:+.0f} days).")
        sec.caveats = list(var.caveats) + list(var.warnings)
        candidates.append(dict(
            label="Planned vs recorded", sec=sec,
            settings=[f"Variance — breakdown: WBS level 1; '{base_name}' "
                      f"vs '{curr_name}'"],
            nar_key="nar_variance",
            prompt=lambda var=var: build_variance_prompt(var),
            charts=[(lambda var=var: report_charts.variance_chart(var),
                     "Finish slippage by WBS group")]))

        # Revision comparison (baseline -> current)
        cmp = cached_compare(_fkey(base_name), _fkey(curr_name),
                             base_name, curr_name,
                             pool[base_name], pool[curr_name])
        sec = ReportSection("Programme Revision Comparison")
        sec.key_findings = [
            f"{cmp.total_changes} recorded changes between '{base_name}' "
            f"and '{curr_name}'.",
            f"Scope: {len(cmp.added)} added / {len(cmp.deleted)} deleted; "
            f"logic {len(cmp.logic_added)} added / "
            f"{len(cmp.logic_removed)} removed.",
            f"Actual dates changed retrospectively: "
            f"{len(cmp.actual_date_changes)}.",
        ]
        sec.caveats = list(cmp.caveats) + list(cmp.warnings)
        candidates.append(dict(
            label="Revision comparison", sec=sec,
            settings=[f"Comparison — '{base_name}' vs '{curr_name}', "
                      "matched by Activity ID"],
            nar_key=f"nar_cmp_{base_name}_{curr_name}",
            prompt=lambda cmp=cmp: build_comparison_prompt(cmp),
            charts=[(lambda cmp=cmp: report_charts.comparison_chart(cmp),
                     "Changes by category")]))

        # Windows
        wres = cached_windows(
        (tuple(_fkey(n) for n, _ in ordered),
         st.session_state.get(sk.CONTRACT_MS)), ordered,
        st.session_state.get(sk.CONTRACT_MS))
        sec = ReportSection("Windows / Period Movement")
        if wres.total_movement_days is not None:
            sec.key_findings.append(
                f"Cumulative completion movement "
                f"{wres.total_movement_days:+.0f} days across "
                f"{len(wres.windows)} window(s).")
        sec.caveats = list(wres.caveats) + list(wres.warnings)
        candidates.append(dict(
            label="Windows analysis", sec=sec,
            settings=["Windows — driving path per revision traced from "
                      "its latest finisher"],
            nar_key="nar_windows",
            prompt=lambda wres=wres: build_windows_prompt(wres),
            charts=[
                (lambda w=wres: report_charts.windows_trajectory_chart(w),
                 "Completion trajectory across data dates"),
                (lambda w=wres: report_charts.windows_movement_chart(w),
                 "Completion movement per window")]))

        # S-curve
        updates = [(n, d) for n, d in ordered if n != base_name]
        pr = compute_progress(pool[base_name], base_name, updates)
        sec = ReportSection("Progress S-Curve")
        if pr.recorded_pct_at_dd is not None:
            sec.key_findings.append(
                f"Recorded {pr.recorded_pct_at_dd:.1f}% vs planned "
                f"{pr.planned_pct_at_dd:.1f}% at the latest data date"
                + (f" (≈ {pr.time_offset_days:+.0f} days in time)."
                   if pr.time_offset_days is not None else "."))
        sec.caveats = list(pr.caveats) + list(pr.warnings)
        candidates.append(dict(
            label="Progress S-curve", sec=sec,
            settings=["S-curve — weighting: activity duration; monthly "
                      "buckets"],
            nar_key="nar_progress_duration",
            prompt=lambda pr=pr: build_progress_prompt(pr),
            charts=[(lambda pr=pr: report_charts.scurve_chart(pr),
                     "Planned vs as-recorded cumulative progress")]))

        # Float erosion
        fe = analyse_float_erosion(ordered)
        lasts = fe.snapshots[-1]
        sec = ReportSection("Float Erosion")
        sec.key_findings = [
            f"Latest revision: median float "
            f"{lasts.median_float:+.0f}d, {lasts.negative_count} "
            f"negative-float activities (minimum {lasts.min_float:+.0f}d)."
            if lasts.median_float is not None else
            "Float profile not computable.",
        ]
        sec.caveats = list(fe.caveats) + list(fe.warnings)
        candidates.append(dict(
            label="Float erosion", sec=sec,
            settings=["Float erosion — near-critical threshold 10d"],
            nar_key="nar_float",
            prompt=lambda fe=fe: build_float_erosion_prompt(fe),
            charts=[(lambda fe=fe: report_charts.float_chart(fe),
                     "Float profile by revision")]))

        # As-built critical path (contemporaneous reconstruction + trace)
        ab = analyse_asbuilt_path(ordered)
        ab_trace = extract_actual_trace(ordered, max_gap_days=60.0)
        ab_tri = triangulate(ab, ab_trace)
        sec = ReportSection("As-Built Critical Path")
        sec.key_findings = [
            f"{len(ab.stitched)} activities on the stitched contemporaneous "
            f"path across {len(ab.windows)} window(s); persistent core "
            f"{len(ab.core_codes)} of {len(ab.persistence)} ever-critical "
            "activities.",
        ]
        covs = [w.coverage_pct for w in ab.windows
                if w.coverage_pct is not None]
        if covs:
            sec.key_findings.append(
                f"Driving-work coverage: {min(covs):.0f}%–{max(covs):.0f}% "
                "of each window with forecast-critical work active.")
        if ab_tri.agreement_pct is not None:
            sec.key_findings.append(
                f"Independent actual-date trace: {len(ab_trace.activities)} "
                f"activities; method agreement {ab_tri.agreement_pct:.0f}% "
                f"({len(ab_tri.both)} activities identified by both "
                "reconstructions).")
        sec.caveats = (list(ab.caveats) + list(ab.warnings)
                       + list(ab_trace.caveats) + list(ab_trace.warnings)
                       + list(ab_tri.caveats) + list(ab_tri.warnings))
        candidates.append(dict(
            label="As-built critical path", sec=sec,
            settings=["As-built path — contemporaneous stitching; "
                      "persistent core at ≥50% of eligible revisions; "
                      "actual-date trace with logic-evidenced hand-offs, "
                      "max gap 60d, no temporal fallback"],
            nar_key="nar_asbuilt",
            prompt=lambda ab=ab, tr=ab_trace, tg=ab_tri:
                build_asbuilt_prompt(ab, tr, tg),
            charts=[(lambda ab=ab:
                     report_charts.asbuilt_persistence_chart(ab),
                     "Criticality persistence on actual dates")]))

    # Resources (baseline)
    rl = extract_resource_loading(pool[base_name], base_name)
    if rl.histogram:
        sec = ReportSection("Planned Resource Loading")
        top = rl.resources[0]
        sec.key_findings = [
            f"{len(rl.resources)} resources with planned loading; largest: "
            f"{top.short_name} [{top.rsrc_type}] "
            f"({top.total_qty:,.0f} across {top.assignment_count} "
            "assignments).",
        ]
        sec.caveats = list(rl.caveats) + list(rl.warnings)
        candidates.append(dict(
            label="Resource loading", sec=sec,
            settings=[f"Resources — programme: {base_name}; planned "
                      "quantities spread across scheduled dates"],
            nar_key=f"nar_res_{base_name}",
            prompt=lambda rl=rl: build_resources_prompt(rl),
            charts=[(lambda rl=rl: report_charts.resources_chart(rl),
                     "Planned resource loading by month")]))

    # Time Impact Analysis (when a run exists this session)
    tia_res = st.session_state.get("tia_result")
    if tia_res is not None and tia_res.completion_delta_days is not None:
        e_t = tia_res.event
        sec = ReportSection("Time Impact Analysis (Prospective)")
        sec.key_findings = [
            f"Event {e_t.event_id}: {e_t.title} — forecast impact "
            f"{tia_res.completion_delta_days:+.1f} days on completion "
            f"({tia_res.completion_pre:%d %b %Y} → "
            f"{tia_res.completion_post:%d %b %Y})."
            if tia_res.completion_pre and tia_res.completion_post else
            f"Event {e_t.event_id}: {e_t.title}.",
            f"Fragnet: {len(tia_res.fragnet)} activities; calibration vs "
            f"P6 {tia_res.calibration_days:+.1f} days."
            if tia_res.calibration_days is not None else
            f"Fragnet: {len(tia_res.fragnet)} activities.",
        ]
        hit = [m for m in tia_res.milestone_impacts
               if (m.delta_days or 0) > 0][:3]
        if hit:
            sec.key_findings.append(
                "Most affected milestones: "
                + "; ".join(f"{m.code} {m.delta_days:+.0f}d"
                            for m in hit) + ".")
        cum_t = st.session_state.get("tia_cum")
        if cum_t and cum_t.get("total_delta_days") is not None:
            sec.key_findings.append(
                f"Cumulative register position: "
                f"{cum_t['total_delta_days']:+.1f} days across "
                f"{len(cum_t['rows'])} events.")
        sec.caveats = list(tia_res.caveats) + list(tia_res.warnings)
        audit_t = st.session_state.get("tia_audit", {})
        candidates.append(dict(
            label="Time impact analysis", sec=sec,
            settings=[
                "TIA — "
                + (audit_t.get("method")
                   or "simplified CPM per AACE RP 52R-06")
                + f"; source {audit_t.get('source_file', '?')} sha256 "
                + str(audit_t.get("source_sha256", ""))[:16]],
            nar_key=f"nar_tia_{e_t.event_id}",
            prompt=lambda r=tia_res: build_tia_prompt(r),
            charts=[(lambda r=tia_res: report_charts.tia_paths_chart(r),
                     "Driving paths, pre vs post impact")]))

    # Sequence coding (latest revision; analyst-confirmed mapping if any)
    seq_prop = st.session_state.get(f"seq_rows_{curr_name}")
    seq_confirmed = st.session_state.get(f"seq_rows_{curr_name}_confirmed",
                                         False)
    if seq_prop is None:
        seq_prop = propose_sequence_mapping(pool[curr_name], curr_name)
    seqr = analyse_sequence(seq_prop.rows, curr_name,
                            mapping_confirmed=seq_confirmed)
    if seqr.bands:
        sec = ReportSection("Construction Sequence (Analyst Coding)")
        sec.key_findings = [
            f"{seqr.mapped_activities} actualised activities coded into "
            f"{len(seq_prop.fronts)} work fronts × construction stages "
            f"(mapping {'analyst-confirmed' if seq_confirmed else 'auto-proposed'}).",
        ]
        if seqr.fronts_by_finish:
            tops = [f for f, fin in seqr.fronts_by_finish[:3] if fin]
            sec.key_findings.append(
                "Last-finishing fronts as recorded: " + ", ".join(tops)
                + ".")
        sec.caveats = list(seqr.caveats) + list(seqr.warnings)
        candidates.append(dict(
            label="Sequence coding", sec=sec,
            settings=[f"Sequence coding — programme: {curr_name}; mapping "
                      f"{'confirmed by analyst' if seq_confirmed else 'auto-proposed'} "
                      "(full mapping disclosed in the module workbook)"],
            nar_key=f"nar_seq_{curr_name}",
            prompt=lambda s=seqr: build_sequence_prompt(s),
            charts=[(lambda s=seqr:
                     report_charts.sequence_matrix_chart(s),
                     "Construction sequence by work front (actual dates)")]))

    # Attach any narrative already generated (here or in the module tabs).
    # Parameterised panels (per-programme keys) also match by prefix.
    prefix_fallbacks = {"nar_dcma_", "nar_cp_", "nar_cmp_",
                        "nar_progress_", "nar_res_"}
    for c in candidates:
        nar = _stored_narrative(c["nar_key"])
        if nar is None:
            pref = next((p for p in prefix_fallbacks
                         if c["nar_key"].startswith(p)), None)
            if pref:
                nar = _stored_narrative(pref)
        c["sec"].narrative_md = nar

    # ---- selection UI -----------------------------------------------------
    st.subheader("Sections to include")
    selected: list[dict] = []
    cols = st.columns(3)
    for i, c in enumerate(candidates):
        has_nar = c["sec"].narrative_md is not None
        tick = cols[i % 3].checkbox(
            f"{c['label']} {'📝' if has_nar else '▫️'}",
            value=True, key=f"rep_inc_{c['label']}",
            help=("AI narrative available — will be included in full."
                  if has_nar else
                  "No narrative yet — generate below, or in the module's "
                  "tab; otherwise key figures only."))
        if tick:
            selected.append(c)
    st.caption("📝 = AI narrative available · ▫️ = key figures only")

    if not selected:
        st.warning("Select at least one section.")
        return

    # ---- batch AI narrative generation ------------------------------------
    missing = [c for c in selected if c["sec"].narrative_md is None]
    with st.expander(
        f"🤖 Generate AI narratives for the report "
        f"({len(missing)} section(s) without one)",
        expanded=bool(missing),
    ):
        pcol1, pcol2 = st.columns(2)
        provider = pcol1.selectbox(
            "AI provider", options=list(PROVIDERS.keys()),
            format_func=lambda p: PROVIDERS[p]["label"], key="rep_provider")
        pinfo = PROVIDERS[provider]
        model = model_selector(pcol2, pinfo, f"rep_{provider}")
        env_key = os.environ.get(pinfo["env_var"], "")
        if provider == "gemini" and not env_key:
            env_key = os.environ.get("GOOGLE_API_KEY", "")
        api_key = st.text_input(f"{pinfo['label']} API key", type="password",
                                value=env_key, key="rep_key")
        regen = st.checkbox("Regenerate sections that already have a "
                            "narrative", value=False, key="rep_regen")
        targets = selected if regen else missing
        if st.button(f"Generate {len(targets)} narrative(s)",
                     type="primary", disabled=not api_key or not targets,
                     key="rep_generate"):
            prog = st.progress(0.0)
            status = st.empty()
            failures = []
            for j, c in enumerate(targets):
                status.write(f"Drafting: **{c['label']}** …")
                try:
                    text = "".join(stream_narrative(
                        provider, api_key, c["prompt"](), model or None))
                    st.session_state[c["nar_key"]] = text
                except NarrativeError as exc:
                    failures.append(f"{c['label']}: {exc.message}")
                prog.progress((j + 1) / len(targets))
            status.empty()
            if failures:
                st.error("Some narratives failed — " + "; ".join(failures))
            else:
                st.rerun()

    # ---- assemble ----------------------------------------------------------
    include_charts = st.toggle("Embed module charts in the report",
                               value=True, key="rep_charts")

    hashes = st.session_state.get(sk.XER_HASHES, {})
    basis = BasisOfAnalysis(
        files=[SourceFile(
            file_name=r.file_name,
            sha256=hashes.get(r.file_name, "not recorded"),
            data_date=r.data_date,
            role=("Baseline" if r.is_baseline
                  else "Current" if r.is_current else "Update"),
            activity_count=r.activity_count,
        ) for r in inv.revisions],
        settings=[s for c in selected for s in c["settings"]]
        + [f"{m} — {s}"
           for m, lines in sorted(
               st.session_state.get(sk.ANALYSIS_BASIS, {}).items())
           for s in lines],
    )

    n_narr = sum(1 for c in selected if c["sec"].narrative_md)
    st.markdown(
        f"**{len(selected)}** sections selected — **{n_narr}** with AI "
        f"narratives, {len(selected) - n_narr} figures-only."
    )
    if st.button("🛠️ Assemble report", type="primary", key="rep_build"):
        with st.spinner("Rendering charts and assembling the document..."):
            sections = []
            for c in selected:
                sec = c["sec"]
                sec.images = []
                if include_charts:
                    for chart_fn, caption in c["charts"]:
                        try:
                            chart = chart_fn()
                            if chart is not None:
                                sec.images.append(
                                    (report_charts.chart_png(chart), caption))
                        except Exception as exc:  # noqa: BLE001
                            st.warning(f"Chart skipped for {c['label']}: "
                                       f"{exc}")
                sections.append(sec)
            st.session_state["rep_docx"] = build_assembled_report(
                title, project, author, sections, basis)
    if "rep_docx" in st.session_state:
        st.download_button(
            "⬇️ Download report (Word)",
            data=st.session_state["rep_docx"],
            file_name="preliminary_delay_analysis_report.docx",
            mime=("application/vnd.openxmlformats-officedocument."
                  "wordprocessingml.document"),
        )
