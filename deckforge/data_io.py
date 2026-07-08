"""DataFrame ⇄ ChartSpec conversion + Excel/CSV loading.

The Streamlit data editor holds a plain DataFrame per chart type (shaped like
the think-cell datasheet); these helpers turn it into a typed spec. All
coercion is defensive — bad cells become None, never exceptions.
"""

from __future__ import annotations

import io

import pandas as pd

from specs import (
    AxisBreak, BarSpec, Bracket, ButterflySpec, Curtain, DateLine,
    DeltaArrow, GanttItem, GanttSpec, LineSpec, MekkoSpec, PieSpec,
    ProcessSpec, ScatterPoint, ScatterSpec, Series, TableSpec,
    WaterfallSpec, WaterfallStep,
)


def load_frame(upload) -> pd.DataFrame:
    """Read an uploaded .xlsx / .csv into a DataFrame (first sheet)."""
    name = upload.name.lower()
    raw = upload.getvalue()
    if name.endswith(".csv"):
        return pd.read_csv(io.BytesIO(raw))
    return pd.read_excel(io.BytesIO(raw))


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def _dt(v):
    ts = pd.to_datetime(v, errors="coerce")
    return None if pd.isna(ts) else ts.to_pydatetime()


def frame_to_bar(df: pd.DataFrame, *, title: str, mode: str,
                 orientation: str, show_values: bool, show_totals: bool,
                 deltas: list[DeltaArrow], unit: str = "",
                 sort: str = "none", line_columns: list[str] | None = None,
                 axis_break: tuple[float, float] | None = None) -> BarSpec:
    df = df.dropna(how="all")
    line_columns = line_columns or []
    bar_cols = [c for c in df.columns[1:] if str(c) not in line_columns]
    if sort in ("asc", "desc"):
        key = df[bar_cols].apply(
            lambda col: pd.to_numeric(col, errors="coerce")).sum(axis=1)
        df = df.loc[key.sort_values(ascending=sort == "asc").index]
    cats = [str(c) for c in df.iloc[:, 0].fillna("")]
    series = [
        Series(name=str(col), values=[_num(v) for v in df[col]])
        for col in bar_cols
    ]
    overlay = [
        Series(name=str(col), values=[_num(v) for v in df[col]])
        for col in df.columns[1:] if str(col) in line_columns
    ]
    return BarSpec(title=title, categories=cats, series=series, mode=mode,
                   orientation=orientation, show_values=show_values,
                   show_totals=show_totals, deltas=deltas, unit=unit,
                   overlay_lines=overlay,
                   axis_break=AxisBreak(*axis_break) if axis_break else None)


def frame_to_line(df: pd.DataFrame, *, title: str, mode: str = "line",
                  show_values: bool = False, unit: str = "",
                  axis_title: str = "") -> LineSpec:
    df = df.dropna(how="all")
    return LineSpec(
        title=title,
        categories=[str(c) for c in df.iloc[:, 0].fillna("")],
        series=[Series(name=str(col), values=[_num(v) for v in df[col]])
                for col in df.columns[1:]],
        mode=mode, show_values=show_values, unit=unit,
        axis_title=axis_title,
    )


def frame_to_pie(df: pd.DataFrame, *, title: str, doughnut: bool = False,
                 show_pcts: bool = True) -> PieSpec:
    df = df.dropna(how="all")
    return PieSpec(
        title=title,
        labels=[str(v) for v in df.iloc[:, 0].fillna("")],
        values=[_num(v) or 0.0 for v in df.iloc[:, 1]],
        doughnut=doughnut, show_pcts=show_pcts,
    )


def frame_to_butterfly(df: pd.DataFrame, *, title: str,
                       show_values: bool = True,
                       unit: str = "") -> ButterflySpec:
    df = df.dropna(how="all")
    cols = df.columns
    return ButterflySpec(
        title=title,
        categories=[str(v) for v in df.iloc[:, 0].fillna("")],
        left=Series(name=str(cols[1]),
                    values=[_num(v) for v in df.iloc[:, 1]]),
        right=Series(name=str(cols[2]),
                     values=[_num(v) for v in df.iloc[:, 2]]),
        show_values=show_values, unit=unit,
    )


