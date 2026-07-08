"""ChartSpec → interactive Plotly figure (the dashboard renderer).

Pure translation layer: every number drawn here comes from the spec's own
resolved_* helpers, so the web preview and the PowerPoint export always agree.
"""

from __future__ import annotations

import plotly.graph_objects as go

from specs import (
    BarSpec, ButterflySpec, ChartSpec, GanttSpec, LineSpec, MekkoSpec,
    PieSpec, ProcessSpec, ScatterSpec, TableSpec, WaterfallSpec,
    decode_cell, weekend_ranges,
)
from theme import Theme

_SEMANTIC = ("accent", "positive", "negative", "warning", "muted")


def _semantic_color(key: str | None, theme: Theme) -> str | None:
    return getattr(theme, key) if key in _SEMANTIC else None


def render(spec: ChartSpec, theme: Theme) -> go.Figure:
    if isinstance(spec, BarSpec):
        return _bar(spec, theme)
    if isinstance(spec, WaterfallSpec):
        return _waterfall(spec, theme)
    if isinstance(spec, GanttSpec):
        return _gantt(spec, theme)
    if isinstance(spec, MekkoSpec):
        return _mekko(spec, theme)
    if isinstance(spec, TableSpec):
        return _table(spec, theme)
    if isinstance(spec, LineSpec):
        return _lines(spec, theme)
    if isinstance(spec, PieSpec):
        return _pie(spec, theme)
    if isinstance(spec, ButterflySpec):
        return _butterfly(spec, theme)
    if isinstance(spec, ScatterSpec):
        return _scatter(spec, theme)
    if isinstance(spec, ProcessSpec):
        return _process(spec, theme)
    raise TypeError(f"No plotly renderer for {type(spec).__name__}")


def _layout(fig: go.Figure, theme: Theme, title: str) -> None:
    fig.update_layout(
        title={"text": f"<b>{title}</b>", "x": 0.01, "xanchor": "left",
               "font": {"size": 17, "color": theme.text}},
        font={"family": theme.font, "size": 13, "color": theme.text},
        paper_bgcolor="white",
        plot_bgcolor="white",
        margin={"l": 40, "r": 40, "t": 60, "b": 40},
        legend={"orientation": "h", "yanchor": "bottom", "y": -0.18,
                "xanchor": "left", "x": 0},
        bargap=0.35,
    )


# ---------------------------------------------------------------------- #
# Bar / column
# ---------------------------------------------------------------------- #

