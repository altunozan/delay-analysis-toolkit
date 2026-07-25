"""Shared as-built critical-path picker.

One method: pick the milestone, trace backwards to the start of the
works. Rendered by BOTH the standalone As-Built Critical Path page and
APvAB step ②, so the same analysis cannot answer differently depending
on which page you opened.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import state as sk
from programme import extract_actual_trace, trace_end_candidates

BASIS_MARK = {"as-built": "▮ as-built",
              "in-progress": "▨ in progress",
              "forecast": "▯ forecast"}


def terminal_picker(ordered, key_prefix: str):
    """Milestone dropdown + advanced settings. Returns (code, gap, strict)."""
    cms = st.session_state.get(sk.CONTRACT_MS)
    cands = trace_end_candidates(ordered, contract_ms=cms)
    if not cands:
        return None, None, None
    labels = {
        c: (f"{c} — {n}"
            + (f"  ({'achieved' if ok else 'forecast'} {d:%d %b %Y})"
               if d else "")
            + ("" if ok else "  ⚠ not achieved"))
        for c, n, d, ok in cands}
    end_code = st.selectbox(
        "Trace back from", options=list(labels),
        format_func=lambda c: labels[c], key=f"{key_prefix}_end",
        help="Every milestone is listed, achieved or not. Choosing one "
             "the works never reached gives a path that is as-built up "
             "to the data date and forecast beyond it — labelled "
             "throughout.")
    with st.expander("Advanced"):
        gap = st.number_input(
            "Treat a hand-off as broken beyond (days)",
            1.0, 1095.0, 365.0, 30.0, key=f"{key_prefix}_gap",
            help="How long the works may pause between one activity "
                 "finishing and the next starting before the tool stops "
                 "treating them as consecutive. Generous by default — "
                 "real projects stall.")
        strict = st.toggle(
            "Only follow programmed relationships", value=False,
            key=f"{key_prefix}_strict",
            help="OFF (default): where the programme never linked two "
                 "consecutive activities, the chain still follows the "
                 "recorded sequence, and every such hand-off is flagged. "
                 "ON: the trace stops at the first hand-off with no "
                 "programmed relationship.")
    return end_code, gap, strict


def render_trace(trace, *, show_chain: bool = True) -> None:
    """Headline figures, the as-built/forecast split, and the chain."""
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("Activities on the path", len(trace.activities))
    seq = sum(1 for lk in trace.links if not lk.had_logic)
    t2.metric("Hand-offs on sequence only",
              f"{seq} / {len(trace.links)}" if trace.links else "—",
              help="Consecutive in the records, but the programme never "
                   "linked them. Corroborate these against the "
                   "contemporaneous record.")
    t3.metric("As-built / forecast",
              f"{trace.asbuilt_count} / {trace.forecast_count}")
    t4.metric("Traced from", trace.terminal_code or "—")
    if trace.hybrid:
        st.warning(
            "⚠️ **The milestone was not achieved.** The path is as-built "
            "up to the data date and forecast beyond it — the forecast "
            "part is what the programme predicts, not what happened.")
    for w in trace.warnings:
        (st.info if w.startswith("Logic corroboration")
         else st.warning)(w)
    if show_chain and trace.activities:
        st.dataframe(pd.DataFrame([{
            "#": i,
            "Basis": BASIS_MARK.get(a.basis, a.basis),
            "Activity ID": a.task_code,
            "Activity": a.name,
            "Start": f"{a.act_start:%Y-%m-%d}" if a.act_start else "—",
            "Finish": f"{a.act_finish:%Y-%m-%d}" if a.act_finish else "—",
        } for i, a in enumerate(trace.activities, start=1)]),
            width="stretch", hide_index=True, height=340)


def trace_basis(ordered, key_prefix: str):
    """Milestone picker + trace + headline render. Returns the trace."""
    end_code, gap, strict = terminal_picker(ordered, key_prefix)
    if end_code is None:
        st.info("No activities with recorded dates in the latest "
                "revision — nothing to trace.")
        return None
    trace = extract_actual_trace(
        ordered, end_task_code=end_code, max_gap_days=gap,
        allow_temporal_fallback=not strict)
    render_trace(trace, show_chain=False)
    return trace


def link_table(trace) -> None:
    """Activity-level logic links along the path."""
    if not trace.links:
        return
    st.dataframe(pd.DataFrame([{
        "Predecessor": lk.pred_code,
        "→ Successor": lk.succ_code,
        "Type": lk.kind,
        "Gap (d)": lk.gap_days,
        "Basis": "programmed logic" if lk.had_logic else "SEQUENCE ONLY",
        "Confidence": lk.score,
    } for lk in trace.links]), width="stretch", hide_index=True)