def frame_to_scatter(df: pd.DataFrame, *, title: str, x_title: str = "",
                     y_title: str = "",
                     quadrants: tuple[float, float] | None = None
                     ) -> ScatterSpec:
    """Columns: Label, X, Y[, Size[, Group]]."""
    df = df.dropna(how="all")
    points = []
    for _, r in df.iterrows():
        x, y = _num(r.iloc[1]), _num(r.iloc[2])
        if x is None or y is None:
            continue
        points.append(ScatterPoint(
            label=str(r.iloc[0]), x=x, y=y,
            size=_num(r.iloc[3]) if len(r) > 3 else None,
            group=_cell(r, 4),
        ))
    return ScatterSpec(title=title, points=points, x_title=x_title,
                       y_title=y_title, quadrants=quadrants)


def frame_to_process(df: pd.DataFrame, *, title: str,
                     highlight: int | None = None) -> ProcessSpec:
    df = df.dropna(how="all")
    return ProcessSpec(
        title=title,
        steps=[str(v) for v in df.iloc[:, 0].fillna("") if str(v)],
        highlight=highlight,
    )


def frame_to_waterfall(df: pd.DataFrame, *, title: str, show_values: bool,
                       show_connectors: bool) -> WaterfallSpec:
    df = df.dropna(how="all")
    steps = [
        WaterfallStep(
            label=str(r.iloc[0]),
            value=_num(r.iloc[1]) or 0.0,
            is_total=bool(r.iloc[2]) if len(r) > 2 and not pd.isna(r.iloc[2])
            else False,
        )
        for _, r in df.iterrows()
    ]
    return WaterfallSpec(title=title, steps=steps, show_values=show_values,
                         show_connectors=show_connectors)


def _cell(r, i, default="") -> str:
    if len(r) > i and not pd.isna(r.iloc[i]):
        return str(r.iloc[i]).strip()
    return default


def frame_to_gantt(
    df: pd.DataFrame, *, title: str, today=None,
    curtains_df: pd.DataFrame | None = None,
    datelines_df: pd.DataFrame | None = None,
    brackets_df: pd.DataFrame | None = None,
    show_date_labels: bool = False,
    show_durations: bool = False,
    show_remarks: bool = False,
    weekend_shading: bool = False,
) -> GanttSpec:
    """Columns: Activity, Start, Finish, Type, Group, Style, Remark.

    Feature frames: curtains (Start, End, Label), date lines (Date, Label),
    brackets (Start, End, Label). Rows with unparseable dates are skipped.
    """
    df = df.dropna(how="all")
    items = []
    for _, r in df.iterrows():
        kind = _cell(r, 3, "bar").lower()
        style = _cell(r, 5, "solid").lower()
        items.append(GanttItem(
            label=str(r.iloc[0]),
            start=_dt(r.iloc[1]),
            finish=_dt(r.iloc[2]) if len(r) > 2 else None,
            kind="milestone" if kind.startswith("mile") else "bar",
            group=_cell(r, 4),
            style=style if style in ("solid", "striped", "open") else "solid",
            remark=_cell(r, 6),
        ))

    curtains = []
    if curtains_df is not None:
        for _, r in curtains_df.dropna(how="all").iterrows():
            s, e = _dt(r.iloc[0]), _dt(r.iloc[1])
            if s and e and e > s:
                curtains.append(Curtain(s, e, _cell(r, 2)))
    date_lines = []
    if datelines_df is not None:
        for _, r in datelines_df.dropna(how="all").iterrows():
            d = _dt(r.iloc[0])
            if d:
                date_lines.append(DateLine(d, _cell(r, 1)))
    brackets = []
    if brackets_df is not None:
        for _, r in brackets_df.dropna(how="all").iterrows():
            s, e = _dt(r.iloc[0]), _dt(r.iloc[1])
            if s and e and e > s:
                brackets.append(Bracket(s, e, _cell(r, 2)))

    return GanttSpec(
        title=title, items=items, today=today, curtains=curtains,
        date_lines=date_lines, brackets=brackets,
        show_date_labels=show_date_labels, show_durations=show_durations,
        show_remarks=show_remarks, weekend_shading=weekend_shading,
    )


def frame_to_mekko(df: pd.DataFrame, *, title: str,
                   show_values: bool) -> MekkoSpec:
    df = df.dropna(how="all")
    cats = [str(c) for c in df.iloc[:, 0].fillna("")]
    series = [
        Series(name=str(col), values=[_num(v) for v in df[col]])
        for col in df.columns[1:]
    ]
    return MekkoSpec(title=title, categories=cats, series=series,
                     show_values=show_values)


def frame_to_table(df: pd.DataFrame, *, title: str) -> TableSpec:
    df = df.dropna(how="all").fillna("")
    return TableSpec(
        title=title,
        columns=[str(c) for c in df.columns],
        rows=[[str(v) for v in row] for row in df.itertuples(index=False)],
    )
