"""Shared as-built critical-path picker.

Rendered by BOTH the standalone As-Built Critical Path page and APvAB
step ②. It exists because those two had drifted: APvAB carried a
cut-down copy with no gap control, no strict/continuous toggle and no
composition metrics, so the same analysis gave different answers
depending on which page you opened. One component, one behaviour.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import state as sk
from programme import (
    analyse_asbuilt_path, extract_actual_trace, trace_end_candidates,
    triangulate,
)

BASIS_MARK = {"as-built": "▮ as-built",
              "in-progress": "▨ in progress",
              "forecast": "▯ forecast"}


def terminal_picker(ordered, key_prefix: str):
    """Terminal + gap + strictness controls. Returns (end_code, gap, strict)."""
    cms = st.session_state.get(sk.CONTRACT_MS)
    cands = trace_end_candidates(ordered, contract_ms=cms)
    if not cands:
        return None, None, None
    labels = {
        c: (f"{c} — {n}"
            + (f"  ({'AF' if ok else 'forecast'} {d:%Y-%m-%d})" if d else "")
            + ("" if ok else "  ⚠ not achieved"))
        for c, n, d, ok in cands}
    c1, c2, c3 = st.columns([3, 1, 1])
    end_code = c1.selectbox(
        "Trace backward from", options=list(labels),
        format_func=lambda c: labels[c], key=f"{key_prefix}_end",
        help="Defaults to the elected contractual completion milestone. "
             "Where that milestone has not been achieved the path is "
             "traced as a disclosed hybrid: as-built to the data date, "
             "forecast beyond it.")
    gap = c2.number_input("Max hand-off gap (days)", 1.0, 730.0, 60.0, 5.0,
                          key=f"{key_prefix}_gap",
                          help="Widen when work stalled between logically "
                               "linked activities.")
    strict = c3.toggle(
        "Strict logic only", value=False, key=f"{key_prefix}_strict",
        help="OFF (default): the chain continues through the tightest "
             "temporal neighbour where no programmed relationship exists, "
             "so the path runs unbroken from the milestone back to "
             "project start — every such hop is flagged as sequence-only "
             "evidence. ON: the trace STOPS at the first hand-off the "
             "records cannot evidence.")
    return end_code, gap, strict


def render_trace(trace, *, show_chain: bool = True) -> None:
    """Metrics, hybrid banner, warnings and the basis-labelled chain."""
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("Chain length", len(trace.activities))
    logic_n = sum(1 for lk in trace.links if lk.had_logic)
    t2.metric("Logic-evidenced hand-offs",
              f"{logic_n} / {len(trace.links)}" if trace.links else "—")
    t3.metric("As-built / forecast",
              f"{trace.asbuilt_count} / {trace.forecast_count}",
              help="Activities whose dates are recorded actuals vs the "
                   "file's remaining early dates.")
    t4.metric("Traced from", trace.terminal_code or "—")
    if trace.hybrid:
        st.warning(
            "⚠️ **Hybrid path** — the elected completion milestone has "
            "not been achieved. The tail beyond the data date is the "
            "programme's own forecast, not a record of what happened; it "
            "is labelled as such in the chain below.")
    for w in trace.warnings:
        (st.info if w.startswith("Logic corroboration")
         else st.warning)(w)
    if show_chain and trace.activities:
        st.markdown("**Traced chain** — terminal at the top of the "
                    "programme, walking back to the first activity.")
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
    """Full activity-level basis: controls + run + render. Returns trace."""
    end_code, gap, strict = terminal_picker(ordered, key_prefix)
    if end_code is None:
        st.info("No actually finished activities in the latest revision — "
                "nothing to trace.")
        return None
    trace = extract_actual_trace(
        ordered, end_task_code=end_code, max_gap_days=gap,
        allow_temporal_fallback=not strict)
    render_trace(trace)
    return trace


def stitched_basis(ordered, key_prefix: str, *, default_freq: float = 0.5):
    """Reconstructed-sequence basis: persistence threshold + run."""
    core_freq = st.slider(
        "Persistence threshold (share of revisions an activity must have "
        "been on the forecast path)", 0.2, 1.0, default_freq, 0.05,
        key=f"{key_prefix}_freq")
    st.session_state[sk.APAB_STITCH_FREQ] = core_freq
    stitch = analyse_asbuilt_path(
        ordered, core_min_frequency=core_freq,
        end_task_code=st.session_state.get(sk.CONTRACT_MS))
    for w in stitch.warnings:
        (st.info if w.startswith("Corroboration") else st.warning)(w)
    return stitch


def cross_check(stitch, trace) -> None:
    """Triangulation summary between the two reconstructions."""
    tri = triangulate(stitch, trace)
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Agreement",
              f"{tri.agreement_pct:.0f}%"
              if tri.agreement_pct is not None else "—",
              help="Share of the union of both reconstructions "
                   "identified by both.")
    a2.metric("Both methods", len(tri.both))
    a3.metric("Stitched only", len(tri.stitched_only))
    a4.metric("Trace only", len(tri.trace_only))
    for w in tri.warnings:
        (st.success if w.startswith("Method agreement")
         else st.warning)(w)
    return tri
