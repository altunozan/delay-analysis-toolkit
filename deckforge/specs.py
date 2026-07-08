"""Typed chart specifications — the single source of truth for every renderer.

The design rule mirrors the toolkit's engine pattern: a spec is a plain,
deterministic description of WHAT to draw (data, labels, arrows). Renderers
(`render_plotly`, `render_pptx`) decide HOW to draw it and must never compute
new figures — all derived numbers (totals, deltas, CAGR, waterfall running
sums) are computed here so both outputs always agree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Union


# ---------------------------------------------------------------------- #
# Shared building blocks
# ---------------------------------------------------------------------- #

@dataclass
class Series:
    """One data series across the spec's categories."""

    name: str
    values: list[float | None]
    color: str | None = None  # override; theme palette used when None


# Unit scaling (think-cell's k / m / bn display scaling).
UNIT_DIVISOR = {"": 1.0, "k": 1e3, "m": 1e6, "bn": 1e9}
UNIT_EXCEL = {"": "#,##0", "k": '#,##0,"k"', "m": '#,##0,,"m"',
              "bn": '#,##0,,,"bn"'}


def fmt_unit(v: float, unit: str = "", signed: bool = False) -> str:
    """Format a value with unit scaling; shared by every renderer."""
    x = v / UNIT_DIVISOR.get(unit, 1.0)
    dec = 1 if (unit and abs(x) < 100 and x != int(x)) else 0
    sign = "+" if signed else ""
    return f"{x:{sign},.{dec}f}{unit}"


@dataclass
class AxisBreak:
    """think-cell value-axis break: compresses [start, end] to a squiggle."""

    start: float
    end: float
    GAP_FRAC = 0.06  # display fraction occupied by the compressed zone

    def transform(self, vmax: float):
        """Returns (t, ticks): t maps real value -> display [0..1];
        ticks = [(display_pos, real_label_value)] for the axis."""
        below, above = self.start, max(vmax - self.end, 1e-9)
        scale = (1.0 - self.GAP_FRAC) / (below + above)

        def t(v: float) -> float:
            if v <= self.start:
                return v * scale
            if v >= self.end:
                return below * scale + self.GAP_FRAC + (v - self.end) * scale
            frac = (v - self.start) / (self.end - self.start)
            return below * scale + self.GAP_FRAC * frac

        step = max(round(below / 3, -max(len(str(int(below))) - 2, 0)) or 1, 1)
        ticks = []
        v = 0.0
        while v <= self.start + 1e-9:
            ticks.append((t(v), v))
            v += step
        ticks.append((t(self.end), self.end))
        ticks.append((t(vmax), vmax))
        return t, ticks


@dataclass
class DeltaArrow:
    """think-cell style difference arrow between two category totals."""

    from_category: str
    to_category: str
    mode: Literal["absolute", "percent", "cagr"] = "absolute"

    def label_for(self, start: float, end: float, periods: int,
                  number_format: str = "{:+,.0f}") -> str:
        if self.mode == "absolute":
            return number_format.format(end - start)
        if self.mode == "percent":
            if start == 0:
                return "n/a"
            return f"{(end - start) / abs(start):+.1%}"
        # CAGR needs at least one full period and positive endpoints.
        if periods < 1 or start <= 0 or end <= 0:
            return "n/a"
        return f"CAGR {((end / start) ** (1.0 / periods)) - 1.0:+.1%}"


# ---------------------------------------------------------------------- #
# Bar / column charts (stacked, clustered, 100%)
# ---------------------------------------------------------------------- #

@dataclass
class BarSpec:
    title: str
    categories: list[str]
    series: list[Series]
    mode: Literal["stacked", "clustered", "stacked100"] = "stacked"
    orientation: Literal["vertical", "horizontal"] = "vertical"
    show_values: bool = True
    show_totals: bool = True
    deltas: list[DeltaArrow] = field(default_factory=list)
    number_format: str = "{:,.0f}"
    axis_title: str = ""
    unit: str = ""                            # "", "k", "m", "bn"
    overlay_lines: list[Series] = field(default_factory=list)  # combo chart
    axis_break: AxisBreak | None = None

    def fmt(self, v: float, signed: bool = False) -> str:
        if self.unit:
            return fmt_unit(v, self.unit, signed)
        f = self.number_format
        if signed and "+" not in f:
            f = f.replace("{:", "{:+", 1)
        return f.format(v)

    def totals(self) -> list[float]:
        """Category totals (Nones treated as 0)."""
        return [
            sum((s.values[i] or 0.0) for s in self.series)
            for i in range(len(self.categories))
        ]

    def resolved_deltas(self) -> list[tuple[int, int, float, float, str]]:
        """(from_idx, to_idx, from_total, to_total, label) per arrow."""
        totals = self.totals()
        out = []
        for d in self.deltas:
            try:
                i = self.categories.index(d.from_category)
                j = self.categories.index(d.to_category)
            except ValueError:
                continue
            if d.mode == "absolute":
                label = self.fmt(totals[j] - totals[i], signed=True)
            else:
                label = d.label_for(totals[i], totals[j], abs(j - i))
            out.append((i, j, totals[i], totals[j], label))
        return out


