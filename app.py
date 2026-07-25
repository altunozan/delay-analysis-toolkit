"""Forensic Programme Analysis — Streamlit entrypoint.

The UI lives in views/ (one module per page; views/_shared.py holds the
intake pool, cache wrappers and AI panels). This file owns only what an
entrypoint must: page config, the access gate, theme injection and the
grouped sidebar navigation. Every page reads the same uploaded-file pool
from session state, so intake done once feeds all three groups.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import hmac

import streamlit as st

import state as sk

from views._shared import status_strip
from views._theme import inject_theme
from views.apab import apab_tab
from views.asbuilt import asbuilt_tab
from views.collapsed_asbuilt import collapsed_asbuilt_tab
from views.comparison import comparison_tab
from views.critical_path import critical_path_tab
from views.dcma_page import dcma_tab
from views.float_erosion import float_erosion_tab
from views.hierarchy import hierarchy_tab
from views.impacted_asplanned import impacted_asplanned_tab
from views.intake import intake_tab
from views.milestone import milestone_tab
from views.oos import oos_tab
from views.progress import progress_tab
from views.progress_transfer import progress_transfer_tab
from views.report import report_tab
from views.resources import resources_tab
from views.sequence import sequence_tab
from views.tia import tia_tab
from views.windows import windows_tab

st.set_page_config(
    page_title="Forensic Programme Analysis",
    page_icon="📊",
    layout="wide",
)


def main() -> None:
    inject_theme()

    # ---- access gate: active whenever APP_PASSWORD is set in secrets
    # (Streamlit Cloud -> app settings -> Secrets). Unset = open, for
    # local development. Client XERs are commercially sensitive; the
    # public URL must not serve them unauthenticated.
    try:
        _pw = st.secrets.get("APP_PASSWORD", "")
    except Exception:                       # no secrets.toml locally
        _pw = ""
    if _pw and not st.session_state.get(sk.AUTH_OK):
        st.title("Forensic Delay-Analysis Toolkit")
        entered = st.text_input("Access password", type="password",
                                key="gate_pw")
        if entered and hmac.compare_digest(entered, _pw):
            st.session_state[sk.AUTH_OK] = True
            st.rerun()
        elif entered:
            st.error("Wrong password.")
        st.stop()

    # Grouped sidebar navigation: the FORENSIC PROGRAMME ANALYSIS tools
    # (inspect / validate / screen / structure the schedule) are kept
    # separate from the recognised delay-analysis METHODS, which are split
    # RETROSPECTIVE (as-planned vs as-built family) and PROSPECTIVE (TIA).
    pages = {
        "\U0001f6e0 Forensic Programme Analysis": [
            st.Page(intake_tab, title="Data Intake & Inventory",
                    icon=":material/upload_file:", url_path="intake",
                    default=True),
            st.Page(dcma_tab, title="DCMA 14-Point",
                    icon=":material/health_and_safety:", url_path="dcma"),
            st.Page(critical_path_tab, title="Baseline Critical Path",
                    icon=":material/route:",
                    url_path="baseline-critical-path"),
            st.Page(comparison_tab, title="Revision Comparison",
                    icon=":material/compare_arrows:",
                    url_path="revision-comparison"),
            st.Page(oos_tab, title="Out-of-Sequence Repair",
                    icon=":material/link:", url_path="out-of-sequence"),
            st.Page(float_erosion_tab, title="Float Erosion",
                    icon=":material/trending_down:",
                    url_path="float-erosion"),
            st.Page(progress_tab, title="Progress S-Curve",
                    icon=":material/show_chart:",
                    url_path="progress-s-curve"),
            st.Page(resources_tab, title="Resource Loading",
                    icon=":material/engineering:",
                    url_path="resource-loading"),
            st.Page(sequence_tab, title="Sequence Coding",
                    icon=":material/extension:",
                    url_path="sequence-coding"),
            st.Page(hierarchy_tab, title="Hierarchy Rebuild",
                    icon=":material/account_tree:",
                    url_path="hierarchy-rebuild"),
            st.Page(milestone_tab, title="Milestone Shift Tracker",
                    icon=":material/flag:", url_path="milestone-shift"),
            st.Page(progress_transfer_tab, title="Progress Transfer",
                    icon=":material/sync_alt:",
                    url_path="progress-transfer"),
            st.Page(asbuilt_tab, title="As-Built Critical Path",
                    icon=":material/timeline:",
                    url_path="as-built-critical-path"),
            st.Page(report_tab, title="Report Assembler",
                    icon=":material/description:",
                    url_path="report-assembler"),
        ],
        "\U0001f52c Retrospective — what happened": [
            st.Page(apab_tab, title="As-Planned vs As-Built",
                    icon=":material/bar_chart:",
                    url_path="as-planned-vs-as-built"),
            st.Page(windows_tab, title="Windows Analysis",
                    icon=":material/grid_view:",
                    url_path="windows-analysis"),
            st.Page(impacted_asplanned_tab, title="Impacted As-Planned",
                    icon=":material/event_upcoming:",
                    url_path="impacted-as-planned"),
            st.Page(collapsed_asbuilt_tab, title="Collapsed As-Built",
                    icon=":material/compress:",
                    url_path="collapsed-as-built"),
        ],
        "⚡ Prospective — forecast impact": [
            st.Page(tia_tab, title="Time Impact Analysis",
                    icon=":material/bolt:",
                    url_path="time-impact-analysis"),
        ],
    }

    with st.sidebar:
        st.caption("Uploaded programmes are shared across every group.")

    header = st.container()          # reserve the top slot
    # expanded=True shows every group and page at once; the default
    # collapses to 10 items behind a "View N more", which would bury the
    # Retrospective and Prospective method groups.
    nav = st.navigation(pages, expanded=True)
    nav.run()                        # the selected page renders here
    # Fill the header AFTER the page runs, so the status strip reflects
    # state (e.g. an intake upload) written during this same rerun.
    with header:
        st.title(nav.title)
        status_strip()


if __name__ == "__main__":
    main()
