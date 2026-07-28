"""Revision Comparison."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import state as sk
from programme import (
    assess_comparison_impact, attribute_completion_impact,
    build_comparison_prompt, build_comparison_xlsx,
    build_impact_xlsx, build_provenance,
)
from programme.narrative import DEFAULT_TEMPLATES
from views._shared import (
    _fkey, ai_narrative_panel, cached_compare, get_parsed_files,
)


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


def _strip_chart(cmp, attr):
    """The delay bridge: what leads to what.

    Reads top to bottom as a chain — the earlier revision's completion,
    then each change the one-at-a-time kernel test says moves it (brick
    = pushes later, green = pulls earlier), then everything the tests
    cannot attribute (progress slippage, untested categories) as the
    residual, arriving at the later revision's completion. The x-axis
    is DAYS of movement, so a ±1-day change and a +500-day slippage
    sit on one honest scale. Thin line segments, not blocks.

    Returns (chart, movers, residual) or (None, [], None)."""
    c_old = cmp.old_finish or attr.kernel_completion_old
    c_new = cmp.new_finish or attr.kernel_completion_new
    if not (c_old and c_new):
        return None, [], None
    total = round((c_new - c_old).total_seconds() / 86400, 1)
    movers = sorted(
        [a for a in attr.tested_changes
         if abs(a.contribution_days or 0) >= 0.5],
        key=lambda a: -abs(a.contribution_days or 0))[:6]
    residual = round(total - sum(a.contribution_days or 0
                                 for a in movers), 1)

    A_OLD = "① Completion — earlier revision"
    A_NEW = "④ Completion — later revision"
    R_ROW = "③ Progress slippage & untested changes"
    steps, anchors, txts = [], [], []
    order = [A_OLD]
    anchors.append({"Row": A_OLD, "x": 0.0, "kind": "completion",
                    "lbl": f"{c_old:%d %b %Y}"})

    run = 0.0
    for i, a in enumerate(movers, start=1):
        d = a.contribution_days or 0.0
        row = f"② {a.category.replace(' changes', '')}: {a.ref}"[:40]
        order.append(row)
        steps.append({"Row": row, "x0": run, "x1": run + d,
                      "kind": ("pushes later" if d > 0
                               else "pulls earlier")})
        txts.append({"Row": row, "x": max(run, run + d),
                     "lbl": f"{d:+.1f}d",
                     "kind": "pushes later" if d > 0
                     else "pulls earlier"})
        run += d
    if abs(residual) >= 0.05 or not movers:
        order.append(R_ROW)
        steps.append({"Row": R_ROW, "x0": run, "x1": run + residual,
                      "kind": ("pushes later" if residual > 0
                               else "pulls earlier")})
        txts.append({"Row": R_ROW, "x": max(run, run + residual),
                     "lbl": f"{residual:+.0f}d",
                     "kind": "pushes later" if residual > 0
                     else "pulls earlier"})
    order.append(A_NEW)
    anchors.append({"Row": A_NEW, "x": total, "kind": "completion",
                    "lbl": f"{c_new:%d %b %Y}  ({total:+.0f}d)"})

    lo = min([0.0, total] + [s["x0"] for s in steps]
             + [s["x1"] for s in steps])
    hi = max([0.0, total] + [s["x0"] for s in steps]
             + [s["x1"] for s in steps])
    pad = max((hi - lo) * 0.22, 3.0)
    # A step smaller than ~1.5% of the axis is sub-pixel as a segment:
    # mark it with a diamond so the row never renders blank. The label
    # carries the exact figure either way — the marker is a locator,
    # never a widened (and so overstated) magnitude.
    tiny_cut = max((hi - lo) * 0.015, 0.05)
    tiny = [s for s in steps if abs(s["x1"] - s["x0"]) < tiny_cut]
    steps = [s for s in steps if abs(s["x1"] - s["x0"]) >= tiny_cut]
    y = alt.Y("Row:N", sort=order, title=None,
              axis=alt.Axis(labelLimit=330, labelFontSize=11,
                            labelPadding=6, domain=False, ticks=False))
    xscale = alt.Scale(domain=[lo - pad * 0.35, hi + pad])
    x = alt.X("x0:Q",
              title="calendar days of completion movement "
                    "(0 = earlier revision)",
              scale=xscale)
    color = alt.Color("kind:N", scale=alt.Scale(
        domain=["completion", "pushes later", "pulls earlier"],
        range=["#14324A", "#9B3227", "#3F6B4F"]),
        legend=alt.Legend(orient="top", title=None))

    layers = []
    if steps:
        # thin line segments, the format that reads cleanly
        layers.append(alt.Chart(pd.DataFrame(steps)).mark_rule(
            strokeWidth=7, strokeCap="butt").encode(
            x=x, x2="x1:Q", y=y, color=color,
            tooltip=["Row:N", "x0:Q", "x1:Q"]))
    if tiny:
        tdf = pd.DataFrame([{"Row": s["Row"], "kind": s["kind"],
                             "x": (s["x0"] + s["x1"]) / 2}
                            for s in tiny])
        layers.append(alt.Chart(tdf).mark_point(
            shape="diamond", size=110, filled=True).encode(
            x=alt.X("x:Q", title=None, scale=xscale), y=y, color=color))
    adf = pd.DataFrame(anchors)
    layers.append(alt.Chart(adf).mark_rule(
        strokeWidth=2, strokeDash=[4, 3], color="#14324A").encode(
        x=alt.X("x:Q", title=None, scale=xscale)))
    layers.append(alt.Chart(adf).mark_point(
        shape="diamond", size=150, filled=True).encode(
        x=alt.X("x:Q", title=None, scale=xscale), y=y, color=color))
    layers.append(alt.Chart(adf).mark_text(
        align="left", dx=12, fontWeight="bold", fontSize=11.5).encode(
        x=alt.X("x:Q", title=None, scale=xscale), y=y, text="lbl:N", color=color))
    if txts:
        layers.append(alt.Chart(pd.DataFrame(txts)).mark_text(
            align="left", dx=10, fontWeight="bold",
            fontSize=11).encode(
            x=alt.X("x:Q", title=None, scale=xscale), y=y, text="lbl:N",
            color=color))
    chart = (alt.layer(*layers)
             .properties(height=32 * len(order) + 46)
             .configure_axisY(grid=False)
             .configure_axisX(grid=True, gridColor="#E4EDF4")
             .configure_view(stroke=None))
    return chart, movers, residual


def _completion_strip(cmp, attr) -> None:
    chart, movers, residual = _strip_chart(cmp, attr)
    if chart is None:
        return
    st.markdown(
        f"**Completion at a glance — what leads to what** &nbsp; "
        f"`{cmp.old_label[:34]}` → `{cmp.new_label[:34]}`")
    st.altair_chart(chart, width="stretch")
    if movers:
        st.caption(
            "Read it top to bottom: ① where the earlier revision "
            "finished, ② each change the one-at-a-time kernel test "
            "shows moving completion (brick pushes it later, green "
            "pulls it earlier), ③ everything the tests cannot "
            "attribute — progress slippage and the untested categories "
            "(constraints, calendars, scope) — and ④ where the later "
            "revision finishes. Each segment starts where the one "
            "above ended, so the chain reads as a summary of every "
            "table below.")
    else:
        st.caption(
            f"No tested change moves completion by half a day or more: "
            f"the whole {residual:+.0f}-day movement falls to progress "
            "slippage and the untested categories (constraints, "
            "calendars, scope), not to the programme edits tested "
            "here.")


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
    cat_chart = (_cc_base.mark_bar(cornerRadius=2).encode(
        color=alt.condition(
            "datum.Category == 'Actual dates changed retrospectively'",
            alt.value("#9B3227"), alt.value("#14324A")),
        tooltip=["Category", "Count"])
        + _cc_base.mark_text(align="left", dx=5, fontSize=10.5)
        .encode(text="Count:Q")
        ).properties(height=28 * len(chart_df))
    st.altair_chart(cat_chart, width="stretch")

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
    # materiality rank, the completion attribution and the provenance
    # timeline — with the page's charts attached as leading figures
    def _cmp_figures(a=attr, cc=cat_chart):
        from programme.report_charts import chart_png
        figs = []
        if a is not None:
            ch, _m, _r = _strip_chart(cmp, a)
            if ch is not None:
                figs.append(("Completion at a glance — and the changes "
                             "that move it", chart_png(ch)))
        figs.append(("Change mix between the revisions", chart_png(cc)))
        return figs or None

    narrative = ai_narrative_panel(
        f"nar_cmp_{old_name}_{new_name}",
        lambda tmpl, i=imp, a=attr, p=prov: build_comparison_prompt(
            cmp, tmpl, impact=i, attribution=a, provenance=p),
        "comparison",
        DEFAULT_TEMPLATES["comparison"],
        chart_png_builder=_cmp_figures,
    )
    st.download_button(
        "⬇️ Download comparison report (Excel — all tables above)",
        data=build_comparison_xlsx(cmp, narrative, impact=imp,
                                   attribution=attr, provenance=prov),
        file_name="revision_comparison_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
