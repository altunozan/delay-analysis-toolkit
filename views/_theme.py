"""Drawing Sheet stylesheet (see ui_variants/ for the revert kit)."""

from __future__ import annotations

import streamlit as st


# --------------------------------------------------------------------- #
# Drawing Sheet identity
# --------------------------------------------------------------------- #
# The visual language of an issued-for-construction drawing: drafting
# paper, a faint blue-line grid, hairline rules, uppercase tracked
# labels, tabular figures and square corners. Chosen because analysis
# screenshots go straight into a Word/PDF deliverable, where dark
# captures read as foreign. Revert kit: ui_variants/01_dark_original/
_THEME_CSS = """
<style>
:root {
  --dsi:      #14324A;   /* drafting ink            */
  --dsi-soft: #55708B;   /* annotation / secondary  */
  --dsr:      #9B3227;   /* revision red (slip)     */
  --dsg:      #3F6B4F;   /* gain / on-programme     */
  --dsline:   #C6D4E0;   /* hairline                */
  --dsgrid:   #EBF2F7;   /* blue-line grid (faint)  */
  --dspaper:  #FCFCFA;
  --dspanel:  #F1F5F9;
  --dsmono: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace;
}

/* paper with a faint drafting grid */
[data-testid="stAppViewContainer"], [data-testid="stMain"] {
  background-color: var(--dspaper);
  background-image:
    linear-gradient(var(--dsgrid) 1px, transparent 1px),
    linear-gradient(90deg, var(--dsgrid) 1px, transparent 1px);
  background-size: 24px 24px;
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stMain"] .block-container { padding-top: 2.4rem; }

/* Sidebar is the drawing's INDEX PANEL — same sheet, same paper, same
   grid, delineated by a rule rather than a change of material. A drawing
   is one sheet; a differently-toned slab bolted to the edge reads as a
   different document. */
[data-testid="stSidebar"] {
  background-color: var(--dspaper) !important;
  background-image:
    linear-gradient(var(--dsgrid) 1px, transparent 1px),
    linear-gradient(90deg, var(--dsgrid) 1px, transparent 1px) !important;
  background-size: 24px 24px !important;
  border-right: 1.5px solid var(--dsi);
}
/* children must be TRANSPARENT or they paint over the parent's grid */
[data-testid="stSidebar"] > div,
[data-testid="stSidebarContent"],
[data-testid="stSidebarUserContent"],
[data-testid="stSidebarNav"] { background: transparent !important; }
/* the collapse control sits on paper too */
[data-testid="stSidebarCollapseButton"] button,
[data-testid="stSidebarHeader"] { background: transparent !important; }
/* nav items: selection marked by an ink rule + wash, not a grey pill */
[data-testid="stSidebarNav"] a {
  border-radius: 0 !important;
  border-left: 2px solid transparent !important;
  background: transparent !important;
  transition: background .15s, border-color .15s;
}
[data-testid="stSidebarNav"] a:hover {
  background: rgba(20, 50, 74, .05) !important;
  border-left-color: var(--dsline) !important;
}
[data-testid="stSidebarNav"] a[aria-current],
[data-testid="stSidebarNav"] li[aria-current] > a {
  background: rgba(20, 50, 74, .085) !important;
  border-left-color: var(--dsi) !important;
}
[data-testid="stSidebarNav"] a[aria-current] span,
[data-testid="stSidebarNav"] li[aria-current] > a span {
  font-weight: 650 !important;
}
[data-testid="stNavSectionHeader"] {
  font-family: var(--dsmono) !important;
  font-size: .6rem !important;
  letter-spacing: .04em !important;
  white-space: normal !important;
  line-height: 1.35 !important;
  text-transform: uppercase !important;
  color: var(--dsi-soft) !important;
  border-bottom: 1px solid var(--dsline);
  padding-bottom: .3rem !important;
  margin-top: .9rem !important;
}

/* titles: uppercase, tracked, ruled under — drawing-sheet headings */
[data-testid="stMain"] h1 {
  font-size: 1.5rem !important;
  font-weight: 700 !important;
  text-transform: uppercase;
  letter-spacing: .07em;
  border-bottom: 2px solid var(--dsi);
  padding-bottom: .35rem;
  margin-bottom: .25rem !important;
}
[data-testid="stMain"] h2 {
  font-size: 1.12rem !important; font-weight: 700 !important;
  text-transform: uppercase; letter-spacing: .05em;
  border-bottom: 1px solid var(--dsline);
  padding-bottom: .25rem; margin-top: 1.6rem !important;
}
[data-testid="stMain"] h3 {
  font-size: .95rem !important; font-weight: 700 !important;
  letter-spacing: .03em;
}

/* metrics as title-block cells */
[data-testid="stMetric"] {
  background: var(--dspaper);
  border: 1px solid var(--dsi);
  border-radius: 0;
  padding: .5rem .7rem;
}
[data-testid="stMetricLabel"] p {
  font-family: var(--dsmono) !important;
  font-size: .62rem !important;
  letter-spacing: .12em !important;
  text-transform: uppercase;
  color: var(--dsi-soft) !important;
}
[data-testid="stMetricValue"] {
  font-size: 1.5rem !important;
  font-variant-numeric: tabular-nums;
  letter-spacing: -.02em;
}

/* square everything — drawings have no rounded corners */
.stButton > button, .stDownloadButton > button,
[data-testid="stExpander"], .stTextInput input, .stNumberInput input,
.stSelectbox [data-baseweb="select"] > div, [data-testid="stDataFrame"],
[data-testid="stAlert"], .stMultiSelect [data-baseweb="select"] > div {
  border-radius: 2px !important;
}
.stButton > button, .stDownloadButton > button {
  border: 1px solid var(--dsi) !important;
  font-family: var(--dsmono);
  font-size: .78rem;
  letter-spacing: .05em;
  text-transform: uppercase;
}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {
  background: var(--dsi) !important; color: var(--dspaper) !important;
}

/* expanders as folded drawing notes */
[data-testid="stExpander"] {
  border: 1px solid var(--dsline) !important;
  background: rgba(255,255,255,.66);
}
[data-testid="stExpander"] summary { font-size: .85rem; }

/* captions / disclosures in the annotation voice */
[data-testid="stCaptionContainer"] p {
  font-size: .76rem !important;
  color: var(--dsi-soft) !important;
  line-height: 1.5;
}

/* tables: hairline, tabular, no zebra */
[data-testid="stDataFrame"] { border: 1px solid var(--dsline) !important; }

/* alerts as revision notes — a coloured left edge, no fill blob */
[data-testid="stAlert"] {
  border-left-width: 3px !important;
  border-radius: 0 2px 2px 0 !important;
}

/* tabs / radios as drafting selectors */
.stRadio [role="radiogroup"] label p { font-size: .85rem; }
code, .stCode { font-family: var(--dsmono) !important; }
</style>
"""


def inject_theme() -> None:
    """Apply the Drawing Sheet stylesheet once per rerun."""
    st.markdown(_THEME_CSS, unsafe_allow_html=True)