def _bar(spec: BarSpec, theme: Theme) -> go.Figure:
    if (spec.axis_break and spec.orientation == "vertical"
            and spec.mode in ("stacked", "clustered")):
        return _bar_broken(spec, theme)

    n = len(spec.categories)
    idx = list(range(n))
    horizontal = spec.orientation == "horizontal"
    stacked = spec.mode in ("stacked", "stacked100")
    totals = spec.totals()

    fig = go.Figure()
    for k, s in enumerate(spec.series):
        vals = list(s.values)
        if spec.mode == "stacked100":
            vals = [
                (v or 0.0) / t * 100.0 if (t := totals[i]) else 0.0
                for i, v in enumerate(vals)
            ]
        text = None
        if spec.show_values:
            if spec.mode == "stacked100":
                text = [f"{v:.0f}%" if v is not None else "" for v in vals]
            else:
                text = [spec.fmt(v) if v is not None else ""
                        for v in s.values]
        kwargs = dict(
            name=s.name,
            marker_color=s.color or theme.color(k),
            text=text,
            textposition="inside" if stacked else "outside",
            insidetextanchor="middle",
            textfont={"size": 12},
        )
        if horizontal:
            fig.add_trace(go.Bar(y=idx, x=vals, orientation="h", **kwargs))
        else:
            fig.add_trace(go.Bar(x=idx, y=vals, **kwargs))

    fig.update_layout(barmode="stack" if stacked else "group")
    _layout(fig, theme, spec.title)

    cat_axis = dict(tickmode="array", tickvals=idx,
                    ticktext=spec.categories, showgrid=False)
    val_axis = dict(gridcolor=theme.grid, zerolinecolor=theme.grid,
                    title=spec.axis_title or None,
                    ticksuffix="%" if spec.mode == "stacked100" else None)
    if horizontal:
        fig.update_yaxes(autorange="reversed", **cat_axis)
        fig.update_xaxes(**val_axis)
    else:
        fig.update_xaxes(**cat_axis)
        fig.update_yaxes(**val_axis)

    # Combo: line series overlaid on the bars (shared value axis).
    for k, s in enumerate(spec.overlay_lines):
        color = s.color or theme.color(len(spec.series) + k)
        ys = list(s.values)
        fig.add_trace(go.Scatter(
            x=idx, y=ys, mode="lines+markers", name=s.name,
            line={"color": color, "width": 2.5},
            marker={"size": 7, "color": color},
        ))
        last = max((i for i, v in enumerate(ys) if v is not None),
                   default=None)
        if last is not None:
            fig.add_annotation(x=last, y=ys[last], text=f"<b>{s.name}</b>",
                               showarrow=False, xanchor="left", xshift=8,
                               font={"color": color, "size": 12})

    # Category totals above / beside each stacked bar.
    if spec.show_totals and spec.mode == "stacked":
        for i, t in enumerate(totals):
            common = dict(text=f"<b>{spec.fmt(t)}</b>",
                          showarrow=False, font={"size": 13,
                                                 "color": theme.text})
            if horizontal:
                fig.add_annotation(y=i, x=t, xshift=6, xanchor="left", **common)
            else:
                fig.add_annotation(x=i, y=t, yshift=8, yanchor="bottom",
                                   **common)

    # Delta / CAGR arrows on stacked totals.
    arrows = spec.resolved_deltas() if spec.mode == "stacked" else []
    gutter_k = 0
    vmax = max(totals) if totals else 0.0
    for (i, j, ti, tj, label) in arrows:
        color = (theme.accent if label.startswith("CAGR")
                 else theme.positive if tj < ti else theme.negative)
        if label.startswith("CAGR"):
            # Diagonal arrow across the bar tops.
            if horizontal:
                fig.add_annotation(ax=ti * 1.04, ay=i, x=tj * 1.04, y=j,
                                   axref="x", ayref="y", xref="x", yref="y",
                                   showarrow=True, arrowhead=2, arrowwidth=2,
                                   arrowcolor=color)
                fig.add_annotation(x=(ti + tj) / 2 * 1.06, y=(i + j) / 2,
                                   text=f"<b>{label}</b>", showarrow=False,
                                   font={"color": color, "size": 12},
                                   bgcolor="rgba(255,255,255,0.85)")
            else:
                fig.add_annotation(ax=i, ay=ti * 1.06, x=j, y=tj * 1.06,
                                   axref="x", ayref="y", xref="x", yref="y",
                                   showarrow=True, arrowhead=2, arrowwidth=2,
                                   arrowcolor=color)
                fig.add_annotation(x=(i + j) / 2, y=(ti + tj) / 2 * 1.10,
                                   text=f"<b>{label}</b>", showarrow=False,
                                   font={"color": color, "size": 12},
                                   bgcolor="rgba(255,255,255,0.85)")
            continue

        gutter = n - 0.5 + 0.55 * (gutter_k + 1)
        gutter_k += 1
        # Level dashed lines from each bar edge out to the gutter, then the
        # difference arrow with its label.
        if not horizontal:
            for cat, tot in ((i, ti), (j, tj)):
                fig.add_shape(type="line", x0=cat + 0.32, x1=gutter,
                              y0=tot, y1=tot, line={"color": theme.muted,
                                                    "width": 1, "dash": "dot"})
            fig.add_annotation(ax=gutter, ay=ti, x=gutter, y=tj,
                               axref="x", ayref="y", xref="x", yref="y",
                               showarrow=True, arrowhead=2, arrowwidth=2,
                               arrowcolor=color)
            fig.add_annotation(x=gutter, y=(ti + tj) / 2,
                               text=f"<b>{label}</b>", showarrow=False,
                               xanchor="left", xshift=4,
                               font={"color": color, "size": 12},
                               bgcolor="rgba(255,255,255,0.85)")
        else:
            gutter_y = n - 0.5 + 0.55 * gutter_k
            for row, tot in ((i, ti), (j, tj)):
                fig.add_shape(type="line", y0=row, y1=gutter_y,
                              x0=tot, x1=tot, line={"color": theme.muted,
                                                    "width": 1, "dash": "dot"})
            fig.add_annotation(ax=ti, ay=gutter_y, x=tj, y=gutter_y,
                               axref="x", ayref="y", xref="x", yref="y",
                               showarrow=True, arrowhead=2, arrowwidth=2,
                               arrowcolor=color)
            fig.add_annotation(y=gutter_y, x=(ti + tj) / 2,
                               text=f"<b>{label}</b>", showarrow=False,
                               yanchor="bottom", yshift=4,
                               font={"color": color, "size": 12},
                               bgcolor="rgba(255,255,255,0.85)")

    non_cagr = sum(1 for (*_, lbl) in arrows if not lbl.startswith("CAGR"))
    if non_cagr and not horizontal:
        fig.update_xaxes(range=[-0.6, n - 0.5 + 0.55 * non_cagr + 0.9])
    if non_cagr and horizontal:
        fig.update_yaxes(range=[n - 0.5 + 0.55 * non_cagr + 0.7, -0.6],
                         autorange=False)
    if spec.show_totals and spec.mode == "stacked" and vmax:
        if horizontal:
            fig.update_xaxes(range=[0, vmax * 1.18])
        else:
            fig.update_yaxes(range=[0, vmax * 1.18])
    return fig


