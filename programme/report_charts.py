"""Chart builders for the assembled Word report (Module 11).

Rebuilds each module's headline chart as a standalone Altair spec and
renders it to PNG via vl-convert, so the Word report carries the same
visuals as the app. Print-friendly (light background), UI-independent.
"""

from __future__ import annotations

import altair as alt
import pandas as pd

PLANNED_C = "#3b76c4"
RECORDED_C = "#cf222e"
GOOD_C = "#1a7f37"
ACCENT_C = "#e8a33d"


def chart_png(chart: alt.Chart, scale: float = 2.0) -> bytes:
    import vl_convert as vlc
    return vlc.vegalite_to_png(chart.to_json(), scale=scale)


def milestone_chart(series, top_n: int = 10) -> alt.Chart | None:
    """Forecast/actual date per data date for the most-slipped milestones."""
    tracked = [s for s in series if s.total_shift_days is not None]
    tracked.sort(key=lambda s: -(s.total_shift_days or 0))
    rows = []
    for s in tracked[:top_n]:
        for p in s.points:
            if p.value_date is None:
                continue
            rows.append({
                "Data date": p.data_date,
                "Milestone date": p.value_date,
                "Milestone": f"{s.key} · {s.name[:32]}",
            })
    if not rows:
        return None
    return (alt.Chart(pd.DataFrame(rows))
            .mark_line(point=True)
            .encode(
                x=alt.X("Data date:T", axis=alt.Axis(format="%b %Y")),
                y=alt.Y("Milestone date:T", scale=alt.Scale(zero=False),
                        axis=alt.Axis(format="%b %Y")),
                color=alt.Color("Milestone:N",
                                legend=alt.Legend(orient="bottom",
                                                  columns=2, title=None)))
            .properties(width=620, height=300,
                        title="Milestone forecast movement by data date"))


def comparison_chart(cmp) -> alt.Chart | None:
    counts = {k: v for k, v in cmp.category_counts.items() if v}
    if not counts:
        return None
    df = pd.DataFrame([{"Category": k, "Count": v}
                       for k, v in counts.items()])
    return (alt.Chart(df).mark_bar(cornerRadius=2)
            .encode(
                x=alt.X("Count:Q", title=None),
                y=alt.Y("Category:N", sort="-x", title=None,
                        axis=alt.Axis(labelLimit=300)),
                color=alt.condition(
                    "datum.Category == 'Actual dates changed retrospectively'",
                    alt.value(RECORDED_C), alt.value(PLANNED_C)))
            .properties(width=560, height=26 * len(df),
                        title=f"Changes: {cmp.old_label} → {cmp.new_label}"))


def windows_trajectory_chart(res) -> alt.Chart | None:
    traj = []
    for w in res.windows:
        if w.start and w.finish_old:
            traj.append({"Data date": w.start, "Completion": w.finish_old})
    last = res.windows[-1] if res.windows else None
    if last and last.end and last.finish_new:
        traj.append({"Data date": last.end, "Completion": last.finish_new})
    if len(traj) < 2:
        return None
    return (alt.Chart(pd.DataFrame(traj))
            .mark_line(point=True, interpolate="step-after", color=RECORDED_C)
            .encode(
                x=alt.X("Data date:T", axis=alt.Axis(format="%b %Y")),
                y=alt.Y("Completion:T", title="Scheduled completion",
                        scale=alt.Scale(zero=False),
                        axis=alt.Axis(format="%b %Y")))
            .properties(width=620, height=280,
                        title="Completion trajectory across data dates"))


def windows_movement_chart(res) -> alt.Chart | None:
    mv = [{"Window": f"W{w.index}", "Movement (d)": w.movement_days}
          for w in res.windows if w.movement_days is not None]
    if not mv:
        return None
    return (alt.Chart(pd.DataFrame(mv)).mark_bar(cornerRadius=2)
            .encode(
                x=alt.X("Window:N", sort=None, title=None),
                y=alt.Y("Movement (d):Q"),
                color=alt.condition("datum['Movement (d)'] > 0",
                                    alt.value(RECORDED_C),
                                    alt.value(GOOD_C)))
            .properties(width=620, height=240,
                        title="Completion movement per window"))


