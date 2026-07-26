"""Umbrella grouping editor — AI proposes, the analyst confirms.

The grouping lives in ONE session key (sk.UMBRELLAS) so a work-package
breakdown defined here is the same breakdown everywhere it is used.
Adoption is single-action: typing a name in the table (or accepting an
AI proposal) IS the analyst's confirming act — there is no separate
"adopt" button to forget, which previously left the grouping defined
but the measurement switched off.

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
    merge_grouping, parse_umbrella_grouping,
)
from views._shared import ai_provider_block


def _adopt(groups: dict[str, list[str]]) -> None:
    st.session_state[sk.UMBRELLAS] = groups
    st.session_state[sk.UMBRELLA_ON] = bool(groups)


def umbrella_editor(rows: list[dict], path_codes: set[str],
                    key_prefix: str = "umb") -> dict[str, list[str]]:
    """Propose → confirm → auto-adopt. Returns the adopted grouping."""
    st.caption(
        "Group similar activities into the work packages the works were "
        "actually delivered in — Screed Works, Blockwork, Plastering, "
        "Electrical First / Second Fix, whatever fits this project — so "
        "the as-built critical path reads package by package instead of "
        "row by row. Grouping is presentation only: an umbrella's "
        "MEASURED dates come from its critical-path members alone, so "
        "grouping can never move the measured delay.")

    saved = dict(st.session_state.get(sk.UMBRELLAS) or {})
    names = {r["task_code"]: r["name"] for r in rows}
    valid = set(names)
    ed_key = f"{key_prefix}_editor"

    # ---- AI proposal ------------------------------------------------
    with st.expander("Propose work packages with AI (you confirm before "
                     "anything is applied)", expanded=not saved):
        scope_cp = st.toggle(
            "Only offer critical-path activities for grouping",
            value=True, key=f"{key_prefix}_scope_cp",
            help="Off-path activities can still be grouped for context, "
                 "but they never affect an umbrella's measured dates.")
        pool = [r for r in rows
                if not scope_cp or r["task_code"] in path_codes]
        st.write(f"{len(pool)} activities in scope for grouping.")
        # THE provider/model/key block — the very same code the
        # narrative panels render, model selector and own-key switch
        # included. Not a copy of the logic: the same function.
        provider, model, ai_key = ai_provider_block(f"{key_prefix}_ai")
        if st.button("Propose work packages", key=f"{key_prefix}_go",
                     disabled=not (pool and ai_key)):
            try:
                out = "".join(stream_narrative(
                    provider, ai_key,
                    build_umbrella_prompt(pool, path_codes),
                    model or None,
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
                st.error(
                    f"{exc.message}\n\nIf this is the managed endpoint "
                    "returning 403, its key has likely been rotated — "
                    "update NVIDIA_API_KEY in the secrets, or open the "
                    "AI settings above and use your own key. Grouping "
                    "by hand in the table below works regardless.")

        proposed = st.session_state.get(sk.UMBRELLA_PROPOSED) or []
        if proposed:
            st.dataframe(pd.DataFrame([{
                "Work package": g["label"],
                "Activities": len(g["codes"]),
                "Rationale": g.get("rationale", ""),
            } for g in proposed]), width="stretch", hide_index=True)
            if st.button("✔ Use this proposal (loads into the table — "
                         "edit or blank any name after)",
                         type="primary", key=f"{key_prefix}_load"):
                _adopt({g["label"]: list(g["codes"]) for g in proposed})
                # the editor must reseed from the new grouping, not
                # replay stale cell edits recorded under its old key
                st.session_state.pop(ed_key, None)
                st.rerun()

    # ---- confirmation table (also the manual fallback) --------------
    show_all = st.toggle(
        f"Show all {len(rows)} activities (default: the "
        f"{sum(1 for r in rows if r['task_code'] in path_codes)} on the "
        "critical path)",
        value=False, key=f"{key_prefix}_show_all",
        help="The critical-path activities are the ones whose grouping "
             "moves anything. Show all only to add off-path context "
             "members to a package.")
    # Path activities first, in as-built order; the rest only on demand.
    visible = ([r for r in rows if r["task_code"] in path_codes]
               + ([r for r in rows if r["task_code"] not in path_codes]
                  if show_all else []))
    visible_codes = [r["task_code"] for r in visible]
    assigned = {c: nm for nm, cs in saved.items() for c in cs}
    df = pd.DataFrame([{
        "Activity ID": c,
        "Activity": names[c][:60],
        "On CP": "✓" if c in path_codes else "",
        "Umbrella": assigned.get(c, ""),
    } for c in visible_codes])
    st.markdown("**Type an umbrella name against each activity** — the "
                "grouping applies as you edit; blank un-groups.")
    edited = st.data_editor(
        df, width="stretch", hide_index=True, height=360,
        disabled=["Activity ID", "Activity", "On CP"], key=ed_key)
    typed = {str(r["Activity ID"]): str(r.get("Umbrella") or "")
             for _, r in edited.iterrows()}
    groups = merge_grouping(saved, visible_codes, typed)
    if groups != saved:
        _adopt(groups)

    if groups and st.button("Clear the whole grouping",
                            key=f"{key_prefix}_clear"):
        _adopt({})
        st.session_state.pop(ed_key, None)
        st.session_state.pop(sk.UMBRELLA_PROPOSED, None)
        st.rerun()

    # ---- live preview of what the roll-up measures -------------------
    if groups:
        res = build_rollup(rows, groups, path_codes)
        prev = [u for u in res.umbrellas if u.measured]
        if prev:
            st.markdown("**Adopted — measured span per umbrella "
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
                "presentation, never added to the measurement. This "
                "grouping now applies everywhere as-built activities "
                "are presented.")
        for w in res.warnings:
            st.warning(w)
        for u in res.umbrellas:
            for w in u.warnings:
                st.caption(f"• {w}")
    return groups