# ---------------------------------------------------------------------- #
# Waterfall
# ---------------------------------------------------------------------- #

def _waterfall(spec: WaterfallSpec, theme: Theme) -> go.Figure:
    steps = spec.resolved()
    measures = ["total" if s.kind == "total" else "relative" for s in steps]
    values = [s.cumulative if s.kind == "total" else s.delta for s in steps]
    text = [
        (spec.number_format.format(s.delta) if s.kind != "total"
         else f"<b>{s.cumulative:,.0f}</b>") if spec.show_values else ""
        for s in steps
    ]
    fig = go.Figure(go.Waterfall(
        x=[s.label for s in steps],
        y=values,
        measure=measures,
        text=text,
        textposition="outside",
        textfont={"size": 12},
        increasing={"marker": {"color": theme.negative}},   # delay grows = red
        decreasing={"marker": {"color": theme.positive}},
        totals={"marker": {"color": theme.total}},
        connector={"visible": spec.show_connectors,
                   "line": {"color": theme.muted, "width": 1}},
    ))
    _layout(fig, theme, spec.title)
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor=theme.grid, zerolinecolor=theme.grid)
    peak = max((max(s.cumulative, s.cumulative - s.delta) for s in steps),
               default=0.0)
    if peak:
        fig.update_yaxes(range=[min(0, min(s.cumulative for s in steps)) * 1.1,
                                peak * 1.22])
    return fig


# ---------------------------------------------------------------------- #
# Gantt
# ---------------------------------------------------------------------- #