def scurve_chart(pr) -> alt.Chart | None:
    rows = ([{"Date": p.date, "Cum %": p.cum_pct, "Series": "Planned"}
             for p in pr.planned_curve]
            + [{"Date": p.date, "Cum %": p.cum_pct, "Series": "As-recorded"}
               for p in pr.recorded_curve])
    if not rows:
        return None
    layers = [alt.Chart(pd.DataFrame(rows)).mark_line(point=True)
              .encode(
                  x=alt.X("Date:T", title=None,
                          axis=alt.Axis(format="%b %Y")),
                  y=alt.Y("Cum %:Q", title="Cumulative progress (%)",
                          scale=alt.Scale(domain=[0, 100])),
                  color=alt.Color("Series:N", title=None,
                                  scale=alt.Scale(
                                      domain=["Planned", "As-recorded"],
                                      range=[PLANNED_C, RECORDED_C]),
                                  legend=alt.Legend(orient="bottom")))]
    pts = [{"Date": rp.data_date, "Cum %": rp.recorded_pct}
           for rp in pr.revision_points
           if rp.data_date and rp.recorded_pct is not None]
    if pts:
        layers.append(alt.Chart(pd.DataFrame(pts)).mark_point(
            shape="diamond", size=140, filled=True, color=ACCENT_C)
            .encode(x="Date:T", y="Cum %:Q"))
    return alt.layer(*layers).properties(
        width=620, height=300, title="Progress S-curve (planned vs as-recorded)")


def float_chart(fe) -> alt.Chart | None:
    rows = [{"Revision": s.label[:28], "order": i,
             "Median TF (d)": s.median_float,
             "Negative-float count": s.negative_count}
            for i, s in enumerate(fe.snapshots) if s.median_float is not None]
    if not rows:
        return None
    df = pd.DataFrame(rows)
    base = alt.Chart(df).encode(
        x=alt.X("Revision:N", sort=alt.SortField("order"), title=None))
    bars = base.mark_bar(color=RECORDED_C, opacity=0.75).encode(
        y=alt.Y("Negative-float count:Q",
                axis=alt.Axis(titleColor=RECORDED_C)))
    line = base.mark_line(point=True, color=PLANNED_C).encode(
        y=alt.Y("Median TF (d):Q", axis=alt.Axis(titleColor=PLANNED_C)))
    return alt.layer(bars, line).resolve_scale(y="independent").properties(
        width=620, height=260, title="Float profile by revision")


def resources_chart(rl, top_n: int = 8) -> alt.Chart | None:
    keep = {r.short_name for r in rl.resources[:top_n]}
    rows = [{"Month": p.month_end, "Resource": p.resource,
             "Quantity": round(p.qty, 1)}
            for p in rl.histogram if p.resource in keep]
    if not rows:
        return None
    return (alt.Chart(pd.DataFrame(rows)).mark_bar()
            .encode(
                x=alt.X("yearmonth(Month):T", title=None,
                        axis=alt.Axis(format="%b %Y")),
                y=alt.Y("Quantity:Q", title="Planned quantity / month"),
                color=alt.Color("Resource:N",
                                legend=alt.Legend(orient="bottom",
                                                  title=None)))
            .properties(width=620, height=280,
                        title="Planned resource loading by month"))


