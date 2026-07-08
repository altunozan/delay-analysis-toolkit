"""Bundled sample datasets — one per chart type, so the app demos instantly.

Each builder returns a pandas DataFrame shaped exactly like the data editor
expects for that chart type; `spec_from_frame` in the app converts it.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd


def bar_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "Category": ["FY22", "FY23", "FY24", "FY25"],
        "Construction": [420, 465, 512, 590],
        "MEP": [180, 210, 236, 275],
        "Fit-out": [90, 118, 160, 205],
    })


def waterfall_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "Step": ["Design changes", "Late approvals", "Weather",
                 "Acceleration", "Net delay"],
        "Value": [45.0, 62.0, 18.0, -25.0, 0.0],
        "Is total": [False, False, False, False, True],
    })


def gantt_frame() -> pd.DataFrame:
    d = datetime
    # NOTE: two "Fit-out" rows share one chart row — the striped second bar
    # is the forecast portion, think-cell style.
    return pd.DataFrame({
        "Activity": ["Enabling works", "Substructure", "Superstructure",
                     "Façade", "MEP first fix", "Fit-out", "Fit-out",
                     "Sectional completion", "Project completion"],
        "Start": [d(2026, 1, 5), d(2026, 2, 16), d(2026, 5, 4),
                  d(2026, 9, 1), d(2026, 10, 12), d(2027, 1, 18),
                  d(2027, 4, 5), d(2027, 3, 31), d(2027, 6, 30)],
        "Finish": [d(2026, 2, 13), d(2026, 4, 30), d(2026, 10, 23),
                   d(2027, 1, 15), d(2027, 2, 26), d(2027, 4, 2),
                   d(2027, 6, 11), d(2027, 3, 31), d(2027, 6, 30)],
        "Type": ["bar", "bar", "bar", "bar", "bar", "bar", "bar",
                 "milestone", "milestone"],
        "Group": ["Civils", "Civils", "Civils", "Envelope", "MEP",
                  "Finishes", "Finishes", "Milestones", "Milestones"],
        "Style": ["solid", "solid", "solid", "solid", "solid", "solid",
                  "striped", "solid", "solid"],
        "Remark": ["", "Piling s/c", "Critical", "", "", "", "forecast",
                   "Section 1", "Contract"],
    })


def gantt_curtains_frame() -> pd.DataFrame:
    d = datetime
    return pd.DataFrame({
        "Start": [d(2026, 12, 15)],
        "End": [d(2027, 1, 5)],
        "Label": ["Holiday shutdown"],
    })


def gantt_datelines_frame() -> pd.DataFrame:
    d = datetime
    return pd.DataFrame({
        "Date": [d(2026, 10, 1)],
        "Label": ["EOT-1 award"],
    })


def gantt_brackets_frame() -> pd.DataFrame:
    d = datetime
    return pd.DataFrame({
        "Start": [d(2026, 1, 5), d(2026, 9, 1)],
        "End": [d(2026, 10, 23), d(2027, 6, 11)],
        "Label": ["Civils phase", "Envelope & fit-out"],
    })


def mekko_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "Category": ["Residential", "Commercial", "Infrastructure", "Industrial"],
        "Region A": [340, 120, 210, 60],
        "Region B": [180, 200, 90, 45],
        "Region C": [95, 160, 140, 110],
    })


def table_frame() -> pd.DataFrame:
    # Status / Progress columns demo the think-cell cell tokens:
    # rag:green|amber|red, hb:0|25|50|75|100, check / cross.
    return pd.DataFrame({
        "Section": ["1", "2", "3", "4", "5"],
        "Topic": ["Programme status", "Delay events register",
                  "Critical path movement", "Mitigation options",
                  "Decisions required"],
        "Owner": ["Planning", "Commercial", "Planning", "Delivery", "Board"],
        "Status": ["rag:green", "rag:amber", "rag:red", "rag:amber",
                   "rag:green"],
        "Progress": ["hb:100", "hb:50", "hb:75", "hb:25", "hb:0"],
        "Signed off": ["check", "cross", "check", "cross", "cross"],
    })


def line_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "Month": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep"],
        "Planned %": [4, 11, 21, 34, 48, 63, 77, 90, 100],
        "Actual %": [3, 8, 15, 24, 34, 45, None, None, None],
    })


def pie_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "Segment": ["Structure", "MEP", "Fit-out", "Façade", "External"],
        "Value": [38, 24, 18, 14, 6],
    })


def butterfly_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "Trade": ["Concrete", "Steel", "MEP", "Finishes", "Logistics"],
        "Planned crew": [120, 85, 140, 90, 40],
        "Actual crew": [95, 88, 110, 60, 45],
    })


def scatter_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "Package": ["Piling", "Frame", "Envelope", "MEP", "Lifts",
                    "Fit-out"],
        "Delay risk": [30, 55, 70, 85, 45, 60],
        "Cost impact": [25, 70, 55, 90, 35, 65],
        "Size": [40, 90, 65, 120, 30, 80],
        "Group": ["Civils", "Civils", "Envelope", "Services", "Services",
                  "Finishes"],
    })


def process_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "Step": ["Notice", "Records", "Analysis", "Quantum", "Submission",
                 "Determination"],
    })


SAMPLE_FRAMES = {
    "bar": bar_frame,
    "combo": bar_frame,
    "waterfall": waterfall_frame,
    "gantt": gantt_frame,
    "mekko": mekko_frame,
    "table": table_frame,
    "line": line_frame,
    "pie": pie_frame,
    "butterfly": butterfly_frame,
    "scatter": scatter_frame,
    "process": process_frame,
}
