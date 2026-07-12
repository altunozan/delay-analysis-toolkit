"""Forensic Programme Analysis — Streamlit UI.

One tab per module, all fed from a single multi-XER intake:

    1. Data Intake & Inventory   (Module 0)
    2. DCMA 14-Point             (Module 1 — schedule health, per revision)
    3. Milestone Shift Tracker   (Module 3)
    4. As-Planned vs As-Recorded (Module 4 — by activity code or WBS level)

Every module offers an Excel export and an AI narrative (Claude / ChatGPT /
Gemini) generated strictly from the deterministic results.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import hashlib
import io
import os

import altair as alt
import pandas as pd
import streamlit as st

from dcma import DCMAConfig, parse_xer, run_all_checks
from dcma.checks import CheckStatus
from dcma.config import (
    HARD_CONSTRAINT_CODES_EXTENDED,
    HARD_CONSTRAINT_CODES_STRICT,
)
from dcma.narrative import (
    DEFAULT_TEMPLATE as DCMA_DEFAULT_TEMPLATE,
    PROVIDERS,
    NarrativeError,
    build_report_prompt,
    stream_narrative,
)
from programme import report_charts
from programme.narrative import DEFAULT_TEMPLATES
from dcma.report_xlsx import build_xlsx_report
from programme.variance import DIMENSION_SEPARATOR
from programme import (
    activity_code_types,
    BasisOfAnalysis,
    ReportSection,
    SourceFile,
    WEIGHT_OPTIONS,
    analyse_float_erosion,
    analyse_windows,
    build_assembled_report,
    build_comparison_prompt,
    build_float_erosion_prompt,
    build_float_erosion_xlsx,
    build_progress_prompt,
    build_progress_xlsx,
    build_resources_prompt,
    build_resources_xlsx,
    compute_progress,
    extract_resource_loading,
    build_comparison_xlsx,
    build_critical_path_prompt,
    build_critical_path_xlsx,
    build_windows_prompt,
    build_windows_xlsx,
    compare_revisions,
    build_inventory,
    combine_mappings,
    end_activity_candidates,
    extract_critical_path,
    extract_longest_path,
    build_inventory_prompt,
    build_inventory_xlsx,
    build_milestone_prompt,
    build_milestone_xlsx,
    build_variance_prompt,
    build_variance_xlsx,
    compute_variance_by_mapping,
    max_wbs_depth,
    task_code_assignments,
    task_wbs_assignments,
    track_milestone_shifts,
)

st.set_page_config(
    page_title="Forensic Programme Analysis",
    page_icon="📊",
    layout="wide",
)

STATUS_COLORS = {
    CheckStatus.PASS: "#1a7f37",
    CheckStatus.FAIL: "#cf222e",
    CheckStatus.NA: "#6e7781",
}
STATUS_BG = {
    CheckStatus.PASS: "#e6f4ea",
    CheckStatus.FAIL: "#fbe9e7",
    CheckStatus.NA: "#f0f1f3",
}

PLANNED_COLOR = "#4c78a8"
RECORDED_COLOR = "#e45756"
SLIP_COLOR = "#cf222e"
GAIN_COLOR = "#1a7f37"


# ====================================================================== #
# Shared helpers
# ====================================================================== #

def get_parsed_files() -> list[tuple[str, object]]:
    """Parsed XER pool from the intake tab (cached in session state)."""
    return st.session_state.get("xer_pool", [])


def ai_narrative_panel(
    state_key: str,
    prompt_builder,
    file_stub: str,
    default_template: str,
) -> str | None:
    """Provider/model/key picker + streaming narrative, shared by all modules.

    ``prompt_builder`` is called with the (possibly analyst-edited) report
    template at generation time. The objectivity rules are baked into the
    prompt separately and cannot be edited here — only the section structure.
    Returns the generated narrative (persisted in session state) or None.
    """
    with st.expander("🤖 AI Narrative Report", expanded=False):
        template = st.text_area(
            "Report section template (editable)",
            value=default_template,
            height=220,
            key=f"{state_key}_tmpl",
            help="Defines the headings and what each section should cover. "
                 "The objectivity rules (only supplied figures, no blame, "
                 "reproduce all caveats) are fixed and applied regardless.",
        )
        pcol1, pcol2 = st.columns(2)
        provider = pcol1.selectbox(
            "AI provider",
            options=list(PROVIDERS.keys()),
            format_func=lambda p: PROVIDERS[p]["label"],
            key=f"{state_key}_provider",
        )
        pinfo = PROVIDERS[provider]
        model = pcol2.text_input(
            "Model",
            value=pinfo["default_model"],
            help="Override with any model ID available to your key.",
            key=f"{state_key}_model",
        )
        env_key = os.environ.get(pinfo["env_var"], "")
        if provider == "gemini" and not env_key:
            env_key = os.environ.get("GOOGLE_API_KEY", "")
        api_key = st.text_input(
            f"{pinfo['label']} API key",
            type="password",
            value=env_key,
            help=f"Get a key at {pinfo['key_hint']}. Used only for this "
                 "request; never stored.",
            key=f"{state_key}_key",
        )

        if st.button("Generate narrative", type="primary",
                     disabled=not api_key, key=f"{state_key}_go"):
            prompt = prompt_builder(template or default_template)
            try:
                with st.spinner("Drafting narrative from the results..."):
                    text = st.write_stream(
                        stream_narrative(provider, api_key, prompt, model or None)
                    )
                st.session_state[state_key] = text
            except NarrativeError as exc:
                st.error(exc.message)
        elif state_key in st.session_state:
            st.markdown(st.session_state[state_key])

        narrative = st.session_state.get(state_key)
        if narrative:
            st.download_button(
                "Download narrative (Markdown)",
                data=narrative,
                file_name=f"{file_stub}_narrative.md",
                mime="text/markdown",
                key=f"{state_key}_dl",
            )
    return st.session_state.get(state_key)


# ====================================================================== #
# Tab 1 — Data Intake & Inventory (Module 0)
# ====================================================================== #

def intake_tab() -> None:
    st.caption(
        "Upload every programme revision once — all modules read from this "
        "pool. The inventory below is the report's data front-matter."
    )
    uploads = st.file_uploader(
        "Primavera P6 XER files (baseline + updates)",
        type=["xer"],
        accept_multiple_files=True,
        key="intake_uploads",
    )

    sample_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample")
    sample_paths = sorted(
        os.path.join(sample_dir, f) for f in os.listdir(sample_dir)
        if f.lower().endswith(".xer")
    ) if os.path.isdir(sample_dir) else []
    use_samples = False
    if not uploads and sample_paths:
        use_samples = st.toggle(
            f"Use bundled sample programmes ({len(sample_paths)} files)",
            value=False,
            help="Loads the .xer files shipped in the sample/ folder.",
        )

    if use_samples:
        sources = [(os.path.basename(p), p, os.path.getsize(p))
                   for p in sample_paths]
    else:
        sources = [(u.name, u, u.size) for u in uploads or []]

    signature = tuple(sorted((name, size) for name, _, size in sources))
    if signature != st.session_state.get("xer_pool_sig"):
        files = []
        hashes: dict[str, str] = {}
        for name, src, _ in sources:
            try:
                if isinstance(src, str):
                    with open(src, "rb") as fh:
                        raw = fh.read()
                else:
                    raw = src.getvalue()
                hashes[name] = hashlib.sha256(raw).hexdigest()
                data = parse_xer(raw, DCMAConfig())
            except Exception as exc:  # noqa: BLE001 - surface per-file errors
                st.warning(f"Skipped '{name}': {exc}")
                continue
            if not data.tasks:
                st.warning(f"Skipped '{name}': no TASK table found.")
                continue
            files.append((name, data))
        st.session_state["xer_pool"] = files
        st.session_state["xer_hashes"] = hashes
        st.session_state["xer_pool_sig"] = signature
        # New data invalidates cached narratives.
        for key in list(st.session_state):
            if key.startswith("nar_"):
                del st.session_state[key]

    files = get_parsed_files()
    if not files:
        st.info("Upload at least one .xer file to begin. Two or more enable "
                "the shift and variance modules.")
        return

    names = [n for n, _ in files]
    baseline_choice = st.selectbox(
        "Contract baseline",
        options=["(auto: earliest data date)"] + names,
        help="Which revision is the contract baseline? Auto picks the "
             "earliest data date.",
    )
    baseline_file = (None if baseline_choice.startswith("(auto")
                     else baseline_choice)

    inv = build_inventory(files, baseline_file=baseline_file)
    st.session_state["inventory"] = inv

    st.subheader("Data Inventory")
    inv_df = pd.DataFrame([
        {
            "File": r.file_name,
            "Project": r.project_short_name or "—",
            "Data date": r.data_date.strftime("%Y-%m-%d") if r.data_date else "—",
            "Role": ("Baseline" if r.is_baseline
                     else "Current" if r.is_current else "Update"),
            "Activities": r.activity_count,
            "Relationships": r.relationship_count,
            "Milestones": r.milestone_count,
            "Activity codes": "Yes" if r.has_activity_codes else "No",
        }
        for r in inv.revisions
    ])
    st.dataframe(inv_df, use_container_width=True, hide_index=True)

    for w in inv.warnings:
        st.info(w)
    if inv.missing:
        with st.expander("Missing inputs (become report caveats)"):
            for m in inv.missing:
                st.write("•", m)

    narrative = ai_narrative_panel(
        "nar_inventory",
        lambda tmpl: build_inventory_prompt(inv, tmpl),
        "data_inventory",
        DEFAULT_TEMPLATES["inventory"],
    )
    st.download_button(
        "⬇️ Download inventory (Excel)",
        data=build_inventory_xlsx(inv, narrative),
        file_name="data_inventory.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ====================================================================== #
# Tab 2 — DCMA 14-Point (Module 1)
# ====================================================================== #

def dcma_config_panel() -> DCMAConfig:
    """Standard thresholds by default; an option opens the full editor."""
    cfg = DCMAConfig()
    customise = st.toggle(
        "Revise DCMA thresholds",
        value=False,
        help="Off = standard DCMA 14-Point targets. On = edit any threshold.",
    )
    if not customise:
        return cfg

    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**Logic & Relationships**")
            cfg.logic_max_pct = st.number_input(
                "1 · Max missing-logic %", 0.0, 100.0, cfg.logic_max_pct, 0.5)
            cfg.leads_max_count = st.number_input(
                "2 · Max leads (count)", 0, 1000, cfg.leads_max_count, 1)
            cfg.lags_max_pct = st.number_input(
                "3 · Max lags %", 0.0, 100.0, cfg.lags_max_pct, 0.5)
            cfg.fs_min_pct = st.number_input(
                "4 · Min Finish-to-Start %", 0.0, 100.0, cfg.fs_min_pct, 1.0)
            cfg.default_hours_per_day = st.number_input(
                "Fallback hours/day", 1.0, 24.0, cfg.default_hours_per_day, 0.5)
        with c2:
            st.markdown("**Constraints & Float**")
            strict = st.checkbox(
                "Strict hard-constraint set (Mandatory only)", value=False,
                help="Off = also counts 'On or Before' constraints.")
            cfg.hard_constraint_codes = set(
                HARD_CONSTRAINT_CODES_STRICT if strict
                else HARD_CONSTRAINT_CODES_EXTENDED)
            cfg.hard_constraint_max_pct = st.number_input(
                "5 · Max hard-constraint %", 0.0, 100.0,
                cfg.hard_constraint_max_pct, 0.5)
            cfg.high_float_days = st.number_input(
                "6 · High float threshold (days)", 1.0, 365.0,
                cfg.high_float_days, 1.0)
            cfg.high_float_max_pct = st.number_input(
                "6 · Max high-float %", 0.0, 100.0, cfg.high_float_max_pct, 0.5)
            cfg.negative_float_max_count = st.number_input(
                "7 · Max negative-float (count)", 0, 1000,
                cfg.negative_float_max_count, 1)
        with c3:
            st.markdown("**Duration, Dates & Execution**")
            cfg.high_duration_days = st.number_input(
                "8 · High duration threshold (days)", 1.0, 365.0,
                cfg.high_duration_days, 1.0)
            cfg.high_duration_max_pct = st.number_input(
                "8 · Max high-duration %", 0.0, 100.0,
                cfg.high_duration_max_pct, 0.5)
            cfg.missed_tasks_max_pct = st.number_input(
                "11 · Max missed-tasks %", 0.0, 100.0,
                cfg.missed_tasks_max_pct, 0.5)
            cfg.cpli_min = st.number_input(
                "13 · Min CPLI", 0.0, 5.0, cfg.cpli_min, 0.01)
            cfg.bei_min = st.number_input(
                "14 · Min BEI", 0.0, 5.0, cfg.bei_min, 0.01)
    return cfg


def scorecard(results) -> None:
    passed = sum(1 for r in results if r.status == CheckStatus.PASS)
    failed = sum(1 for r in results if r.status == CheckStatus.FAIL)
    na = sum(1 for r in results if r.status == CheckStatus.NA)
    scored = passed + failed
    score_pct = (passed / scored * 100.0) if scored else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Checks Passed", f"{passed}/14")
    c2.metric("Checks Failed", failed)
    c3.metric("Not Applicable", na)
    c4.metric("Score (of scored)", f"{score_pct:.0f}%")

    st.divider()

    cols = st.columns(2)
    for i, r in enumerate(results):
        col = cols[i % 2]
        color = STATUS_COLORS[r.status]
        bg = STATUS_BG[r.status]
        col.markdown(
            f"""
            <div style="border-left:5px solid {color};background:{bg};
                        padding:10px 14px;border-radius:6px;margin-bottom:8px;">
              <div style="display:flex;justify-content:space-between;align-items:center;">
                <strong>Check {r.number}: {r.name}</strong>
                <span style="color:{color};font-weight:700;">{r.status.value}</span>
              </div>
              <div style="font-size:0.9em;color:#444;margin-top:4px;">
                {r.metric_label}: <strong>{r.metric_value}</strong>
                &nbsp;·&nbsp; Target {r.threshold}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def detail_section(results) -> None:
    st.subheader("Check Details")
    for r in results:
        icon = {"PASS": "🟢", "FAIL": "🔴", "N/A": "⚪"}[r.status.value]
        with st.expander(f"{icon} Check {r.number}: {r.name} — {r.status.value}"):
            st.write(r.summary)
            st.caption(f"Metric: {r.metric_value}  ·  Target: {r.threshold}")
            if r.na_reason:
                st.info(r.na_reason)
            if r.detail_rows:
                df = pd.DataFrame(r.detail_rows)
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.caption(f"{len(df)} affected item(s).")
            elif r.affected_ids:
                st.write(", ".join(r.affected_ids[:200]))


