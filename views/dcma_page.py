"""DCMA 14-Point schedule health (Module 1)."""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from dcma import DCMAConfig
from dcma.checks import CheckStatus
from dcma.config import (
    HARD_CONSTRAINT_CODES_EXTENDED, HARD_CONSTRAINT_CODES_STRICT,
)
from dcma.narrative import (
    DEFAULT_TEMPLATE as DCMA_DEFAULT_TEMPLATE, build_report_prompt,
)
from dcma.report_xlsx import build_xlsx_report
from programme import dcma_appendix
from views._shared import (
    STATUS_BG, STATUS_COLORS, _cfgkey, _fkey, ai_narrative_panel, cached_dcma,
    get_parsed_files,
)


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
            st.markdown("**Supplementary (not DCMA 14)**")
            cfg.loe_driving_max_count = st.number_input(
                "15 · Max LOE-driving links", 0, 1000,
                cfg.loe_driving_max_count, 1)
            cfg.redundant_max_pct = st.number_input(
                "16 · Max redundant-logic %", 0.0, 100.0,
                cfg.redundant_max_pct, 0.5)
            cfg.dangling_max_pct = st.number_input(
                "17 · Max dangling-ends %", 0.0, 100.0,
                cfg.dangling_max_pct, 0.5)
    return cfg


def scorecard(results) -> None:
    passed = sum(1 for r in results if r.status == CheckStatus.PASS)
    failed = sum(1 for r in results if r.status == CheckStatus.FAIL)
    na = sum(1 for r in results if r.status == CheckStatus.NA)
    scored = passed + failed
    score_pct = (passed / scored * 100.0) if scored else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Checks Passed", f"{passed}/{scored}",
              help="DCMA 14 plus 3 supplementary baseline-quality checks "
                   "(15-17, labelled 'supp.' — not part of the standard).")
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
                st.dataframe(df, width="stretch", hide_index=True)
                st.caption(f"{len(df)} affected item(s).")
            elif r.affected_ids:
                st.write(", ".join(r.affected_ids[:200]))


_PATH_ICON = {"driving": "🔴 driving", "critical": "🟠 critical",
              "near-critical": "🟡 near-critical", "off-path": "⚪ off-path"}


def traceback_section(trace) -> None:
    """Forensic traceback: driving chain, float drivers, offender index."""
    st.subheader("Forensic Traceback")
    st.caption(
        "Networked detail behind the scorecard — from the file's own "
        "stored dates, float and logic; nothing recomputed."
    )

    c = trace.chain
    m1, m2, m3 = st.columns(3)
    m1.metric("Driving chain (Check 12)",
              f"{len(c.steps)} activities" if c and c.steps else "—",
              help="Ordered walk of the stored driving logic to the "
                   "latest incomplete finisher.")
    m2.metric("Negative-float drivers (5→7)",
              f"{len(trace.float_driver_groups)} distinct"
              if trace.float_driver_groups else "none",
              help="Each negative-float activity traced downstream to the "
                   "constraint or project date governing its late dates.")
    m3.metric("Multi-check offenders",
              str(len(trace.offenders)),
              help="Activities tripping two or more of checks 1–11, "
                   "ranked driving-path first.")

    for w in trace.warnings:
        st.warning(w)

    if c and c.steps:
        cont = ("✅ traces continuously back to the data date"
                if c.reaches_data_date
                else f"⛔ breaks at `{c.break_code}` — {c.break_reason}")
        with st.expander(
            f"Driving chain — {len(c.steps)} steps to {c.terminal_code} "
            f"({'continuous' if c.reaches_data_date else 'BROKEN'})",
            expanded=not c.reaches_data_date,
        ):
            st.markdown(f"The chain {cont}.")
            chain_df = pd.DataFrame([{
                "#": s.seq,
                "Activity ID": s.task_code,
                "Activity Name": s.name,
                "MS": "🏁" if s.is_milestone else "",
                "Early Start": (s.early_start.strftime("%Y-%m-%d")
                                if s.early_start else ""),
                "Early Finish": (s.early_finish.strftime("%Y-%m-%d")
                                 if s.early_finish else ""),
                "TF (d)": s.total_float_days,
                "Driven by (link)": s.link_from_prev,
                "Constraint(s)": s.constraint,
            } for s in c.steps])
            st.dataframe(chain_df, width="stretch", hide_index=True)

    if trace.float_driver_groups:
        with st.expander(
            f"Negative float → governing constraint — "
            f"{len(trace.float_traces)} activities, "
            f"{len(trace.float_driver_groups)} driver(s)"
        ):
            drv_df = pd.DataFrame([{
                "Activities": g.count,
                "Worst TF (d)": g.worst_tf_days,
                "Governing driver": g.driver_detail,
                "Kind": g.driver_kind,
                "Example trace": (
                    g.example.origin_code
                    + (" → " + " → ".join(g.example.via_codes[:6])
                       if g.example.via_codes else "")
                ) if g.example else "",
            } for g in trace.float_driver_groups])
            st.dataframe(drv_df, width="stretch", hide_index=True)
            st.caption(
                "A traced driver is the mechanical cause inside the "
                "schedule model — not a statement of responsibility."
            )

    if trace.offenders:
        with st.expander(
            f"Activities tripping multiple checks — {len(trace.offenders)}"
        ):
            off_df = pd.DataFrame([{
                "Path position": _PATH_ICON.get(o.band, o.band),
                "Activity ID": o.task_code,
                "Activity Name": o.name,
                "Checks tripped": o.checks_label,
                "Count": len(o.checks),
            } for o in trace.offenders[:300]])
            st.dataframe(off_df, width="stretch", hide_index=True)
            if len(trace.offenders) > 300:
                st.caption(f"Showing 300 of {len(trace.offenders)}.")

    with st.expander("Traceback caveats (always apply)"):
        for cv in trace.caveats:
            st.write("•", cv)


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

    results, trace = cached_dcma(_fkey(chosen), _cfgkey(cfg), data, cfg)

    st.header("Scorecard")
    scorecard(results)
    st.divider()
    detail_section(results)

    st.divider()
    traceback_section(trace)

    st.divider()
    narrative = ai_narrative_panel(
        f"nar_dcma_{chosen}",
        lambda tmpl: build_report_prompt(data, results, tmpl, trace=trace),
        f"dcma_{proj.short_name if proj else 'project'}",
        DCMA_DEFAULT_TEMPLATE,
        appendix_builder=lambda r=results, t=trace:
            dcma_appendix(r, trace=t),
    )

    st.subheader("Export")
    col1, col2 = st.columns(2)
    col1.download_button(
        "⬇️ Excel report (.xlsx)",
        data=build_xlsx_report(data, results, narrative=narrative,
                               trace=trace),
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