def _gantt(spec: GanttSpec, theme: Theme) -> go.Figure:
    fig = go.Figure()
    groups = spec.groups() or [""]
    color_of = {g: theme.color(i) for i, g in enumerate(groups)}
    rows = spec.rows()
    idx = {label: i for i, label in enumerate(rows)}
    n = len(rows)
    span = spec.span()

    # --- background layers: row banding, weekend shading, curtains ------
    for i in range(1, n, 2):
        fig.add_hrect(y0=i - 0.5, y1=i + 0.5, fillcolor=theme.band,
                      opacity=1.0, line_width=0, layer="below")
    if spec.weekend_shading and span:
        for (ws, we) in weekend_ranges(*span):
            fig.add_vrect(x0=ws, x1=we, fillcolor=theme.grid, opacity=0.45,
                          line_width=0, layer="below")
    for c in spec.curtains:
        if c.start is None or c.end is None:
            continue
        fig.add_vrect(x0=c.start, x1=c.end,
                      fillcolor=c.color or theme.curtain, opacity=0.55,
                      line_width=0, layer="below")
        if c.label:
            fig.add_annotation(x=c.start + (c.end - c.start) / 2, y=-0.55,
                               yref="y", text=c.label, showarrow=False,
                               font={"size": 10, "color": theme.muted})

    # --- bars & milestones (items sharing a label share a row) ----------
    seen_groups: set[str] = set()
    for it in spec.items:
        g = it.group or groups[0]
        show_legend = bool(spec.groups()) and g not in seen_groups
        seen_groups.add(g)
        color = color_of.get(g, theme.color(0))
        y = idx[it.label]
        if it.kind == "milestone":
            when = it.start or it.finish
            if when is None:
                continue
            fig.add_trace(go.Scatter(
                x=[when], y=[y], mode="markers",
                marker={"symbol": "diamond", "size": 14, "color": color,
                        "line": {"color": "white", "width": 1}},
                name=g, legendgroup=g, showlegend=show_legend,
                hovertemplate=f"{it.label}<br>%{{x|%d %b %Y}}<extra></extra>",
            ))
            if spec.show_date_labels:
                fig.add_annotation(x=when, y=y, text=f"{when:%d %b %y}",
                                   showarrow=False, xanchor="left", xshift=10,
                                   font={"size": 10, "color": theme.muted})
        elif it.start and it.finish:
            marker: dict = {"color": color}
            if it.style == "striped":
                marker["pattern"] = {"shape": "/", "fgcolor": "white",
                                     "fgopacity": 0.45, "size": 5}
            elif it.style == "open":
                marker = {"color": "rgba(0,0,0,0)",
                          "line": {"color": color, "width": 1.6}}
            fig.add_trace(go.Bar(
                base=[it.start],
                x=[(it.finish - it.start).total_seconds() * 1000],
                y=[y], orientation="h", width=0.55, marker=marker,
                name=g, legendgroup=g, showlegend=show_legend,
                hovertemplate=(f"{it.label}<br>"
                               f"{it.start:%d %b %Y} → {it.finish:%d %b %Y}"
                               "<extra></extra>"),
            ))
            if spec.show_date_labels:
                fig.add_annotation(x=it.start, y=y, xanchor="right",
                                   xshift=-5, text=f"{it.start:%d %b %y}",
                                   showarrow=False,
                                   font={"size": 10, "color": theme.muted})
                fig.add_annotation(x=it.finish, y=y, xanchor="left",
                                   xshift=5, text=f"{it.finish:%d %b %y}",
                                   showarrow=False,
                                   font={"size": 10, "color": theme.muted})
            if spec.show_durations:
                days = (it.finish - it.start).days
                mid = it.start + (it.finish - it.start) / 2
                fig.add_annotation(x=mid, y=y, text=f"{days}d",
                                   showarrow=False, yanchor="bottom",
                                   yshift=8,
                                   font={"size": 10, "color": theme.text})

    # --- remark column ---------------------------------------------------
    has_remarks = spec.show_remarks and any(it.remark for it in spec.items)
    if has_remarks:
        by_row: dict[int, str] = {}
        for it in spec.items:
            if it.remark and idx[it.label] not in by_row:
                by_row[idx[it.label]] = it.remark
        for y, remark in by_row.items():
            fig.add_annotation(xref="paper", x=1.005, xanchor="left",
                               y=y, yref="y", text=remark, showarrow=False,
                               font={"size": 10.5, "color": theme.muted})

    # --- date lines (incl. legacy today) ---------------------------------
    for dl in spec.all_date_lines():
        if dl.date is None:
            continue
        color = dl.color or theme.accent
        fig.add_vline(x=dl.date, line={"color": color, "width": 1.5,
                                       "dash": "dash"})
        if dl.label:
            fig.add_annotation(x=dl.date, y=-0.95, yref="y", xanchor="left",
                               xshift=4, text=dl.label, showarrow=False,
                               font={"color": color, "size": 10.5})

    # --- phase brackets above the bars ------------------------------------
    levels = spec.bracket_levels()
    max_level = max((lvl for _, lvl in levels), default=-1)
    for b, lvl in levels:
        by = -1.35 - 1.0 * lvl
        for (bx, tick) in ((b.start, 0.22), (b.end, 0.22)):
            fig.add_shape(type="line", x0=bx, x1=bx, y0=by, y1=by + tick,
                          line={"color": theme.text, "width": 1.4})
        fig.add_shape(type="line", x0=b.start, x1=b.end, y0=by, y1=by,
                      line={"color": theme.text, "width": 1.4})
        fig.add_annotation(x=b.start + (b.end - b.start) / 2, y=by,
                           yanchor="bottom", yshift=3, text=f"<b>{b.label}</b>",
                           showarrow=False,
                           font={"size": 11, "color": theme.text})

    _layout(fig, theme, spec.title)
    top = -0.6 - (1.35 + 1.0 * max_level if max_level >= 0 else 0.4)
    fig.update_layout(barmode="overlay", bargap=0.3,
                      margin={"r": 150 if has_remarks else 40})
    fig.update_yaxes(
        tickmode="array", tickvals=list(range(n)), ticktext=rows,
        range=[n - 0.5 + 0.4, top], autorange=False, showgrid=False,
        automargin=True,
    )
    fig.update_xaxes(type="date", gridcolor=theme.grid, tickformat="%b %Y")
    return fig