def critical_path_chart(cp, max_rows: int = 60) -> alt.Chart | None:
    """Compact gantt of the critical chain in early-start order."""
    shown = [a for a in cp.critical
             if a.early_start and (a.early_finish or a.is_milestone)]
    shown = shown[:max_rows]
    if not shown:
        return None
    order, bars, points = [], [], []
    for a in shown:
        lbl = f"{a.task_code} · {a.name[:34]}"
        order.append(lbl)
        if a.is_milestone:
            points.append({"Activity": lbl,
                           "Date": a.early_finish or a.early_start})
        elif a.early_finish:
            bars.append({"Activity": lbl, "Start": a.early_start,
                         "Finish": a.early_finish})
    y = alt.Y("Activity:N", sort=order, title=None,
              axis=alt.Axis(labelLimit=280, labelFontSize=8))
    layers = []
    if bars:
        layers.append(alt.Chart(pd.DataFrame(bars))
                      .mark_bar(height=5, color=RECORDED_C)
                      .encode(x=alt.X("Start:T", title=None,
                                      axis=alt.Axis(format="%b %Y")),
                              x2="Finish:T", y=y))
    if points:
        layers.append(alt.Chart(pd.DataFrame(points))
                      .mark_point(shape="diamond", size=60, filled=True,
                                  color=RECORDED_C)
                      .encode(x="Date:T", y=y))
    if not layers:
        return None
    title = "Planned critical path (early-start order)"
    if len(cp.critical) > max_rows:
        title += f" — first {max_rows} of {len(cp.critical)} activities"
    return alt.layer(*layers).properties(
        width=620, height=max(180, 11 * len(order)), title=title)

def variance_chart(var) -> alt.Chart | None:
    rows = [{"Group": g.code_value[:40],
             "Finish delta (d)": g.finish_delta_days}
            for g in var.groups if g.finish_delta_days is not None]
    if not rows:
        return None
    df = pd.DataFrame(rows).sort_values("Finish delta (d)", ascending=False)
    return (alt.Chart(df).mark_bar(cornerRadius=2)
            .encode(
                x=alt.X("Finish delta (d):Q"),
                y=alt.Y("Group:N", sort="-x", title=None,
                        axis=alt.Axis(labelLimit=280)),
                color=alt.condition("datum['Finish delta (d)'] > 0",
                                    alt.value(RECORDED_C),
                                    alt.value(GOOD_C)))
            .properties(width=560, height=max(120, 24 * len(df)),
                        title=f"Finish slippage by {var.code_type_name}"))

def asbuilt_persistence_chart(res, max_rows: int = 70) -> alt.Chart | None:
    """Actual-date gantt of ever-critical activities; colour = persistence.

    Sequential encoding (one hue, light->dark): darker red = on the
    forecast critical path in a larger share of revisions.
    """
    rows = []
    for e in res.persistence:
        if e.act_start is None:
            continue
        rows.append({
            "Activity": f"{e.task_code} · {e.name[:34]}",
            "Start": e.act_start,
            "Finish": e.act_finish or e.act_start,
            "Persistence": round(100 * e.frequency),
            "On path": f"{e.times_on_path}/{e.times_eligible} revisions",
        })
    if not rows:
        return None
    rows.sort(key=lambda r: r["Start"])
    rows = rows[:max_rows]
    order = [r["Activity"] for r in rows]
    title = "As-built criticality persistence (actual dates)"
    if len(res.persistence) > max_rows:
        title += f" — first {max_rows} by actual start"
    return (alt.Chart(pd.DataFrame(rows))
            .mark_bar(height=6, cornerRadius=2)
            .encode(
                x=alt.X("Start:T", title=None,
                        axis=alt.Axis(format="%b %Y")),
                x2="Finish:T",
                y=alt.Y("Activity:N", sort=order, title=None,
                        axis=alt.Axis(labelLimit=280, labelFontSize=8)),
                color=alt.Color(
                    "Persistence:Q",
                    scale=alt.Scale(scheme="reds", domain=[0, 100]),
                    legend=alt.Legend(title="% of revisions critical",
                                      orient="bottom", gradientLength=220)),
                tooltip=["Activity", "On path",
                         alt.Tooltip("Start:T", format="%d %b %Y"),
                         alt.Tooltip("Finish:T", format="%d %b %Y")])
            .properties(width=620, height=max(200, 10 * len(order)),
                        title=title))