# ---------------------------------------------------------------------- #
# Waterfall
# ---------------------------------------------------------------------- #

@dataclass
class WaterfallStep:
    label: str
    value: float = 0.0          # signed delta; ignored when is_total
    is_total: bool = False      # draws the running total from the base line


@dataclass
class ResolvedStep:
    label: str
    base: float                 # bottom of the visible segment
    delta: float                # signed movement (totals: cumulative value)
    cumulative: float           # running total AFTER this step
    kind: Literal["increase", "decrease", "total"]


@dataclass
class WaterfallSpec:
    title: str
    steps: list[WaterfallStep]
    show_values: bool = True
    show_connectors: bool = True
    number_format: str = "{:+,.0f}"

    def resolved(self) -> list[ResolvedStep]:
        out: list[ResolvedStep] = []
        running = 0.0
        for s in self.steps:
            if s.is_total:
                out.append(ResolvedStep(s.label, 0.0, running, running, "total"))
                continue
            base = running if s.value >= 0 else running + s.value
            running += s.value
            out.append(ResolvedStep(
                s.label, base, s.value, running,
                "increase" if s.value >= 0 else "decrease",
            ))
        return out


# ---------------------------------------------------------------------- #
# Gantt / timeline — full think-cell feature set
# ---------------------------------------------------------------------- #

@dataclass
class GanttItem:
    label: str                  # items sharing a label share a ROW
    start: datetime | None
    finish: datetime | None     # equals start (or None) for milestones
    kind: Literal["bar", "milestone"] = "bar"
    group: str = ""             # colour grouping / swimlane
    style: Literal["solid", "striped", "open"] = "solid"
    remark: str = ""            # right-hand remark / responsibility column


@dataclass
class Curtain:
    """Shaded vertical band across the whole chart (think-cell curtain)."""

    start: datetime | None
    end: datetime | None
    label: str = ""
    color: str | None = None    # override; theme curtain tint when None


@dataclass
class DateLine:
    """Labelled vertical date line (today line, EOT date, data date, ...)."""

    date: datetime | None
    label: str = ""
    color: str | None = None


@dataclass
class Bracket:
    """Horizontal span bracket above the bars with a phase label."""

    start: datetime | None
    end: datetime | None
    label: str = ""


@dataclass
class GanttSpec:
    title: str
    items: list[GanttItem]
    today: datetime | None = None
    curtains: list[Curtain] = field(default_factory=list)
    date_lines: list[DateLine] = field(default_factory=list)
    brackets: list[Bracket] = field(default_factory=list)
    show_date_labels: bool = False    # start/finish dates at bar ends
    show_durations: bool = False      # "123d" on each bar
    show_remarks: bool = False        # right-hand remark column
    weekend_shading: bool = False     # only drawn when the span is short

    def rows(self) -> list[str]:
        """Ordered unique row labels (several items may share a row)."""
        seen: list[str] = []
        for it in self.items:
            if it.label not in seen:
                seen.append(it.label)
        return seen

    def span(self) -> tuple[datetime, datetime] | None:
        dates = [d for it in self.items
                 for d in (it.start, it.finish) if d is not None]
        dates += [d for c in self.curtains
                  for d in (c.start, c.end) if d is not None]
        dates += [dl.date for dl in self.all_date_lines()
                  if dl.date is not None]
        dates += [d for b in self.brackets
                  for d in (b.start, b.end) if d is not None]
        if not dates:
            return None
        return min(dates), max(dates)

    def all_date_lines(self) -> list[DateLine]:
        """Explicit date lines plus the legacy `today` shortcut."""
        lines = list(self.date_lines)
        if self.today is not None:
            lines.append(DateLine(self.today, "today"))
        return lines

    def groups(self) -> list[str]:
        seen: list[str] = []
        for it in self.items:
            if it.group and it.group not in seen:
                seen.append(it.group)
        return seen

    def bracket_levels(self) -> list[tuple[Bracket, int]]:
        """Assign each bracket a stacking level so overlaps don't collide."""
        placed: list[tuple[Bracket, int]] = []
        for b in self.brackets:
            if b.start is None or b.end is None:
                continue
            level = 0
            while any(
                lvl == level and not (b.end <= o.start or b.start >= o.end)
                for o, lvl in placed
            ):
                level += 1
            placed.append((b, level))
        return placed


WEEKEND_SHADING_MAX_DAYS = 130


def weekend_ranges(t0: datetime, t1: datetime) -> list[tuple[datetime,
                                                             datetime]]:
    """Saturday→Monday bands between t0 and t1 (shared by both renderers)."""
    from datetime import timedelta
    if (t1 - t0).days > WEEKEND_SHADING_MAX_DAYS:
        return []
    out = []
    d = datetime(t0.year, t0.month, t0.day)
    d -= timedelta(days=(d.weekday() - 5) % 7)  # back to Saturday
    while d < t1:
        out.append((max(d, t0), min(d + timedelta(days=2), t1)))
        d += timedelta(days=7)
    return out