# ---------------------------------------------------------------------- #
# Marimekko
# ---------------------------------------------------------------------- #

def _mekko(spec: MekkoSpec, theme: Theme) -> go.Figure:
    shares = spec.column_shares()
    totals = spec.column_totals()
    gap = 0.006
    widths = [max(s - gap, 0.001) for s in shares]
    lefts: list[float] = []
    cum = 0.0
    for s in shares:
        lefts.append(cum)
        cum += s
    centers = [left + s / 2 for left, s in zip(lefts, shares)]

    fig = go.Figure()
    for k, s in enumerate(spec.series):
        pcts = [
            (v or 0.0) / t * 100.0 if (t := totals[i]) else 0.0
            for i, v in enumerate(s.values)
        ]
        text = [f"{p:.0f}%" if spec.show_values and p >= 7 else ""
                for p in pcts]
        fig.add_trace(go.Bar(
            x=centers, y=pcts, width=widths, name=s.name,
            marker={"color": s.color or theme.color(k),
                    "line": {"color": "white", "width": 1}},
            text=text, textposition="inside", insidetextanchor="middle",
            textfont={"size": 11},
            customdata=[[spec.categories[i], (s.values[i] or 0.0)]
                        for i in range(len(spec.categories))],
            hovertemplate=("%{customdata[0]} · " + s.name +
                           ": %{customdata[1]:,.0f} (%{y:.0f}%)"
                           "<extra></extra>"),
        ))
    for c, cat, t in zip(centers, spec.categories, totals):
        fig.add_annotation(x=c, y=102, yanchor="bottom", showarrow=False,
                           text=(f"<b>{cat}</b><br>"
                                 f"{spec.number_format.format(t)}"),
                           font={"size": 12, "color": theme.text})
    fig.update_layout(barmode="stack")
    _layout(fig, theme, spec.title)
    fig.update_xaxes(range=[0, 1], showticklabels=False, showgrid=False)
    fig.update_yaxes(range=[0, 116], ticksuffix="%", gridcolor=theme.grid,
                     tickvals=[0, 25, 50, 75, 100])
    return fig


# ---------------------------------------------------------------------- #
# Bar chart with a value-axis break (drawn in transformed display space)
# ---------------------------------------------------------------------- #

def _bar_broken(spec: BarSpec, theme: Theme) -> go.Figure:
    n = len(spec.categories)
    idx = list(range(n))
    totals = spec.totals()
    stacked = spec.mode == "stacked"
    vmax = (max(totals) if stacked
            else max((v or 0.0) for s in spec.series for v in s.values)
            ) * 1.05
    t, ticks = spec.axis_break.transform(vmax)

    fig = go.Figure()
    cum = [0.0] * n
    for k, s in enumerate(spec.series):
        heights, text = [], []
        for i, v in enumerate(s.values):
            v = v or 0.0
            if stacked:
                heights.append(t(cum[i] + v) - t(cum[i]))
                cum[i] += v
            else:
                heights.append(t(v))
            text.append(spec.fmt(v) if spec.show_values else "")
        fig.add_trace(go.Bar(
            x=idx, y=heights, name=s.name,
            marker_color=s.color or theme.color(k),
            text=text, textposition="inside", insidetextanchor="middle",
            textfont={"size": 12},
        ))
    fig.update_layout(barmode="stack" if stacked else "group")
    _layout(fig, theme, spec.title)

    if spec.show_totals and stacked:
        for i, tot in enumerate(totals):
            fig.add_annotation(x=i, y=t(tot), yshift=8, yanchor="bottom",
                               text=f"<b>{spec.fmt(tot)}</b>",
                               showarrow=False,
                               font={"size": 13, "color": theme.text})

    # Squiggle: slanted white band with grey edges across the gap.
    mid = (t(spec.axis_break.start) + t(spec.axis_break.end)) / 2
    d = 0.011
    fig.add_shape(type="line", x0=-0.6, x1=n - 0.4, y0=mid - d, y1=mid + d,
                  line={"color": "white", "width": 9})
    for off in (-d, d):
        fig.add_shape(type="line", x0=-0.6, x1=n - 0.4,
                      y0=mid - d + off, y1=mid + d + off,
                      line={"color": theme.muted, "width": 1.2})

    fig.update_xaxes(tickmode="array", tickvals=idx,
                     ticktext=spec.categories, showgrid=False)
    fig.update_yaxes(tickmode="array",
                     tickvals=[pos for pos, _ in ticks],
                     ticktext=[spec.fmt(v) for _, v in ticks],
                     range=[0, 1.12], gridcolor=theme.grid)
    return fig


