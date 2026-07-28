"""Revision Comparison."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import state as sk
from programme import (
    assess_comparison_impact, attribute_completion_impact,
    build_comparison_prompt, build_comparison_xlsx, build_gantt_html,
    build_impact_xlsx, build_provenance, group_tree,
)
from programme.narrative import DEFAULT_TEMPLATES
from views._shared import (
    _fkey, ai_narrative_panel, cached_compare, gantt_fullscreen_button,
    get_parsed_files,
)

# the longest-path comparison colours: where the driving path itself
# changed between the revisions is exactly what the reader must see
LP_CATEGORIES = [
    {"key": "shared", "label": "on both driving paths",
     "color": "#14324A"},
    {"key": "joined", "label": "joined the path (new driver)",
     "color": "#9B3227"},
    {"key": "left", "label": "left the path", "color": "#B07A24"},
]


@st.cache_data(show_spinner=False, max_entries=8)
def _cached_impact(k0: str, k1: str, ms, _old, _new, l0, l1, _cmp):
    return assess_comparison_impact(
        _old, _new, l0, l1, comparison=_cmp, end_task_code=ms)


@st.cache_data(show_spinner=False, max_entries=8)
def _cached_attr(k0: str, k1: str, ms, _old, _new, l0, l1, _cmp, _imp):
    return attribute_completion_impact(
        _old, _new, l0, l1, comparison=_cmp, impact=_imp,
        end_task_code=ms)


@st.cache_data(show_spinner=False, max_entries=4)
def _cached_prov(keys: tuple, _ordered):
    return build_provenance(_ordered)


def _completion_strip(cmp, attr) -> None:
    """Completion at a glance: a handful of rows — the two completion
    dates, and each change that measurably moves completion drawn as
    its own before/after row. Open point = without / earlier, filled
    point = with / later; the label is the movement."""
    rows = []

    def add(label, x0, x1, delta, kind):
        if not (x0 and x1):
            return
        rows.append({"Row": label, "x0": x0, "x1": x1,
                     "lbl": f"{delta:+.0f}d" if delta is not None else "",
                     "kind": kind,
                     "x_lbl": max(x0, x1)})

    if cmp.old_finish and cmp.new_finish:
        add("Scheduled completion (as filed)", cmp.old_finish,
            cmp.new_finish,
            (cmp.new_finish - cmp.old_finish).days, "completion")
    add("Kernel completion (like-for-like)",
        attr.kernel_completion_old, attr.kernel_completion_new,
        attr.kernel_moved_days, "completion")
    movers = [a for a in attr.tested_changes
              if abs(a.contribution_days or 0) >= 0.5][:5]
    for a in movers:
        add(f"{a.category}: {a.ref}"[:46], a.completion_without,
            a.completion_with, a.contribution_days,
            "pushes later" if (a.contribution_days or 0) > 0
            else "pulls earlier")
    if not rows:
        return
    st.markdown("**Completion at a glance** — and the changes that "
                "move it")
    df = pd.DataFrame(rows)
    order = [r["Row"] for r in rows]
    y = alt.Y("Row:N", sort=order, title=None,
              axis=alt.Axis(labelLimit=330))
    color = alt.Color("kind:N", scale=alt.Scale(
        domain=["completion", "pushes later", "pulls earlier"],
        range=["#14324A", "#9B3227", "#3F6B4F"]),
        legend=alt.Legend(orient="top", title=None))
    st.altair_chart(alt.layer(
        alt.Chart(df).mark_rule(strokeWidth=2).encode(
            x=alt.X("x0:T", title=None), x2="x1:T", y=y, color=color),
        alt.Chart(df).mark_point(size=70, filled=False,
                                 strokeWidth=2).encode(
            x="x0:T", y=y, color=color),
        alt.Chart(df).mark_point(size=80, filled=True).encode(
            x="x1:T", y=y, color=color),
        alt.Chart(df).mark_text(align="left", dx=10, fontWeight="bold",
                                fontSize=11).encode(
            x="x_lbl:T", y=y, text="lbl:N", color=color),
    ).properties(height=30 * len(rows) + 40), width="stretch")
    if movers:
        st.caption(
            "Each change row: completion WITHOUT the change (open "
            "point) vs WITH it (filled) — the one-at-a-time kernel "
            "test. Only changes moving completion ≥ half a day are "
            "shown; the full table is under Impact & materiality "
            "screening.")
    else:
        st.caption(
            "No tested change moves completion by half a day or more — "
            "the movement between these revisions reads as progress "
            "slippage rather than programme editing.")


def comparison_tab() -> None:
    st.caption(
        "A change log between two programme revisions: scope, logic, "
        "durations, constraints, calendars — and retrospective changes to "
        "actualised dates."
    )
    files = get_parsed_files()
    inv = st.session_state.get(sk.INVENTORY)
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
    cmp = cached_compare(_fkey(old_name), _fkey(new_name),
                         old_name, new_name,
                         pool[old_name], pool[new_name])

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
    # filled from the impact section below once the attribution has run
    # — sits up here because it is the page's headline reading
    _strip = st.container()

    for w in cmp.warnings:
        st.warning(w)

    counts = {k: v for k, v in cmp.category_counts.items() if v}
    if not counts:
        st.success("No differences found between the two revisions.")
        return
    chart_df = pd.DataFrame(
        [{"Category": k, "Count": v} for k, v in counts.items()])
    _cc_base = alt.Chart(chart_df).encode(
        x=alt.X("Count:Q", title=None),
        y=alt.Y("Category:N", sort="-x", title=None,
                axis=alt.Axis(labelLimit=280)))
    st.altair_chart(
        (_cc_base.mark_bar(cornerRadius=2).encode(
            color=alt.condition(
                "datum.Category == 'Actual dates changed retrospectively'",
                alt.value("#9B3227"), alt.value("#14324A")),
            tooltip=["Category", "Count"])
         + _cc_base.mark_text(align="left", dx=5, fontSize=10.5)
           .encode(text="Count:Q")
         ).properties(height=28 * len(chart_df)),
        width="stretch",
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
                         width="stretch", hide_index=True)

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
        (f"🚩 Calendar definitions changed "
         f"({len(cmp.calendar_def_changes)})",
         _changes_table, cmp.calendar_def_changes),
        (f"🚩 Scheduling options changed "
         f"({len(cmp.sched_options_changes)})",
         _changes_table, cmp.sched_options_changes),
        (f"Renamed activities ({len(cmp.renamed)})", _changes_table,
         cmp.renamed),
    ]
    for label, fn, items in sections:
        if items:
            with st.expander(label):
                st.dataframe(fn(items), width="stretch",
                             hide_index=True)

    # ------------------------------------------------------------------ #
    # Module 6b — impact & materiality screening
    # ------------------------------------------------------------------ #
    st.divider()
    st.subheader("Impact & materiality screening")
    st.caption(
        "Places every change on the driving (longest) path of each "
        "revision, ranks changes by a disclosed screening score, and "
        "screens the later revision for out-of-sequence progress. "
        "A screening for analyst attention — not a causation finding."
    )
    imp = attr = None
    if st.toggle("Run impact screening", value=True,
                 key=f"impact_on_{old_name}_{new_name}"):
        with st.spinner("Tracing driving paths and ranking changes…"):
            imp = _cached_impact(
                _fkey(old_name), _fkey(new_name),
                st.session_state.get(sk.CONTRACT_MS),
                pool[old_name], pool[new_name], old_name, new_name, cmp)
        i1, i2, i3, i4 = st.columns(4)
        i1.metric("Changes on / near driving path",
                  f"{imp.band_counts.get('critical', 0)} / "
                  f"{imp.band_counts.get('near-critical', 0)}")
        i2.metric("Completion moved (cal. days)",
                  f"{imp.completion_moved_days:+.0f}"
                  if imp.completion_moved_days is not None else "—")
        i3.metric("Red-flag changes",
                  sum(1 for c in imp.ranked if c.red_flag))
        i4.metric("Out-of-sequence records", len(imp.oos_flags))
        for w in imp.warnings:
            st.warning(w)

        _BAND_ICON = {"critical": "🔴 critical",
                      "near-critical": "🟠 near-critical",
                      "off-path": "⚪ off-path",
                      "completed": "✅ completed",
                      "absent": "◌ absent"}
        top_n = 50
        rank_df = pd.DataFrame([{
            "Score": c.score,
            "Path position": _BAND_ICON.get(c.band, c.band),
            "Category": c.category,
            "Activity / Link": c.ref,
            "Name": c.name,
            "Change": c.detail,
            "Delta (d)": c.delta_days,
            "TF now (d)": c.total_float_new,
        } for c in imp.ranked[:top_n]])
        st.markdown(f"**Materiality rank** — top {min(top_n, len(imp.ranked))} "
                    f"of {len(imp.ranked)} changes:")
        st.dataframe(rank_df, width="stretch", hide_index=True)

        if imp.oos_flags:
            st.caption(
                f"ℹ️ {len(imp.oos_flags)} out-of-sequence record(s) "
                f"detected in '{new_name}' — screening, as-built "
                "relation fits and the repaired-.xer export live in the "
                "**Out-of-Sequence Repair** tab.")

        # ---- which changes MOVED completion (one-at-a-time revert) --
        st.markdown("#### Which changes moved completion?")
        st.caption(
            "Each revertible change is tested ONE AT A TIME: the later "
            "revision is re-scheduled by the CPM kernel with that "
            "single change undone, and the completion delta is that "
            "change's contribution — e.g. a lag change whose reversal "
            "pulls completion from 12 Aug back to 20 Jul contributed "
            "+23 days. Kernel-vs-kernel deltas; contributions interact "
            "and need not sum to the total movement.")
        with st.spinner("Re-scheduling with each change reverted…"):
            attr = _cached_attr(
                _fkey(old_name), _fkey(new_name),
                st.session_state.get(sk.CONTRACT_MS),
                pool[old_name], pool[new_name], old_name, new_name,
                cmp, imp)
        a1, a2, a3 = st.columns(3)
        a1.metric("Kernel completion, earlier",
                  f"{attr.kernel_completion_old:%d %b %Y}"
                  if attr.kernel_completion_old else "—")
        a2.metric("Kernel completion, later",
                  f"{attr.kernel_completion_new:%d %b %Y}"
                  if attr.kernel_completion_new else "—",
                  delta=(f"{attr.kernel_moved_days:+.0f} d"
                         if attr.kernel_moved_days is not None
                         else None), delta_color="inverse")
        _movers = [a for a in attr.tested_changes
                   if abs(a.contribution_days or 0) >= 0.5]
        a3.metric("Changes that move completion",
                  f"{len(_movers)} of {len(attr.tested_changes)} tested")
        with _strip:
            _completion_strip(cmp, attr)
        for w in attr.warnings:
            st.warning(w)
        if attr.changes:
            st.dataframe(pd.DataFrame([{
                "Category": a.category,
                "Change": a.ref,
                "Name": a.name[:40],
                "Detail": a.detail,
                "Completion WITH change":
                    (f"{a.completion_with:%Y-%m-%d}"
                     if a.completion_with else "—"),
                "WITHOUT (reverted)":
                    (f"{a.completion_without:%Y-%m-%d}"
                     if a.completion_without else "—"),
                "Contribution (d)": a.contribution_days,
                "Note": a.note,
            } for a in attr.changes[:40]]), width="stretch",
                hide_index=True, height=320)
            st.caption(
                "Positive contribution = the change pushed completion "
                "later; negative = it pulled completion earlier. "
                "Untested rows say why (completed side of the network, "
                "or beyond the test cap).")
        with st.expander("Attribution caveats (always apply)"):
            for c in attr.caveats:
                st.write("•", c)

        # ---- longest-path comparison, summary gantt -----------------
        st.markdown("#### Driving longest path — earlier vs later")
        by_o = {t.task_code: t for t in pool[old_name].tasks}
        by_n = {t.task_code: t for t in pool[new_name].tasks}
        o_codes = {c for c, _ in imp.lp_old}
        n_codes = {c for c, _ in imp.lp_new}

        def _lp_root(label, members, links, by_code, other_codes, tag):
            codes = {c for c, _ in members}
            succs: dict[str, list[str]] = {}
            for p_, s_ in links:
                if p_ in codes and s_ in codes:
                    succs.setdefault(p_, []).append(s_)
            acts = []
            for c, n in members[:40]:
                t = by_code.get(c)
                if t is None:
                    continue
                acts.append({
                    "id": c, "name": n,
                    "start": t.act_start or t.early_start,
                    "finish": t.act_finish or t.early_finish,
                    "milestone": t.is_milestone,
                    "status": ("shared" if c in other_codes else tag),
                    "lid": f"{label}:{c}",
                    "links": [f"{label}:{s}" for s in succs.get(c, [])]})
            return {"name": label, "activities": acts}

        _lp_html = build_gantt_html(
            group_tree([
                _lp_root(f"Longest path — {old_name}", imp.lp_old,
                         imp.lp_old_links, by_o, n_codes, "left"),
                _lp_root(f"Longest path — {new_name}", imp.lp_new,
                         imp.lp_new_links, by_n, o_codes, "joined"),
            ]),
            title="Driving path comparison",
            categories=LP_CATEGORIES)
        st.iframe(_lp_html, height=420)
        st.caption(
            "The driving longest path of each revision (capped at 40 "
            "rows each). Navy = on both paths; brick = joined the path "
            "in the later revision (the new drivers); ochre = left it. "
            "Where the paths differ is where the delay mechanism "
            "changed between the revisions.")
        gantt_fullscreen_button(_lp_html, "driving_path_comparison",
                                f"lp_fs_{_fkey(old_name)}")

        with st.expander("Screening caveats (always apply)"):
            for c in imp.caveats:
                st.write("•", c)
        st.download_button(
            "⬇️ Download impact screening (Excel)",
            data=build_impact_xlsx(imp),
            file_name="comparison_impact_screening.xlsx",
            mime="application/vnd.openxmlformats-officedocument."
                 "spreadsheetml.sheet",
            key=f"impact_dl_{old_name}_{new_name}",
        )

    # ------------------------------------------------------------------ #
    # Change provenance across the whole revision set
    # ------------------------------------------------------------------ #
    prov = None
    if len(files) >= 3:
        st.divider()
        st.subheader("Change provenance across revisions")
        st.caption(
            "Attributes each category of change to the update window "
            "that introduced it — the timeline of programme editing."
        )
        if st.toggle("Build provenance timeline", value=True,
                     key="prov_on"):
            ordered = [(r.file_name, pool[r.file_name])
                       for r in inv.revisions if r.file_name in pool]
            with st.spinner("Diffing consecutive revisions…"):
                prov = _cached_prov(
                    tuple(_fkey(n) for n, _ in ordered), ordered)
            for w in prov.warnings:
                st.warning(w)
            if prov.windows:
                col_labels = [
                    f"{w.old_data_date:%d %b %y} → "
                    f"{w.new_data_date:%d %b %y}"
                    if w.old_data_date and w.new_data_date
                    else f"{w.old_label} → {w.new_label}"
                    for w in prov.windows]
                matrix = {"Category": prov.categories}
                for lbl, w in zip(col_labels, prov.windows):
                    matrix[lbl] = [w.counts.get(c, 0)
                                   for c in prov.categories]
                mat_df = pd.DataFrame(matrix)
                move_row = {"Category": "Completion moved (cal. days)"}
                for lbl, w in zip(col_labels, prov.windows):
                    move_row[lbl] = (round(w.completion_moved_days)
                                     if w.completion_moved_days is not None
                                     else None)
                mat_df = pd.concat(
                    [mat_df, pd.DataFrame([move_row])], ignore_index=True)
                st.dataframe(mat_df, width="stretch", hide_index=True)
                st.caption(
                    "Drill into any window by selecting that revision "
                    "pair above; red-flag windows (retrospective actual "
                    "changes) deserve first attention.")
            with st.expander("Provenance caveats"):
                for c in prov.caveats:
                    st.write("•", c)

    with st.expander("Standing caveats (always apply)"):
        for c in cmp.caveats:
            st.write("•", c)

    # the report carries EVERYTHING the page computed: the diff, the
    # materiality rank, the completion attribution, the driving-path
    # comparison and the provenance timeline
    narrative = ai_narrative_panel(
        f"nar_cmp_{old_name}_{new_name}",
        lambda tmpl, i=imp, a=attr, p=prov: build_comparison_prompt(
            cmp, tmpl, impact=i, attribution=a, provenance=p),
        "comparison",
        DEFAULT_TEMPLATES["comparison"],
    )
    st.download_button(
        "⬇️ Download comparison report (Excel — all tables above)",
        data=build_comparison_xlsx(cmp, narrative, impact=imp,
                                   attribution=attr, provenance=prov),
        file_name="revision_comparison_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
