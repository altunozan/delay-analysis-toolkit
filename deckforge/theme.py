"""Shared visual theme — one palette + font set consumed by BOTH renderers,
so the dashboard preview and the exported PowerPoint look identical."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Theme:
    name: str
    palette: list[str] = field(default_factory=list)
    positive: str = "#1a7f37"   # gains / increases
    negative: str = "#cf222e"   # slips / decreases
    warning: str = "#d4890f"    # RAG amber
    total: str = "#39424e"      # waterfall totals
    accent: str = "#0f4c81"     # arrows, today-line, table header
    text: str = "#1f2937"
    muted: str = "#6b7280"
    grid: str = "#e2e6ea"
    curtain: str = "#f2e6d4"    # gantt curtain tint (light, sits behind bars)
    band: str = "#f7f8fa"       # gantt alternating row banding
    font: str = "Arial"
    base_font_pt: int = 11

    def color(self, i: int) -> str:
        return self.palette[i % len(self.palette)]


THEMES: dict[str, Theme] = {
    "Consulting Blue": Theme(
        name="Consulting Blue",
        palette=["#0f4c81", "#4c78a8", "#9ecae9", "#c3cdd6",
                 "#e8a33d", "#7b9e87"],
    ),
    "Slate & Teal": Theme(
        name="Slate & Teal",
        palette=["#2f4550", "#586f7c", "#84a9ac", "#b8dbd9",
                 "#c98936", "#8f7e9e"],
        accent="#2f4550",
    ),
    "Forensic (toolkit match)": Theme(
        name="Forensic (toolkit match)",
        palette=["#4c78a8", "#e45756", "#72b7b2", "#eeca3b",
                 "#54a24b", "#b279a2"],
        accent="#cf222e",
    ),
}

DEFAULT_THEME = THEMES["Consulting Blue"]