# ---------------------------------------------------------------------- #
# Line / area
# ---------------------------------------------------------------------- #

def _lines(spec: LineSpec, theme: Theme) -> go.Figure:
    n = len(spec.categories)
    idx = list(range(n))
    fig = go.Figure()
    for k, s in enumerate(spec.series):
        color = s.color or theme.color(k)
        kwargs = dict(
            x=idx, y=list(s.values), name=s.name,
            line={"color": color, "width": 2.5},
            marker={"size": 6, "color": color},
        )
        if spec.mode == "area":
            kwargs["stackgroup"] = "one"
            kwargs["mode"] = "lines"
        else:
            kwargs["mode"] = ("lines+markers+text" if spec.show_values
                              else "lines+markers")
            if spec.show_values:
                kwargs["text"] = [spec.fmt(v) if v is not None else ""
                                  for v in s.values]
                kwargs["textposition"] = "top center"
                kwargs["textfont"] = {"size": 11}
        fig.add_trace(go.Scatter(**kwargs))
        if spec.end_labels and spec.mode == "line":
            last = max((i for i, v in enumerate(s.values) if v is not None),
                       default=None)
            if last is not None:
                fig.add_annotation(x=last, y=s.values[last],
                                   text=f"<b>{s.name}</b>", showarrow=False,
                                   xanchor="left", xshift=8,
                                   font={"color": color, "size": 12})
    _layout(fig, theme, spec.title)
    if spec.end_labels and spec.mode == "line":
        fig.update_layout(showlegend=False,
                          margin={"r": 110, "l": 40, "t": 60, "b": 40})
    fig.update_xaxes(tickmode="array", tickvals=idx,
                     ticktext=spec.categories, showgrid=False)
    fig.update_yaxes(gridcolor=theme.grid, zerolinecolor=theme.grid,
                     title=spec.axis_title or None)
    return fig


# ---------------------------------------------------------------------- #
# Pie / doughnut
# ---------------------------------------------------------------------- #

def _pie(spec: PieSpec, theme: Theme) -> go.Figure:
    fig = go.Figure(go.Pie(
        labels=spec.labels, values=spec.values,
        hole=0.45 if spec.doughnut else 0.0,
        marker={"colors": [theme.color(i) for i in range(len(spec.labels))],
                "line": {"color": "white", "width": 1.5}},
        textinfo="label+percent" if spec.show_pcts else "label+value",
        textfont={"size": 12.5, "family": theme.font},
        sort=False, direction="clockwise", rotation=0,
    ))
    _layout(fig, theme, spec.title)
    fig.update_layout(showlegend=False)
    return fig


# ---------------------------------------------------------------------- #
# Butterfly / tornado
# ---------------------------------------------------------------------- #

def _butterfly(spec: ButterflySpec, theme: Theme) -> go.Figure:
    n = len(spec.categories)
    idx = list(range(n))
    lvals = [-(v or 0.0) for v in spec.left.values]
    rvals = [(v or 0.0) for v in spec.right.values]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=idx, x=lvals, orientation="h", name=spec.left.name,
        marker_color=spec.left.color or theme.color(0),
        text=[spec.fmt(abs(v)) if spec.show_values else "" for v in lvals],
        textposition="outside", textfont={"size": 12},
    ))
    fig.add_trace(go.Bar(
        y=idx, x=rvals, orientation="h", name=spec.right.name,
        marker_color=spec.right.color or theme.color(1),
        text=[spec.fmt(v) if spec.show_values else "" for v in rvals],
        textposition="outside", textfont={"size": 12},
    ))
    _layout(fig, theme, spec.title)
    fig.update_layout(barmode="overlay", bargap=0.35)
    span = max([abs(v) for v in lvals + rvals] or [1.0]) * 1.25
    fig.update_xaxes(range=[-span, span], gridcolor=theme.grid,
                     zerolinecolor=theme.muted,
                     tickvals=[-span * 0.8, -span * 0.4, 0, span * 0.4,
                               span * 0.8],
                     ticktext=[spec.fmt(abs(v)) for v in
                               (-span * 0.8, -span * 0.4, 0, span * 0.4,
                                span * 0.8)])
    fig.update_yaxes(tickmode="array", tickvals=idx,
                     ticktext=spec.categories, autorange="reversed",
                     showgrid=False, automargin=True)
    return fig