# ---------------------------------------------------------------------- #
# Marimekko
# ---------------------------------------------------------------------- #

@dataclass
class MekkoSpec:
    """Variable-width 100% stacked columns; width ∝ category total."""

    title: str
    categories: list[str]
    series: list[Series]        # absolute values, normalised per column
    show_values: bool = True
    number_format: str = "{:,.0f}"

    def column_totals(self) -> list[float]:
        return [
            sum((s.values[i] or 0.0) for s in self.series)
            for i in range(len(self.categories))
        ]

    def column_shares(self) -> list[float]:
        totals = self.column_totals()
        grand = sum(totals) or 1.0
        return [t / grand for t in totals]


# ---------------------------------------------------------------------- #
# Line / area (also the S-curve)
# ---------------------------------------------------------------------- #

@dataclass
class LineSpec:
    title: str
    categories: list[str]
    series: list[Series]
    mode: Literal["line", "area"] = "line"
    show_values: bool = False
    end_labels: bool = True       # series name at the line end, think-cell style
    number_format: str = "{:,.0f}"
    unit: str = ""
    axis_title: str = ""

    def fmt(self, v: float) -> str:
        return fmt_unit(v, self.unit) if self.unit \
            else self.number_format.format(v)


# ---------------------------------------------------------------------- #
# Pie / doughnut
# ---------------------------------------------------------------------- #

@dataclass
class PieSpec:
    title: str
    labels: list[str]
    values: list[float]
    doughnut: bool = False
    show_pcts: bool = True
    unit: str = ""


# ---------------------------------------------------------------------- #
# Butterfly / tornado
# ---------------------------------------------------------------------- #

@dataclass
class ButterflySpec:
    """Two mirrored horizontal bar sets sharing categories."""

    title: str
    categories: list[str]
    left: Series
    right: Series
    show_values: bool = True
    number_format: str = "{:,.0f}"
    unit: str = ""

    def fmt(self, v: float) -> str:
        return fmt_unit(v, self.unit) if self.unit \
            else self.number_format.format(v)


# ---------------------------------------------------------------------- #
# Scatter / bubble
# ---------------------------------------------------------------------- #

@dataclass
class ScatterPoint:
    label: str
    x: float
    y: float
    size: float | None = None     # bubble area driver; None = plain scatter
    group: str = ""


@dataclass
class ScatterSpec:
    title: str
    points: list[ScatterPoint]
    x_title: str = ""
    y_title: str = ""
    quadrants: tuple[float, float] | None = None   # (x, y) crosshair lines

    @property
    def bubble(self) -> bool:
        return any(p.size is not None for p in self.points)

    def groups(self) -> list[str]:
        seen: list[str] = []
        for p in self.points:
            if p.group and p.group not in seen:
                seen.append(p.group)
        return seen


# ---------------------------------------------------------------------- #
# Process flow (chevron strip)
# ---------------------------------------------------------------------- #

@dataclass
class ProcessSpec:
    title: str
    steps: list[str]
    highlight: int | None = None   # 0-based index of the emphasised step


# ---------------------------------------------------------------------- #
# Table / agenda — with think-cell cell tokens
# ---------------------------------------------------------------------- #

HARVEY = {"0": "○", "25": "◔", "50": "◑", "75": "◕", "100": "●"}
_RAG = {"green": "positive", "amber": "warning", "red": "negative"}


def decode_cell(text: str) -> tuple[str, str | None]:
    """Decode cell tokens → (display_text, semantic_color_key | None).

    Tokens: `hb:0|25|50|75|100` harvey ball · `rag:green|amber|red` status
    dot · `check` / `cross`. Anything else passes through unchanged.
    """
    t = text.strip().lower()
    if t.startswith("hb:"):
        return HARVEY.get(t[3:].strip(), text), "accent"
    if t.startswith("rag:"):
        key = _RAG.get(t[4:].strip())
        return ("●", key) if key else (text, None)
    if t in ("check", "yes", "✓"):
        return "✓", "positive"
    if t in ("cross", "no", "✗"):
        return "✗", "negative"
    return text, None


@dataclass
class TableSpec:
    title: str
    columns: list[str]
    rows: list[list[str]]


ChartSpec = Union[BarSpec, WaterfallSpec, GanttSpec, MekkoSpec, TableSpec,
                  LineSpec, PieSpec, ButterflySpec, ScatterSpec, ProcessSpec]

SPEC_KIND_LABELS = {
    BarSpec: "Bar chart",
    WaterfallSpec: "Waterfall",
    GanttSpec: "Gantt / timeline",
    MekkoSpec: "Marimekko",
    TableSpec: "Table",
    LineSpec: "Line chart",
    PieSpec: "Pie chart",
    ButterflySpec: "Butterfly",
    ScatterSpec: "Scatter",
    ProcessSpec: "Process flow",
}


def spec_kind(spec: ChartSpec) -> str:
    return SPEC_KIND_LABELS.get(type(spec), "Chart")
