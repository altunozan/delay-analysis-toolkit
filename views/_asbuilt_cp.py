"""Shared as-built critical-path definition — THE step-① breakdown.

Per elected milestone the toolkit computes BOTH candidate paths — the
as-built programme's own longest path, and the actual recorded sequence
(which catches unlinked-but-obvious hand-offs and sequence shifts) —
the analyst picks one, may hand-edit it, and may group it into umbrella
work packages (critical-path activities only). Rendered by BOTH the
standalone As-Built Critical Path page and APvAB step ①, and the
adopted election lives in ONE set of session keys, so the same analysis
cannot answer differently depending on which page you opened.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

import state as sk
from programme import (
    build_gantt_html, extract_actual_trace, extract_asbuilt_longest_path,
    group_tree, planned_vs_actual,
)
from programme.gantt_html import ASBUILT_CATEGORIES
from views._shared import _fkey
from views._umbrella import umbrella_editor

# --------------------------------------------------------------------- #
# cached candidate engines
# --------------------------------------------------------------------- #
@st.cache_data(show_spinner=False, max_entries=16)
def cached_longest(key: str, ms: str, _data):
    # the AS-BUILT longest path: programmed logic walked through
    # completed work to the earliest linked activity — it does not
    # stop at the data date the way a remaining-works trace would.
    cp = extract_asbuilt_longest_path(_data, end_task_code=ms)
    return ([(a.task_code, a.name) for a in cp.activities],
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


def cp_definition_block(ordered, baseline, *, key_prefix: str,
                        date_basis: str = "late"):
    """Milestone multiselect → dual candidates + divergence → pick +
    hand-edit → adopt → umbrella grouping (CP only) → linked gantt.

    Returns (paths, basis_by, groups, chosen_ms). The adopted state is
    project-wide (sk.APAB_PATHS / APAB_PATH_BASIS / APAB_MS /
    UMBRELLAS); only the widget keys differ per page.
    """
    latest_label, latest = ordered[-1]
    okey = tuple(_fkey(n) for n, _ in ordered)
    dd = latest.project.data_date if latest.project else None
    by_code = {t.task_code: t for t in latest.tasks if not t.is_loe_or_wbs}

    paths: dict = st.session_state.get(sk.APAB_PATHS) or {}
    basis_by: dict = st.session_state.get(sk.APAB_PATH_BASIS) or {}
    groups = st.session_state.get(sk.UMBRELLAS) or {}

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
    # a saved election can outlive the corpus that made it (new files
    # loaded mid-session) — a default OR STORED WIDGET STATE that is
    # not among the options is a hard StreamlitAPIException, so
    # sanitise both before rendering
    saved_ms = [c for c in (st.session_state.get(sk.APAB_MS) or [])
                if c in labels]
    wkey = f"{key_prefix}_ms_pick"
    if wkey in st.session_state:
        st.session_state[wkey] = [
            c for c in st.session_state[wkey] if c in labels]
    chosen_ms = st.multiselect(
        "Milestone(s) to measure to — each gets its own path, "
        "grouped separately in the gantt",
        options=list(labels),
        default=saved_ms or ([cms] if cms in labels
                             else list(labels)[:1]),
        format_func=lambda c: labels[c], key=f"{key_prefix}_ms_pick")
    st.session_state[sk.APAB_MS] = chosen_ms

    for ms in chosen_ms:
        st.markdown(f"##### Path to **{ms}** — "
                    f"{by_code[ms].name[:60]}")
        lp_path, lp_links = cached_longest(
            _fkey(latest_label), ms, latest)
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
            key=f"{key_prefix}_cand_{ms}", horizontal=True)
        cand = lp_path if pick.startswith("Longest") else sq_path
        cand_key = "lp" if pick.startswith("Longest") else "sq"
        all_labels = {c: f"{c} — {t.name[:52]}"
                      for c, t in by_code.items()}
        ekey = f"{key_prefix}_edit_{ms}_{cand_key}"
        if ekey in st.session_state:
            st.session_state[ekey] = [
                c for c in st.session_state[ekey] if c in all_labels]
        edited = st.multiselect(
            f"Hand-edit the path for {ms} (add or remove "
            "activities; edits are disclosed)",
            options=list(all_labels),
            default=[c for c, _ in cand],
            format_func=lambda c: all_labels[c],
            key=f"{key_prefix}_edit_{ms}_{cand_key}")
        if st.button(f"Adopt this path for {ms} "
                     f"({len(edited)} activities)",
                     type="primary", key=f"{key_prefix}_adopt_{ms}"):
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

    # ---- umbrella grouping: CP activities ONLY ----------------------
    union = {c for ms in chosen_ms for c, _ in paths.get(ms, [])}
    if union:
        st.markdown("##### Group the path into umbrella activities "
                    "(optional)")
        cp_rows = planned_vs_actual(baseline, latest, union,
                                    date_basis=date_basis)
        groups = umbrella_editor(cp_rows, union,
                                 key_prefix=f"{key_prefix}_umb")

        # ---- the adopted path(s) as a linked gantt ------------------
        st.markdown("##### The as-built critical path")
        roots = []
        for ms in chosen_ms:
            if ms not in paths:
                continue
            lp_path, lp_links = cached_longest(
                _fkey(latest_label), ms, latest)
            _, sq_links, _ = cached_sequence(okey, ms, ordered)
            # the adopted basis is durable state, not widget state —
            # a path adopted on the other page still links correctly
            links_src = (lp_links if str(basis_by.get(
                ms, "")).startswith("Longest") else sq_links)
            # stale codes from a previous corpus never reach the gantt
            members = [(c, n) for c, n in paths[ms] if c in by_code]
            codes = {c for c, _ in members}
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
            for c, n in members:
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

    return paths, basis_by, groups, chosen_ms


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