# ---------------------------------------------------------------------- #
# Scatter / bubble
# ---------------------------------------------------------------------- #

def _scatter(spec: ScatterSpec, theme: Theme) -> go.Figure:
    fig = go.Figure()
    groups = spec.groups() or [""]
    color_of = {g: theme.color(i) for i, g in enumerate(groups)}
    max_size = max((p.size or 0.0) for p in spec.points) or 1.0
    for g in groups:
        pts = [p for p in spec.points if (p.group or groups[0]) == g]
        if not pts:
            continue
        marker = {"color": color_of[g],
                  "line": {"color": "white", "width": 1}}
        if spec.bubble:
            marker.update(size=[max((p.size or 0.0), 0.0) for p in pts],
                          sizemode="area",
                          sizeref=2.0 * max_size / (46.0 ** 2),
                          sizemin=5)
        else:
            marker["size"] = 11
        fig.add_trace(go.Scatter(
            x=[p.x for p in pts], y=[p.y for p in pts],
            mode="markers+text", text=[p.label for p in pts],
            textposition="top center", textfont={"size": 11},
            marker=marker, name=g, showlegend=bool(spec.groups()),
        ))
    if spec.quadrants:
        qx, qy = spec.quadrants
        fig.add_vline(x=qx, line={"color": theme.muted, "width": 1,
                                  "dash": "dot"})
        fig.add_hline(y=qy, line={"color": theme.muted, "width": 1,
                                  "dash": "dot"})
    _layout(fig, theme, spec.title)
    fig.update_xaxes(gridcolor=theme.grid, title=spec.x_title or None)
    fig.update_yaxes(gridcolor=theme.grid, title=spec.y_title or None)
    return fig


# ---------------------------------------------------------------------- #
# Process flow (chevron strip)
# ---------------------------------------------------------------------- #

def _process(spec: ProcessSpec, theme: Theme) -> go.Figure:
    n = max(len(spec.steps), 1)
    fig = go.Figure()
    notch = 0.18
    for i, step in enumerate(spec.steps):
        x0, x1 = float(i), i + 0.92
        path = (f"M{x0},0 L{x1 - notch},0 L{x1},0.5 L{x1 - notch},1 "
                f"L{x0},1 L{x0 + notch},0.5 Z")
        hot = spec.highlight == i
        fig.add_shape(type="path", path=path,
                      fillcolor=theme.accent if hot else theme.grid,
                      line={"width": 0})
        fig.add_annotation(
            x=(x0 + x1) / 2 + notch / 2, y=0.5, text=f"<b>{step}</b>",
            showarrow=False,
            font={"size": 12.5,
                  "color": "white" if hot else theme.text})
    _layout(fig, theme, spec.title)
    fig.update_xaxes(visible=False, range=[-0.1, n + 0.1])
    fig.update_yaxes(visible=False, range=[-0.35, 1.35])
    fig.update_layout(height=190, showlegend=False)
    return fig


# ---------------------------------------------------------------------- #
# Table — with harvey-ball / RAG / check cell tokens
# ---------------------------------------------------------------------- #

def _table(spec: TableSpec, theme: Theme) -> go.Figure:
    ncols = len(spec.columns)
    display: list[list[str]] = [[] for _ in range(ncols)]
    colors: list[list[str]] = [[] for _ in range(ncols)]
    for row in spec.rows:
        for c in range(ncols):
            raw = row[c] if c < len(row) else ""
            text, key = decode_cell(str(raw))
            display[c].append(text)
            colors[c].append(_semantic_color(key, theme) or theme.text)
    fig = go.Figure(go.Table(
        header={"values": [f"<b>{c}</b>" for c in spec.columns],
                "fill_color": theme.accent,
                "font": {"color": "white", "size": 13, "family": theme.font},
                "align": "left", "height": 32},
        cells={"values": display,
               "fill_color": [["white", "#f4f6f8"]
                              * (len(spec.rows) // 2 + 1)],
               "font": {"size": 12.5, "family": theme.font,
                        "color": colors},
               "align": "left", "height": 28},
    ))
    _layout(fig, theme, spec.title)
    return fig
