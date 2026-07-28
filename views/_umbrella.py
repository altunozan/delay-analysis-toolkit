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
    UMBRELLA_SYSTEM_PROMPT, build_rollup, critique_grouping,
    merge_grouping, refine_grouping,
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
        if st.button("Propose work packages (up to 3 AI rounds — a "
                     "deterministic reviewer scores each round, best "
                     "round kept)", key=f"{key_prefix}_go",
                     disabled=not (pool and ai_key)):
            try:
                def _call(prompt: str) -> str:
                    return "".join(stream_narrative(
                        provider, ai_key, prompt, model or None,
                        system=UMBRELLA_SYSTEM_PROMPT))

                with st.spinner("Proposing, critiquing, refining…"):
                    best, best_crit, traj = refine_grouping(
                        _call, pool, path_codes, valid)
                st.session_state[sk.UMBRELLA_PROPOSED] = best or []
                st.session_state[sk.UMBRELLA_ROUNDS] = traj
                dropped = sum(t.get("dropped") or 0 for t in traj)
                if dropped:
                    st.warning(
                        f"{dropped} proposed code(s) were not present in "
                        "the programme and were dropped.")
                if not best:
                    st.warning("No usable groups were returned — try "
                               "again, or type groups in the table.")
            except NarrativeError as exc:
                st.error(
                    f"{exc.message}\n\nIf this is the managed endpoint "
                    "returning 403, its key has likely been rotated — "
                    "update NVIDIA_API_KEY in the secrets, or open the "
                    "AI settings above and use your own key. Grouping "
                    "by hand in the table below works regardless.")

        traj = st.session_state.get(sk.UMBRELLA_ROUNDS) or []
        if len(traj) > 1 or (traj and traj[0].get("defects")):
            scored = [t for t in traj if t.get("score") is not None]
            best_rnd = (max(scored, key=lambda t: t["score"])["round"]
                        if scored else None)
            st.dataframe(pd.DataFrame([{
                "Round": t["round"],
                "Score": t["score"] if t["score"] is not None else "—",
                "Packages": t["packages"],
                "Defects": (t["defects"] if t["defects"] is not None
                            else "—"),
                "": "✔ kept" if t["round"] == best_rnd else "",
            } for t in traj]), width="stretch", hide_index=True)
            st.caption(
                "Each round the model revises its own grouping against "
                "the reviewer's defect list; the reviewer is arithmetic "
                "on the rows (coverage, spans, ID families, name "
                "coherence), never the model grading itself. The "
                "best-scoring round is kept — revisions do not improve "
                "monotonically.")
            last_best = next((t for t in traj
                              if t["round"] == best_rnd), None)
            if last_best and last_best.get("top_defects"):
                st.caption("Remaining defects to fix by hand: "
                           + last_best["top_defects"])
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
        st.session_state.pop(sk.UMBRELLA_ROUNDS, None)
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
        # the same deterministic reviewer that drives the AI rounds,
        # run on whatever is adopted — typed by hand or proposed
        crit = critique_grouping(groups, rows, path_codes)
        if crit.defects:
            st.caption(
                f"Reviewer: {crit.score:.0f}/100 — "
                + "; ".join(d.detail for d in crit.defects[:3])
                + (" …" if len(crit.defects) > 3 else ""))
        else:
            st.caption(f"Reviewer: {crit.score:.0f}/100 — no defects "
                       "found in the adopted grouping.")
    return groups