def build_summary_df(results) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Check #": r.number,
            "Check Name": r.name,
            "Status": r.status.value,
            "Metric": r.metric_label,
            "Value": r.metric_value,
            "Threshold": r.threshold,
            "Affected Count": r.affected_count,
            "Summary": r.summary,
        }
        for r in results
    ])


def dcma_tab() -> None:
    st.caption(
        "Schedule health check — establishes whether each programme is a "
        "reliable analytical instrument before any delay conclusions."
    )
    files = get_parsed_files()
    if not files:
        st.info("Upload programmes in the **Data Intake** tab first.")
        return

    names = [n for n, _ in files]
    chosen = st.selectbox("Programme to assess", names, key="dcma_file")
    data = dict(files)[chosen]

    cfg = dcma_config_panel()

    proj = data.project
    pc1, pc2, pc3, pc4 = st.columns(4)
    pc1.metric("Project", proj.short_name if proj else "—")
    pc2.metric("Activities", f"{len(data.tasks):,}")
    pc3.metric("Relationships", f"{len(data.relationships):,}")
    pc4.metric("Data date",
               f"{proj.data_date:%Y-%m-%d}" if proj and proj.data_date else "—")

    results = run_all_checks(data, cfg)

    st.header("Scorecard")
    scorecard(results)
    st.divider()
    detail_section(results)

    st.divider()
    narrative = ai_narrative_panel(
        f"nar_dcma_{chosen}",
        lambda tmpl: build_report_prompt(data, results, tmpl),
        f"dcma_{proj.short_name if proj else 'project'}",
        DCMA_DEFAULT_TEMPLATE,
    )

    st.subheader("Export")
    col1, col2 = st.columns(2)
    col1.download_button(
        "⬇️ Excel report (.xlsx)",
        data=build_xlsx_report(data, results, narrative=narrative),
        file_name=f"dcma_report_{proj.short_name if proj else 'project'}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    csv_buf = io.StringIO()
    build_summary_df(results).to_csv(csv_buf, index=False)
    col2.download_button(
        "⬇️ Results (CSV)",
        data=csv_buf.getvalue(),
        file_name=f"dcma_assessment_{proj.short_name if proj else 'project'}.csv",
        mime="text/csv",
    )


# ====================================================================== #
# Tab 3 — Milestone Shift Tracker (Module 3)
# ====================================================================== #

def milestone_tab() -> None:
    st.caption(
        "How milestone forecasts drifted as the project progressed. "
        "X-axis = revision data date; a rising line = slippage."
    )
    files = get_parsed_files()
    inv = st.session_state.get("inventory")
    if not files or inv is None:
        st.info("Upload programmes in the **Data Intake** tab first.")
        return

    data_by_name = dict(files)
    revs = [(r.label, r.data_date, data_by_name[r.file_name])
            for r in inv.revisions if r.data_date is not None]
    if len(revs) < 2:
        st.info("Need at least two revisions with data dates to track shifts.")
        return

    result = track_milestone_shifts(revs)
    tracked = [s for s in result.series
               if len({p.data_date for p in s.points}) > 1
               and s.total_shift_days is not None]
    if not tracked:
        st.warning("No milestone could be matched across two or more revisions.")
        return

    if result.needs_confirmation:
        with st.expander(
            f"⚠️ {len(result.needs_confirmation)} possible renamed/re-IDed "
            "milestone(s) — confirm before trusting"
        ):
            for m in result.needs_confirmation:
                st.write(
                    f"• `{m.task_code}` \"{m.task_name}\" may be the same as "
                    f"`{m.matched_to_key}` \"{m.matched_to_name}\" "
                    f"(name similarity {m.similarity:.0%})"
                )

    by_slip = sorted(tracked, key=lambda s: abs(s.total_shift_days), reverse=True)

    view = st.radio(
        "View",
        ["Top slipping milestones", "Single milestone"],
        horizontal=True,
        key="ms_view",
    )
    if view == "Top slipping milestones":
        top_n = st.slider("How many milestones", 3, min(25, len(by_slip)),
                          min(10, len(by_slip)))
        selected = by_slip[:top_n]
    else:
        labels = {
            s.key: f"{s.key} — {s.name}  ({s.total_shift_days:+.0f}d"
                   f"{', achieved' if s.is_achieved else ''})"
            for s in by_slip
        }
        pick = st.selectbox(
            "Milestone",
            options=[s.key for s in by_slip],
            format_func=lambda k: labels[k],
            key="ms_pick",
        )
        selected = [s for s in by_slip if s.key == pick]

    rows = []
    for s in selected:
        for p in s.points:
            if p.value_date is None:
                continue
            rows.append({
                "Milestone": f"{s.key} · {s.name[:45]}",
                "Data date": p.data_date,
                "Milestone date": p.value_date,
                "Status": "Actual" if p.is_actual else "Forecast",
                "Shift (days)": round(s.total_shift_days, 1),
            })
    chart_df = pd.DataFrame(rows)

    line = (
        alt.Chart(chart_df)
        .mark_line(strokeWidth=2.5, interpolate="monotone")
        .encode(
            x=alt.X("Data date:T", title="Revision data date",
                    axis=alt.Axis(format="%b %Y", labelAngle=-30, grid=True)),
            y=alt.Y("Milestone date:T", title="Forecast / actual milestone date",
                    scale=alt.Scale(zero=False),
                    axis=alt.Axis(format="%b %Y", grid=True)),
            color=alt.Color("Milestone:N",
                            legend=alt.Legend(orient="bottom", columns=2,
                                              labelLimit=380, title=None)),
        )
    )
    points = (
        alt.Chart(chart_df)
        .mark_point(size=110, filled=True)
        .encode(
            x="Data date:T",
            y="Milestone date:T",
            color=alt.Color("Milestone:N", legend=None),
            shape=alt.Shape(
                "Status:N",
                scale=alt.Scale(domain=["Forecast", "Actual"],
                                range=["circle", "diamond"]),
                legend=alt.Legend(orient="top", title=None),
            ),
            tooltip=[
                alt.Tooltip("Milestone:N"),
                alt.Tooltip("Data date:T", format="%d %b %Y"),
                alt.Tooltip("Milestone date:T", format="%d %b %Y"),
                alt.Tooltip("Status:N"),
                alt.Tooltip("Shift (days):Q", format="+.0f"),
            ],
        )
    )
    st.altair_chart(
        (line + points).properties(height=420).interactive(),
        use_container_width=True,
    )
    st.caption("◆ = achieved (actual date) · ● = forecast. Positive shift = "
               "milestone moved later.")

    st.subheader("Shift summary")
    summary = pd.DataFrame([
        {
            "Activity ID": s.key,
            "Milestone": s.name,
            "First forecast": s.first_value.strftime("%Y-%m-%d") if s.first_value else "—",
            "Latest": s.last_value.strftime("%Y-%m-%d") if s.last_value else "—",
            "Total shift (days)": round(s.total_shift_days, 1),
            "Achieved": "Yes" if s.is_achieved else "No",
        }
        for s in by_slip
    ])
    st.dataframe(summary, use_container_width=True, hide_index=True, height=320)

    narrative = ai_narrative_panel(
        "nar_milestones",
        lambda tmpl: build_milestone_prompt(result, selected, tmpl),
        "milestone_shifts",
        DEFAULT_TEMPLATES["milestones"],
    )
    st.download_button(
        "⬇️ Download milestone report (Excel)",
        data=build_milestone_xlsx(result, by_slip, narrative),
        file_name="milestone_shift_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ====================================================================== #
# Tab 4 — As-Planned vs As-Recorded (Module 4)
# ====================================================================== #

def variance_tab() -> None:
    st.caption(
        "Screening view of where slippage clusters: the programme re-broken "
        "down by activity code or WBS level, planned vs recorded bands per "
        "group. Preliminary and indicative only."
    )
    files = get_parsed_files()
    inv = st.session_state.get("inventory")
    if not files or inv is None:
        st.info("Upload programmes in the **Data Intake** tab first.")
        return
    if len(files) < 2:
        st.info("Need at least two programmes (baseline + update).")
        return

    data_by_name = dict(files)
    names = [r.file_name for r in inv.revisions]
    default_base = inv.baseline.file_name if inv.baseline else names[0]
    default_cur = inv.current.file_name if inv.current else names[-1]

    c1, c2 = st.columns(2)
    base_name = c1.selectbox("Baseline (as-planned)", names,
                             index=names.index(default_base))
    cur_name = c2.selectbox("Current (as-recorded)", names,
                            index=names.index(default_cur))
    if base_name == cur_name:
        st.info("Choose two different programmes.")
        return

    base_data = data_by_name[base_name]
    cur_data = data_by_name[cur_name]

    # Breakdown dimensions: any mix of activity codes and WBS levels, up to 4,
    # combined in the order selected (e.g. "Zone A › Structure › Level 03").
    options: list[tuple[str, str]] = []  # (kind:id, label)
    for t in activity_code_types(base_data):
        options.append((f"code:{t.type_id}",
                        f"Activity code — {t.name} ({t.assigned_task_count} acts)"))
    depth = min(max_wbs_depth(base_data), max_wbs_depth(cur_data))
    for lvl in range(1, min(depth, 4) + 1):
        options.append((f"wbs:{lvl}", f"WBS Level {lvl}"))
    if not options:
        st.warning("Neither activity codes nor a WBS exist in these files — "
                   "no breakdown dimension available.")
        return

    dim_keys = st.multiselect(
        "Breakdown dimension(s) — combined in the order selected, max 4",
        options=[k for k, _ in options],
        default=[options[0][0]],
        format_func=lambda k: dict(options)[k],
        max_selections=4,
        key="var_dims",
        help="One dimension gives a flat breakdown; several nest, e.g. "
             "an Area code combined with WBS Level 2.",
    )
    if not dim_keys:
        st.info("Select at least one breakdown dimension.")
        return

    def _maps_for(key: str) -> tuple[str, dict, dict]:
        kind, _, ident = key.partition(":")
        if kind == "code":
            name = next(t.name for t in activity_code_types(base_data)
                        if t.type_id == ident)
            return (name,
                    task_code_assignments(base_data, ident),
                    task_code_assignments(cur_data, ident))
        lvl = int(ident)
        return (f"WBS L{lvl}",
                task_wbs_assignments(base_data, lvl),
                task_wbs_assignments(cur_data, lvl))

    names_maps = [_maps_for(k) for k in dim_keys]
    dim_name = " › ".join(n for n, _, _ in names_maps)
    base_map = combine_mappings([bm for _, bm, _ in names_maps])
    cur_map = combine_mappings([cm for _, _, cm in names_maps])

    var = compute_variance_by_mapping(base_data, cur_data, base_map, cur_map,
                                      dim_name)
    if len(var.groups) > 80:
        st.warning(
            f"{len(var.groups)} groups — this combination is too granular to "
            "read as a screening view. Consider fewer/coarser dimensions."
        )
    plotted = [g for g in var.groups if g.in_both]

    # With combined dimensions, colour everything by the FIRST (outermost)
    # dimension so sibling groups share a hue.
    multi_dim = len(names_maps) > 1
    first_dim_name = names_maps[0][0]

    def _first_part(label: str) -> str:
        return label.split(DIMENSION_SEPARATOR)[0]

    # --- Finish-slippage bar chart: instantly shows where delay clusters ---
    delta_rows = [
        {
            "Group": g.code_value,
            "Δ finish (days)": round(g.finish_delta_days, 1),
            first_dim_name: _first_part(g.code_value),
        }
        for g in plotted if g.finish_delta_days is not None
    ]
    if delta_rows:
        st.subheader("Finish slippage by group")
        delta_df = pd.DataFrame(delta_rows).sort_values(
            "Δ finish (days)", ascending=False)
        if multi_dim:
            bar_color = alt.Color(
                f"{first_dim_name}:N",
                scale=alt.Scale(scheme="tableau10"),
                legend=alt.Legend(orient="top", title=first_dim_name,
                                  labelLimit=300),
            )
            tooltip = [first_dim_name, "Group",
                       alt.Tooltip("Δ finish (days):Q", format="+.0f")]
        else:
            bar_color = alt.condition(
                alt.datum["Δ finish (days)"] > 0,
                alt.value(SLIP_COLOR), alt.value(GAIN_COLOR))
            tooltip = ["Group", alt.Tooltip("Δ finish (days):Q", format="+.0f")]
        bar = (
            alt.Chart(delta_df)
            .mark_bar(cornerRadiusEnd=3)
            .encode(
                x=alt.X("Δ finish (days):Q", title="Finish delta (days) — "
                        "positive = later than planned"),
                y=alt.Y("Group:N", sort="-x", title=None,
                        axis=alt.Axis(labelLimit=320)),
                color=bar_color,
                tooltip=tooltip,
            )
            .properties(height=max(140, 26 * len(delta_df)))
        )
        st.altair_chart(bar, use_container_width=True)
        if multi_dim:
            st.caption(f"Bar colour = {first_dim_name} (first selected "
                       "dimension). Bar direction shows slip (right) vs "
                       "gain (left).")

    # --- Gantt: planned vs recorded band per group ---
    bars = []
    for g in plotted:
        if g.planned.start and g.planned.finish:
            bars.append({"Group": g.code_value, "Series": "Planned",
                         "Start": g.planned.start, "Finish": g.planned.finish,
                         first_dim_name: _first_part(g.code_value)})
        if g.recorded.start and g.recorded.finish:
            bars.append({"Group": g.code_value, "Series": "As-recorded",
                         "Start": g.recorded.start, "Finish": g.recorded.finish,
                         first_dim_name: _first_part(g.code_value)})
    if bars:
        st.subheader("Planned vs as-recorded bands")
        if multi_dim:
            # Hue = first dimension; Planned is the faded band, As-recorded
            # the solid one (they also sit on separate row offsets).
            gantt_color = alt.Color(
                f"{first_dim_name}:N",
                scale=alt.Scale(scheme="tableau10"),
                legend=alt.Legend(orient="top", title=first_dim_name,
                                  labelLimit=300),
            )
            gantt_opacity = alt.Opacity(
                "Series:N",
                scale=alt.Scale(domain=["Planned", "As-recorded"],
                                range=[0.4, 1.0]),
                legend=alt.Legend(orient="top", title=None),
            )
            tooltip = [first_dim_name, "Group", "Series",
                       alt.Tooltip("Start:T", format="%d %b %Y"),
                       alt.Tooltip("Finish:T", format="%d %b %Y")]
        else:
            gantt_color = alt.Color(
                "Series:N",
                scale=alt.Scale(domain=["Planned", "As-recorded"],
                                range=[PLANNED_COLOR, RECORDED_COLOR]),
                legend=alt.Legend(orient="top", title=None),
            )
            gantt_opacity = alt.value(1.0)
            tooltip = ["Group", "Series",
                       alt.Tooltip("Start:T", format="%d %b %Y"),
                       alt.Tooltip("Finish:T", format="%d %b %Y")]
        gantt = (
            alt.Chart(pd.DataFrame(bars))
            .mark_bar(height=11, cornerRadius=2)
            .encode(
                x=alt.X("Start:T", title=None,
                        axis=alt.Axis(format="%b %Y", grid=True)),
                x2="Finish:T",
                y=alt.Y("Group:N", title=None,
                        axis=alt.Axis(labelLimit=320)),
                yOffset=alt.YOffset("Series:N",
                                    scale=alt.Scale(domain=["Planned",
                                                            "As-recorded"])),
                color=gantt_color,
                opacity=gantt_opacity,
                tooltip=tooltip,
            )
            .properties(height=max(160, 34 * len({b['Group'] for b in bars})))
        )
        st.altair_chart(gantt, use_container_width=True)
        if multi_dim:
            st.caption(f"Colour = {first_dim_name}; faded band = planned, "
                       "solid band = as-recorded.")

    st.subheader("Variance table")
    table = pd.DataFrame([
        {
            dim_name: g.code_value,
            "Planned start": g.planned.start.strftime("%Y-%m-%d") if g.planned.start else "—",
            "Planned finish": g.planned.finish.strftime("%Y-%m-%d") if g.planned.finish else "—",
            "Recorded start": g.recorded.start.strftime("%Y-%m-%d") if g.recorded.start else "—",
            "Recorded finish": g.recorded.finish.strftime("%Y-%m-%d") if g.recorded.finish else "—",
            "Δ start (days)": round(g.start_delta_days, 1) if g.start_delta_days is not None else None,
            "Δ finish (days)": round(g.finish_delta_days, 1) if g.finish_delta_days is not None else None,
        }
        for g in var.groups
    ])
    st.dataframe(table, use_container_width=True, hide_index=True)

    for w in var.warnings:
        st.warning(w)
    with st.expander("Standing caveats (always apply)"):
        for c in var.caveats:
            st.write("•", c)

    narrative = ai_narrative_panel(
        "nar_variance",
        lambda tmpl: build_variance_prompt(var, tmpl),
        "planned_vs_recorded",
        DEFAULT_TEMPLATES["variance"],
    )
    st.download_button(
        "⬇️ Download variance report (Excel)",
        data=build_variance_xlsx(var, narrative),
        file_name="planned_vs_recorded_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ====================================================================== #
# Tab 11 — Report Assembler (Module 11)
# ====================================================================== #

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
    inv = st.session_state.get("inventory")
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
    cp = extract_longest_path(pool[base_name], base_name)
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
        ms = track_milestone_shifts(
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
        cmp = compare_revisions(pool[base_name], pool[curr_name],
                                base_name, curr_name)
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
        wres = analyse_windows(ordered)
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
        model = pcol2.text_input("Model", value=pinfo["default_model"],
                                 key="rep_model")
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

    hashes = st.session_state.get("xer_hashes", {})
    basis = BasisOfAnalysis(
        files=[SourceFile(
            file_name=r.file_name,
            sha256=hashes.get(r.file_name, "not recorded"),
            data_date=r.data_date,
            role=("Baseline" if r.is_baseline
                  else "Current" if r.is_current else "Update"),
            activity_count=r.activity_count,
        ) for r in inv.revisions],
        settings=[s for c in selected for s in c["settings"]],
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


# ====================================================================== #
# Tab 10 — Planned Resource Histograms (Module 10)
# ====================================================================== #

def resources_tab() -> None:
    st.caption(
        "Monthly planned resource loading from the programme's assignments "
        "— planned deployment as scheduled, not actual expenditure."
    )
    files = get_parsed_files()
    inv = st.session_state.get("inventory")
    if not files or inv is None:
        st.info("Upload programmes in the **Data Intake** tab first.")
        return

    names = [r.file_name for r in inv.revisions]
    default_idx = (names.index(inv.baseline.file_name)
                   if inv.baseline else 0)
    chosen = st.selectbox("Programme", names, index=default_idx,
                          key="res_prog", help="Defaults to the baseline.")
    res = extract_resource_loading(dict(files)[chosen], chosen)

    for w in res.warnings:
        st.warning(w)
    if not res.histogram:
        return

    all_names = [r.short_name for r in res.resources]
    sel = st.multiselect(
        "Resources to chart", all_names, default=all_names[:8],
        help="Ordered by total planned quantity.")
    rows = [{"Month": p.month_end, "Resource": p.resource,
             "Type": p.rsrc_type, "Quantity": round(p.qty, 1)}
            for p in res.histogram if p.resource in sel]
    if rows:
        st.altair_chart(
            alt.Chart(pd.DataFrame(rows)).mark_bar()
            .encode(
                x=alt.X("yearmonth(Month):T", title=None,
                        axis=alt.Axis(format="%b %Y")),
                y=alt.Y("Quantity:Q", title="Planned quantity / month"),
                color=alt.Color("Resource:N",
                                legend=alt.Legend(orient="top", title=None)),
                tooltip=["Resource", "Type",
                         alt.Tooltip("yearmonth(Month):T", format="%b %Y"),
                         alt.Tooltip("Quantity:Q", format=",.0f")],
            ).properties(height=340),
            use_container_width=True,
        )

    st.subheader("Resources")
    st.dataframe(pd.DataFrame([{
        "Resource": r.short_name,
        "Name": r.name,
        "Type": r.rsrc_type,
        "Total planned qty": round(r.total_qty, 1),
        "Assignments": r.assignment_count,
    } for r in res.resources]), use_container_width=True, hide_index=True)

    with st.expander("Standing caveats (always apply)"):
        for c in res.caveats:
            st.write("•", c)

    narrative = ai_narrative_panel(
        f"nar_res_{chosen}",
        lambda tmpl: build_resources_prompt(res, tmpl),
        "resources",
        DEFAULT_TEMPLATES["resources"],
    )
    st.download_button(
        "⬇️ Download resource loading report (Excel)",
        data=build_resources_xlsx(res, narrative),
        file_name="resource_loading_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ====================================================================== #
# Tab 9 — Float Erosion Tracker (Module 9)
# ====================================================================== #

def float_erosion_tab() -> None:
    st.caption(
        "How the programme's scheduling flexibility changed across "
        "revisions: float profile per revision and float consumption per "
        "window."
    )
    files = get_parsed_files()
    inv = st.session_state.get("inventory")
    if not files or inv is None or len(files) < 2:
        st.info("Upload at least two programmes in the **Data Intake** tab "
                "first.")
        return

    near = st.number_input("Near-critical threshold (days)",
                           1.0, 100.0, 10.0, 1.0)
    pool = dict(files)
    ordered = [(r.file_name, pool[r.file_name]) for r in inv.revisions]
    res = analyse_float_erosion(ordered, near_days=near)

    last = res.snapshots[-1]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Median float (latest)",
              f"{last.median_float:+.0f} d"
              if last.median_float is not None else "—")
    m2.metric("Negative-float activities", last.negative_count)
    m3.metric("Critical (TF ≤ 0)", last.critical_count)
    m4.metric("Minimum float",
              f"{last.min_float:+.0f} d"
              if last.min_float is not None else "—")

    for w in res.warnings:
        (st.success if w.startswith("Favourable") else st.warning)(w)

    prof = []
    for s in res.snapshots:
        if s.data_date is None:
            continue
        prof += [
            {"Data date": s.data_date, "Revision": s.label,
             "Metric": "Median float (d)", "Value": s.median_float},
            {"Data date": s.data_date, "Revision": s.label,
             "Metric": "Negative-float count", "Value": s.negative_count},
        ]
    if prof:
        st.altair_chart(
            alt.Chart(pd.DataFrame(prof)).mark_line(point=True)
            .encode(
                x=alt.X("Data date:T", title=None,
                        axis=alt.Axis(format="%b %Y")),
                y=alt.Y("Value:Q", title=None),
                color=alt.Color("Metric:N", title=None,
                                legend=alt.Legend(orient="top")),
                tooltip=["Revision", "Metric", "Value"],
            ).properties(height=260).facet(
                column=alt.Column("Metric:N", title=None)
            ).resolve_scale(y="independent"),
            use_container_width=True,
        )

    st.subheader("Float profile by revision")
    st.dataframe(pd.DataFrame([{
        "Revision": s.label,
        "Data date": f"{s.data_date:%Y-%m-%d}" if s.data_date else "—",
        "Incomplete": s.incomplete_count,
        "Median TF (d)": s.median_float,
        "Min TF (d)": s.min_float,
        "Critical (TF ≤ 0)": s.critical_count,
        "Negative": s.negative_count,
        f"Near (≤ {near:.0f}d)": s.near_count,
    } for s in res.snapshots]), use_container_width=True, hide_index=True)

    for w in res.windows:
        if w.top_eroders or w.top_gainers:
            with st.expander(
                f"Window {w.index}: {w.from_label} → {w.to_label} — "
                f"median Δ {w.median_delta:+.0f}d, {w.eroded_count} eroded, "
                f"{w.gained_count} gained"
            ):
                st.dataframe(pd.DataFrame([{
                    "Direction": "eroded", "Activity ID": d.task_code,
                    "Activity": d.name, "TF was (d)": d.old_tf,
                    "TF now (d)": d.new_tf, "Delta (d)": round(d.delta, 1),
                } for d in w.top_eroders] + [{
                    "Direction": "gained", "Activity ID": d.task_code,
                    "Activity": d.name, "TF was (d)": d.old_tf,
                    "TF now (d)": d.new_tf, "Delta (d)": round(d.delta, 1),
                } for d in w.top_gainers]),
                    use_container_width=True, hide_index=True)

    with st.expander("Standing caveats (always apply)"):
        for c in res.caveats:
            st.write("•", c)

    narrative = ai_narrative_panel(
        "nar_float",
        lambda tmpl: build_float_erosion_prompt(res, tmpl),
        "float_erosion",
        DEFAULT_TEMPLATES["float_erosion"],
    )
    st.download_button(
        "⬇️ Download float erosion report (Excel)",
        data=build_float_erosion_xlsx(res, narrative),
        file_name="float_erosion_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ====================================================================== #
# Tab 8 — Progress S-curve (Module 8)
# ====================================================================== #

def progress_tab() -> None:
    st.caption(
        "Planned cumulative progress from the baseline vs recorded progress "
        "from the updates — slippage appears as the horizontal gap between "
        "the curves."
    )
    files = get_parsed_files()
    inv = st.session_state.get("inventory")
    if not files or inv is None:
        st.info("Upload programmes in the **Data Intake** tab first.")
        return
    if inv.baseline is None or len(files) < 2:
        st.info("A baseline plus at least one update are needed for the "
                "S-curve comparison.")
        return

    pool = dict(files)
    base_name = inv.baseline.file_name
    updates = [(r.file_name, pool[r.file_name])
               for r in inv.revisions if r.file_name != base_name]

    scheme_label = st.radio(
        "Progress weighting", list(WEIGHT_OPTIONS.values()), horizontal=True,
        help="How much each activity contributes to overall percent "
             "complete.")
    scheme = next(k for k, v in WEIGHT_OPTIONS.items()
                  if v == scheme_label)

    res = compute_progress(pool[base_name], base_name, updates,
                           weight_scheme=scheme)
    if not res.planned_curve:
        for w in res.warnings:
            st.warning(w)
        return

    m1, m2, m3 = st.columns(3)
    m1.metric("Planned at data date",
              f"{res.planned_pct_at_dd:.1f}%"
              if res.planned_pct_at_dd is not None else "—")
    m2.metric("Recorded at data date",
              f"{res.recorded_pct_at_dd:.1f}%"
              if res.recorded_pct_at_dd is not None else "—")
    m3.metric("Time offset",
              f"{res.time_offset_days:+.0f} d"
              if res.time_offset_days is not None else "—",
              help="Positive = the recorded level of progress was planned "
                   "to be reached that many days earlier.")

    for w in res.warnings:
        (st.success if w.startswith("Favourable") else st.warning)(w)

    rows = ([{"Date": p.date, "Cum %": p.cum_pct, "Series": "Planned"}
             for p in res.planned_curve]
            + [{"Date": p.date, "Cum %": p.cum_pct, "Series": "As-recorded"}
               for p in res.recorded_curve])
    layers = [
        alt.Chart(pd.DataFrame(rows)).mark_line(point=True)
        .encode(
            x=alt.X("Date:T", title=None, axis=alt.Axis(format="%b %Y")),
            y=alt.Y("Cum %:Q", title="Cumulative progress (%)",
                    scale=alt.Scale(domain=[0, 100])),
            color=alt.Color("Series:N", title=None,
                            scale=alt.Scale(
                                domain=["Planned", "As-recorded"],
                                range=["#3b76c4", "#cf222e"]),
                            legend=alt.Legend(orient="top")),
            tooltip=[alt.Tooltip("Date:T", format="%b %Y"), "Series",
                     alt.Tooltip("Cum %:Q", format=".1f")],
        )
    ]
    pts = [{"Date": rp.data_date, "Cum %": rp.recorded_pct,
            "Revision": rp.label}
           for rp in res.revision_points
           if rp.data_date and rp.recorded_pct is not None]
    if pts:
        layers.append(
            alt.Chart(pd.DataFrame(pts)).mark_point(
                shape="diamond", size=140, filled=True, color="#e8a33d")
            .encode(x="Date:T", y="Cum %:Q",
                    tooltip=["Revision",
                             alt.Tooltip("Date:T", format="%d %b %Y"),
                             alt.Tooltip("Cum %:Q", format=".1f")]))
    st.altair_chart(alt.layer(*layers).properties(height=380),
                    use_container_width=True)
    st.caption("◆ = each revision's overall recorded % at its data date.")

    if res.revision_points:
        st.dataframe(pd.DataFrame([{
            "Revision": rp.label,
            "Data date": (f"{rp.data_date:%Y-%m-%d}"
                          if rp.data_date else "—"),
            "Recorded %": rp.recorded_pct,
            "Planned %": rp.planned_pct,
            "Gap (pts)": (round(rp.planned_pct - rp.recorded_pct, 1)
                          if rp.planned_pct is not None
                          and rp.recorded_pct is not None else None),
        } for rp in res.revision_points]),
            use_container_width=True, hide_index=True)

    with st.expander("Standing caveats (always apply)"):
        for c in res.caveats:
            st.write("•", c)

    narrative = ai_narrative_panel(
        f"nar_progress_{scheme}",
        lambda tmpl: build_progress_prompt(res, tmpl),
        "progress",
        DEFAULT_TEMPLATES["progress"],
    )
    st.download_button(
        "⬇️ Download S-curve report (Excel)",
        data=build_progress_xlsx(res, narrative),
        file_name="progress_scurve_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ====================================================================== #
# Tab 7 — Windows / Period Movement (Module 7)
# ====================================================================== #

def windows_tab() -> None:
    st.caption(
        "Movement per window between consecutive data dates: how much "
        "completion moved, and how the driving path changed in each period."
    )
    files = get_parsed_files()
    inv = st.session_state.get("inventory")
    if not files or inv is None or len(files) < 2:
        st.info("Upload at least two programmes in the **Data Intake** tab "
                "first.")
        return

    pool = dict(files)
    ordered = [(r.file_name, pool[r.file_name]) for r in inv.revisions]
    res = analyse_windows(ordered)
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
            use_container_width=True,
        )
    mv = [{"Window": f"W{w.index}: {w.from_label} → {w.to_label}",
           "Movement (d)": w.movement_days}
          for w in res.windows if w.movement_days is not None]
    if mv:
        c2.altair_chart(
            alt.Chart(pd.DataFrame(mv)).mark_bar(cornerRadius=2)
            .encode(
                x=alt.X("Window:N", sort=None, title=None,
                        axis=alt.Axis(labelAngle=-20, labelLimit=200)),
                y=alt.Y("Movement (d):Q"),
                color=alt.condition("datum['Movement (d)'] > 0",
                                    alt.value("#cf222e"),
                                    alt.value("#1a7f37")),
                tooltip=["Window", "Movement (d)"],
            ).properties(height=260, title="Movement per window"),
            use_container_width=True,
        )

    st.subheader("Windows")
    st.dataframe(pd.DataFrame([{
        "#": w.index,
        "From": w.from_label,
        "To": w.to_label,
        "Period": (f"{w.start:%Y-%m-%d} → {w.end:%Y-%m-%d}"
                   if w.start and w.end else "—"),
        "Window (d)": w.window_days,
        "Completion movement (d)": w.movement_days,
        "Path retained": w.cp_retained,
        "Path similarity": (f"{w.cp_similarity:.0%}"
                            if w.cp_similarity is not None else "—"),
        "Joined / left path": f"{len(w.joined)} / {len(w.left)}",
    } for w in res.windows]), use_container_width=True, hide_index=True)

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
                } for s in w.shifts]), use_container_width=True,
                    hide_index=True)

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


# ====================================================================== #
# Tab 6 — Revision Comparison / Change Log (Module 6)
# ====================================================================== #

def comparison_tab() -> None:
    st.caption(
        "A change log between two programme revisions: scope, logic, "
        "durations, constraints, calendars — and retrospective changes to "
        "actualised dates."
    )
    files = get_parsed_files()
    inv = st.session_state.get("inventory")
    if not files or inv is None or len(files) < 2:
        st.info("Upload at least two programmes in the **Data Intake** tab "
                "first.")
        return

    names = [r.file_name for r in inv.revisions]     # data-date order
    c1, c2 = st.columns(2)
    old_name = c1.selectbox("Earlier revision", names, index=0,
                            help="Defaults to the baseline.")
    new_default = len(names) - 1 if names[-1] != old_name else 0
    new_name = c2.selectbox("Later revision", names, index=new_default)
    if old_name == new_name:
        st.warning("Pick two different revisions.")
        return

    pool = dict(files)
    cmp = compare_revisions(pool[old_name], pool[new_name],
                            old_name, new_name)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total changes", cmp.total_changes)
    m2.metric("Added / deleted",
              f"{len(cmp.added)} / {len(cmp.deleted)}")
    m3.metric("Logic added / removed",
              f"{len(cmp.logic_added)} / {len(cmp.logic_removed)}")
    m4.metric("Actuals changed retrospectively",
              len(cmp.actual_date_changes))
    if cmp.old_finish and cmp.new_finish:
        moved = (cmp.new_finish - cmp.old_finish).days
        st.markdown(
            f"Scheduled completion: **{cmp.old_finish:%d %b %Y}** → "
            f"**{cmp.new_finish:%d %b %Y}** ({moved:+d} calendar days)"
        )

    for w in cmp.warnings:
        st.warning(w)

    counts = {k: v for k, v in cmp.category_counts.items() if v}
    if not counts:
        st.success("No differences found between the two revisions.")
        return
    chart_df = pd.DataFrame(
        [{"Category": k, "Count": v} for k, v in counts.items()])
    st.altair_chart(
        alt.Chart(chart_df).mark_bar(cornerRadius=2)
        .encode(
            x=alt.X("Count:Q", title=None),
            y=alt.Y("Category:N", sort="-x", title=None,
                    axis=alt.Axis(labelLimit=280)),
            color=alt.condition(
                "datum.Category == 'Actual dates changed retrospectively'",
                alt.value("#cf222e"), alt.value("#3b76c4")),
            tooltip=["Category", "Count"],
        ).properties(height=28 * len(chart_df)),
        use_container_width=True,
    )

    def _acts_table(refs):
        return pd.DataFrame([{
            "Activity ID": a.task_code, "Activity": a.name,
            "Type": "Milestone" if a.is_milestone else "Task",
            "Start": a.start.strftime("%Y-%m-%d") if a.start else "—",
            "Finish": a.finish.strftime("%Y-%m-%d") if a.finish else "—",
            "Duration (d)": a.duration_days,
        } for a in refs])

    def _changes_table(changes):
        return pd.DataFrame([{
            "Activity / Link": c.task_code, "Name": c.name,
            "Was": c.old_value, "Now": c.new_value,
            "Delta (d)": c.delta_days,
        } for c in changes])

    def _logic_table(links):
        return pd.DataFrame([{
            "Predecessor": lk.pred_code, "Pred name": lk.pred_name,
            "Type": lk.link_type, "Successor": lk.succ_code,
            "Succ name": lk.succ_name, "Lag (d)": lk.lag_days,
        } for lk in links])

    if cmp.actual_date_changes:
        with st.expander(
            f"🚩 Actual dates changed retrospectively "
            f"({len(cmp.actual_date_changes)})", expanded=True,
        ):
            st.dataframe(_changes_table(cmp.actual_date_changes),
                         use_container_width=True, hide_index=True)

    sections = [
        (f"Activities added ({len(cmp.added)})", _acts_table, cmp.added),
        (f"Activities deleted ({len(cmp.deleted)})", _acts_table,
         cmp.deleted),
        (f"Duration changes ({len(cmp.duration_changes)})", _changes_table,
         cmp.duration_changes),
        (f"Logic added ({len(cmp.logic_added)})", _logic_table,
         cmp.logic_added),
        (f"Logic removed ({len(cmp.logic_removed)})", _logic_table,
         cmp.logic_removed),
        (f"Lag changes ({len(cmp.lag_changes)})", _changes_table,
         cmp.lag_changes),
        (f"Constraint changes ({len(cmp.constraint_changes)})",
         _changes_table, cmp.constraint_changes),
        (f"Calendar reassignments ({len(cmp.calendar_changes)})",
         _changes_table, cmp.calendar_changes),
        (f"Renamed activities ({len(cmp.renamed)})", _changes_table,
         cmp.renamed),
    ]
    for label, fn, items in sections:
        if items:
            with st.expander(label):
                st.dataframe(fn(items), use_container_width=True,
                             hide_index=True)

    with st.expander("Standing caveats (always apply)"):
        for c in cmp.caveats:
            st.write("•", c)

    narrative = ai_narrative_panel(
        f"nar_cmp_{old_name}_{new_name}",
        lambda tmpl: build_comparison_prompt(cmp, tmpl),
        "comparison",
        DEFAULT_TEMPLATES["comparison"],
    )
    st.download_button(
        "⬇️ Download comparison report (Excel)",
        data=build_comparison_xlsx(cmp, narrative),
        file_name="revision_comparison_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ====================================================================== #
# Tab 5 — Baseline Planned Critical Path (Module 5)
# ====================================================================== #

BAND_COLORS = {"critical": "#cf222e", "near-critical": "#e8a33d"}


def critical_path_tab() -> None:
    st.caption(
        "The planned critical path of a single programme: the chain of "
        "activities at or below the float tolerance, its continuity, and the "
        "near-critical band behind it."
    )
    files = get_parsed_files()
    inv = st.session_state.get("inventory")
    if not files or inv is None:
        st.info("Upload programmes in the **Data Intake** tab first.")
        return

    names = [r.file_name for r in inv.revisions]
    default_idx = (names.index(inv.baseline.file_name)
                   if inv.baseline else 0)
    c1, c2 = st.columns([2, 2])
    chosen = c1.selectbox("Programme", names, index=default_idx,
                          help="Defaults to the baseline.")
    method = c2.radio(
        "Identification method",
        ["Longest path (backward driving trace)", "Float-based (TF ≤ tolerance)"],
        horizontal=True,
        help="Longest path traces the driving logic backward from the end "
             "activity — robust with multiple calendars. Float-based flags "
             "everything at or below the tolerance.",
    )
    data = dict(files)[chosen]

    if method.startswith("Longest"):
        cands = end_activity_candidates(data, limit=40)
        if not cands:
            st.warning("No incomplete activities with early dates to trace from.")
            return
        cand_labels = {
            code: f"{code} — {name}" + (f"  (EF {ef:%Y-%m-%d})" if ef else "")
            for code, name, ef in cands
        }
        cc1, cc2, cc3 = st.columns([3, 1, 1])
        end_code = cc1.selectbox(
            "Trace backward from",
            options=list(cand_labels.keys()),
            format_func=lambda c: cand_labels[c],
            help="Defaults to the latest finisher (completion milestone "
                 "preferred). Pick a sectional milestone to isolate its "
                 "individual driving chain.",
        )
        near = cc2.number_input("Near-critical ≤ (days)", 0.0, 200.0, 10.0, 1.0)
        show_near = cc3.toggle("Show near-critical", value=False)
        cp = extract_longest_path(
            data, chosen, end_task_code=end_code, near_critical_days=near)
    else:
        cc1, cc2, cc3 = st.columns([1, 1, 1])
        tol = cc1.number_input("Critical float ≤ (days)", -100.0, 100.0, 0.0, 1.0)
        near = cc2.number_input("Near-critical ≤ (days)", 0.0, 200.0, 10.0, 1.0)
        show_near = cc3.toggle("Show near-critical", value=False)
        cp = extract_critical_path(
            data, chosen, float_tolerance_days=tol, near_critical_days=near)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Path activities" if cp.method == "longest_path"
              else "Critical activities", len(cp.critical))
    m2.metric("Near-critical", len(cp.near_critical))
    if cp.method == "longest_path":
        m3.metric("Driving links", len(cp.links))
        m4.metric("Traced from", cp.end_choice or "—")
    else:
        m3.metric("Chain segments", cp.chain_segments)
        m4.metric("Continuous", "Yes ✅" if cp.is_continuous else "No ⚠️")

    for w in cp.warnings:
        st.warning(w)
    if not cp.critical:
        return

    # --- Chain visual: bars in ES order + logic-link connectors ---------
    shown = [a for a in cp.activities
             if a.band == "critical" or show_near]
    if len(shown) > 300:
        st.info(f"{len(shown)} activities in view — drawing the first 300 "
                "by early start. Narrow the tolerance to see the full chain.")
        shown = shown[:300]
    order = [f"{a.task_code} · {a.name[:38]}" for a in shown]
    label_by_code = {a.task_code: lbl for a, lbl in zip(shown, order)}

    rows, points = [], []
    for a, lbl in zip(shown, order):
        base = {
            "Activity": lbl, "Band": a.band,
            "Float (d)": a.total_float_days,
        }
        if a.is_milestone and (a.early_finish or a.early_start):
            points.append({**base,
                           "Date": a.early_finish or a.early_start})
        elif a.early_start and a.early_finish:
            rows.append({**base, "Start": a.early_start,
                         "Finish": a.early_finish})

    band_color = alt.Color(
        "Band:N",
        scale=alt.Scale(domain=list(BAND_COLORS), range=list(BAND_COLORS.values())),
        legend=alt.Legend(orient="top", title=None),
    )
    y_axis = alt.Y("Activity:N", sort=order, title=None,
                   axis=alt.Axis(labelLimit=330))
    layers = []
    if rows:
        layers.append(
            alt.Chart(pd.DataFrame(rows)).mark_bar(height=8, cornerRadius=2)
            .encode(x=alt.X("Start:T", title=None,
                            axis=alt.Axis(format="%b %Y", grid=True)),
                    x2="Finish:T", y=y_axis, color=band_color,
                    tooltip=["Activity", "Band",
                             alt.Tooltip("Start:T", format="%d %b %Y"),
                             alt.Tooltip("Finish:T", format="%d %b %Y"),
                             alt.Tooltip("Float (d):Q", format="+.0f")]))
    if points:
        layers.append(
            alt.Chart(pd.DataFrame(points)).mark_point(
                shape="diamond", size=120, filled=True)
            .encode(x="Date:T", y=y_axis, color=band_color,
                    tooltip=["Activity", "Band",
                             alt.Tooltip("Date:T", format="%d %b %Y"),
                             alt.Tooltip("Float (d):Q", format="+.0f")]))

    # Logic-link connectors between critical activities in view.
    link_rows = [
        {"y": label_by_code[lk.pred_code], "y2": label_by_code[lk.succ_code]}
        for lk in cp.links
        if lk.pred_code in label_by_code and lk.succ_code in label_by_code
    ]
    if link_rows:
        pred_finish = {label_by_code[a.task_code]:
                       (a.early_finish or a.early_start) for a in shown}
        succ_start = {label_by_code[a.task_code]:
                      (a.early_start or a.early_finish) for a in shown}
        for lr in link_rows:
            lr["x"] = pred_finish.get(lr["y"])
            lr["x2"] = succ_start.get(lr["y2"])
        link_df = pd.DataFrame(
            [lr for lr in link_rows if lr["x"] and lr["x2"]])
        if not link_df.empty:
            layers.insert(0,
                alt.Chart(link_df).mark_rule(
                    strokeWidth=0.7, color="#8a8f98", opacity=0.6)
                .encode(x="x:T", x2="x2:T", y=alt.Y("y:N", sort=order),
                        y2="y2:N"))

    if layers:
        st.altair_chart(
            alt.layer(*layers).properties(
                height=max(240, 15 * len(order))).resolve_scale(y="shared"),
            use_container_width=True,
        )
        st.caption("Bars in early-start order; ◆ = milestone; grey lines = "
                   "logic links between critical activities. Gaps with no "
                   "connector indicate a broken chain.")

    st.subheader("Path activities")
    table = pd.DataFrame([
        {
            "Activity ID": a.task_code,
            "Activity": a.name,
            "Type": "Milestone" if a.is_milestone else "Task",
            "Band": a.band,
            "Early start": a.early_start.strftime("%Y-%m-%d") if a.early_start else "—",
            "Early finish": a.early_finish.strftime("%Y-%m-%d") if a.early_finish else "—",
            "Duration (d)": a.duration_days,
            "Total float (d)": a.total_float_days,
        }
        for a in (cp.activities if show_near else cp.critical)
    ])
    st.dataframe(table, use_container_width=True, hide_index=True, height=340)

    with st.expander("Standing caveats (always apply)"):
        for c in cp.caveats:
            st.write("•", c)

    narrative = ai_narrative_panel(
        f"nar_cp_{chosen}",
        lambda tmpl: build_critical_path_prompt(cp, tmpl),
        "critical_path",
        DEFAULT_TEMPLATES["critical_path"],
    )
    st.download_button(
        "⬇️ Download critical path report (Excel)",
        data=build_critical_path_xlsx(cp, narrative),
        file_name="critical_path_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ====================================================================== #

def main() -> None:
    st.title("Forensic Programme Analysis")
    st.caption("Primavera P6 (.xer) delay-analysis toolkit — one module per tab.")

    (intake, dcma, cpath, milestones, variance, compare, windows,
     scurve, floats, resources, report) = st.tabs([
        "📥 Data Intake & Inventory",
        "🩺 DCMA 14-Point",
        "🧭 Baseline Critical Path",
        "🏁 Milestone Shift Tracker",
        "📊 As-Planned vs As-Recorded",
        "🔀 Revision Comparison",
        "🪟 Windows Analysis",
        "📈 Progress S-Curve",
        "🎈 Float Erosion",
        "👷 Resource Loading",
        "📄 Report Assembler",
    ])
    with intake:
        intake_tab()
    with dcma:
        dcma_tab()
    with cpath:
        critical_path_tab()
    with milestones:
        milestone_tab()
    with variance:
        variance_tab()
    with compare:
        comparison_tab()
    with windows:
        windows_tab()
    with scurve:
        progress_tab()
    with floats:
        float_erosion_tab()
    with resources:
        resources_tab()
    with report:
        report_tab()


if __name__ == "__main__":
    main()
