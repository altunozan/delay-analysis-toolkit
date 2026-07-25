"""Umbrella grouping editor — AI proposes, the analyst confirms.

The grouping lives in ONE session key (sk.UMBRELLAS) so a work-package
breakdown defined here is the same breakdown everywhere it is used.
Nothing here does arithmetic: the roll-up rules, and in particular the
critical-path-members-only measurement rule, live in programme/rollup.py.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import state as sk
from dcma.narrative import NarrativeError, stream_narrative
from programme import (
    UMBRELLA_SYSTEM_PROMPT, build_rollup, build_umbrella_prompt,
    parse_umbrella_grouping,
)
from views._shared import ai_credentials_panel


def _groups_from_editor(df) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for _, r in df.iterrows():
        name = str(r.get("Umbrella") or "").strip()
        if name:
            groups.setdefault(name, []).append(str(r["Activity ID"]))
    return groups


def umbrella_editor(rows: list[dict], path_codes: set[str],
                    key_prefix: str = "umb") -> dict[str, list[str]]:
    """Propose → confirm → persist. Returns the confirmed grouping."""
    st.caption(
        "Group the as-built activities into work packages a reader "
        "recognises — 'Electrical First Fix' rather than twenty rows of "
        "containment, trunking and sleeves. Grouping is presentation "
        "only: an umbrella's MEASURED dates come from its critical-path "
        "members alone, so grouping can never move the measured delay.")

    saved = dict(st.session_state.get(sk.UMBRELLAS) or {})
    # Only activities in the current comparison set can be grouped.
    codes = [r["task_code"] for r in rows]
    names = {r["task_code"]: r["name"] for r in rows}
    valid = set(codes)

    # ---- AI proposal ------------------------------------------------
    with st.expander("Propose work packages with AI (you confirm every "
                     "one)", expanded=not saved):
        st.caption(
            "The model only proposes groupings of activity codes that "
            "appear verbatim in the programme; any code it invents is "
            "dropped before you see it. Nothing is applied until you "
            "press Adopt below.")
        scope_cp = st.toggle(
            "Only offer critical-path activities for grouping",
            value=True, key=f"{key_prefix}_scope_cp",
            help="Off-path activities can still be grouped for context, "
                 "but they never affect an umbrella's measured dates.")
        pool = [r for r in rows
                if not scope_cp or r["task_code"] in path_codes]
        st.write(f"{len(pool)} activities in scope for grouping.")
        ai_key = st.session_state.get(sk.AI_KEY, "")
        if not ai_key:
            with st.expander("Register your AI (shared across the whole "
                             "app)"):
                ai_credentials_panel("umbrella")
            ai_key = st.session_state.get(sk.AI_KEY, "")
        if st.button("Propose work packages", key=f"{key_prefix}_go",
                     disabled=not (pool and ai_key)):
            try:
                out = "".join(stream_narrative(
                    st.session_state.get(sk.AI_PROVIDER, "nvidia"),
                    ai_key, build_umbrella_prompt(pool, path_codes),
                    st.session_state.get(sk.AI_MODEL, ""),
                    system=UMBRELLA_SYSTEM_PROMPT))
                proposed, dropped = parse_umbrella_grouping(out, valid)
                st.session_state[sk.UMBRELLA_PROPOSED] = proposed
                if dropped:
                    st.warning(
                        f"{dropped} proposed code(s) were not present in "
                        "the programme and were dropped.")
                if not proposed:
                    st.warning("No usable groups were returned — try "
                               "again, or type groups in the table.")
            except NarrativeError as exc:
                st.error(f"{exc.message}  You can still group by hand "
                         "in the table below.")

        proposed = st.session_state.get(sk.UMBRELLA_PROPOSED) or []
        if proposed:
            st.dataframe(pd.DataFrame([{
                "Work package": g["label"],
                "Activities": len(g["codes"]),
                "Rationale": g.get("rationale", ""),
            } for g in proposed]), width="stretch", hide_index=True)
            if st.button("Load this proposal into the table below",
                         key=f"{key_prefix}_load"):
                saved = {g["label"]: list(g["codes"]) for g in proposed}
                st.session_state[sk.UMBRELLAS] = saved
                st.rerun()

    # ---- confirmation table (also the manual fallback) --------------
    assigned = {c: nm for nm, cs in saved.items() for c in cs if c in valid}
    df = pd.DataFrame([{
        "Activity ID": c,
        "Activity": names[c][:60],
        "On CP": "✓" if c in path_codes else "",
        "Umbrella": assigned.get(c, ""),
    } for c in codes])
    st.markdown("**Confirm the grouping** — edit any name; blank leaves "
                "the activity standalone.")
    edited = st.data_editor(
        df, width="stretch", hide_index=True, height=360,
        disabled=["Activity ID", "Activity", "On CP"],
        key=f"{key_prefix}_editor")
    groups = _groups_from_editor(edited)

    c1, c2 = st.columns([1, 3])
    if c1.button("Adopt grouping", type="primary",
                 key=f"{key_prefix}_adopt"):
        st.session_state[sk.UMBRELLAS] = groups
        st.session_state[sk.UMBRELLA_ON] = bool(groups)
        st.success(f"{len(groups)} umbrella(s) adopted and shared with "
                   "every module that presents as-built activities.")
    if saved and c2.button("Clear grouping", key=f"{key_prefix}_clear"):
        st.session_state[sk.UMBRELLAS] = {}
        st.session_state[sk.UMBRELLA_ON] = False
        st.rerun()

    # ---- live preview of what the roll-up would measure --------------
    if groups:
        res = build_rollup(rows, groups, path_codes)
        prev = [u for u in res.umbrellas if u.measured]
        if prev:
            st.markdown("**Preview — measured span per umbrella "
                        "(critical-path members only):**")
            st.dataframe(pd.DataFrame([{
                "Umbrella": u.name,
                "Members": u.member_count,
                "On CP": u.on_path_count,
                "Measured start": (f"{u.actual_start:%Y-%m-%d}"
                                   if u.actual_start else "—"),
                "Measured finish": (f"{u.actual_finish:%Y-%m-%d}"
                                    if u.actual_finish else "—"),
                "Finish var (d)": u.finish_var_days,
                "Driving member": u.driving_member or "—",
                "Full group runs on (d)": u.presentation_only_days,
            } for u in prev]), width="stretch", hide_index=True)
            st.caption(
                "'Full group runs on' is how much later the whole work "
                "package ran than its critical-path portion — shown for "
                "presentation, never added to the measurement.")
        for w in res.warnings:
            st.warning(w)
        for u in res.umbrellas:
            for w in u.warnings:
                st.caption(f"• {w}")
    return groups