# Fixed stage palette: 9 hues in fixed order + neutral for Unclassified.
STAGE_COLORS = {
    "Design, Submittals & Approvals": "#3b76c4",
    "Procurement & Fabrication": "#8a63d2",
    "Enabling, Access & MEP": "#0e8388",
    "Structure & Screed": "#8d6e63",
    "Ceilings & Closures": "#e8a33d",
    "Walls, Glazing & Cladding": "#c2185b",
    "Joinery, Doors & Flooring": "#5c9e31",
    "Finishes & Fit-Out": "#f4511e",
    "Snagging & Handover": "#546e7a",
    "Unclassified": "#9e9e9e",
}


def sequence_matrix_chart(seq, max_fronts: int = 25) -> alt.Chart | None:
    """Front x stage actual bands: y = work front, colour = stage."""
    keep = [f for f, _ in seq.fronts_by_finish[:max_fronts]]
    if not keep:
        return None
    order = list(reversed(keep))          # earliest-finishing at top
    rows = []
    for b in seq.bands:
        if b.front not in keep or b.act_start is None:
            continue
        rows.append({
            "Front": b.front,
            "Stage": b.stage,
            "Start": b.act_start,
            "Finish": b.act_finish or b.act_start,
            "Activities": b.activity_count,
        })
    if not rows:
        return None
    stages = [s for s in seq.stage_order
              if any(r["Stage"] == s for r in rows)]
    return (alt.Chart(pd.DataFrame(rows))
            .mark_bar(height=7, cornerRadius=2, opacity=0.9)
            .encode(
                x=alt.X("Start:T", title=None,
                        axis=alt.Axis(format="%b %Y")),
                x2="Finish:T",
                y=alt.Y("Front:N", sort=order, title=None,
                        axis=alt.Axis(labelLimit=220)),
                color=alt.Color(
                    "Stage:N",
                    scale=alt.Scale(domain=stages,
                                    range=[STAGE_COLORS.get(s, "#9e9e9e")
                                           for s in stages]),
                    legend=alt.Legend(orient="bottom", columns=3,
                                      title=None)),
                tooltip=["Front", "Stage", "Activities",
                         alt.Tooltip("Start:T", format="%d %b %Y"),
                         alt.Tooltip("Finish:T", format="%d %b %Y")])
            .properties(width=620, height=max(220, 16 * len(keep)),
                        title="Construction sequence by work front "
                              "(actual dates)"))


def tia_paths_chart(res) -> alt.Chart | None:
    """Static pre- vs post-impact driving paths for the Word report."""
    rows = []
    for series, path in (("Pre-impact", getattr(res, "path_pre", [])),
                         ("Post-impact", getattr(res, "path_post", []))):
        for p in path[:30]:
            if not p.get("start") or not p.get("finish"):
                continue
            cat = ("Fragnet" if (series == "Post-impact"
                                 and p.get("fragnet")) else series)
            rows.append({"Row": f"{series}: {p['id']}",
                         "Series": cat, "Start": p["start"],
                         "Finish": p["finish"]})
    if not rows:
        return None
    order = [r["Row"] for r in rows]
    return (alt.Chart(pd.DataFrame(rows))
            .mark_bar(height=8, cornerRadius=2)
            .encode(
                x=alt.X("Start:T", title=None,
                        axis=alt.Axis(format="%b %Y")),
                x2="Finish:T",
                y=alt.Y("Row:N", sort=order, title=None,
                        axis=alt.Axis(labelLimit=280, labelFontSize=8)),
                color=alt.Color("Series:N", scale=alt.Scale(
                    domain=["Pre-impact", "Post-impact", "Fragnet"],
                    range=["#4c8ede", "#cf222e", "#e8a33d"]),
                    legend=alt.Legend(orient="bottom", title=None)))
            .properties(width=620, height=max(160, 12 * len(order)),
                        title="Driving paths — pre vs post impact"))
