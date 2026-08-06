"""Standalone sub-analyses embedded in every method page."""

from __future__ import annotations

import streamlit as st

from views.concurrency import concurrency_tab
from views.explain import explain_tab


def analysis_submodules(page_key: str) -> None:
    """Concurrency screening + Explain-this-delay as sub-modules of an
    analysis method page (they are lenses on an analysis, not standalone
    methods). Toggle-gated so they cost nothing until opened."""
    st.divider()
    st.markdown("##### Analysis sub-modules")
    with st.expander("⚖️ Concurrency screening (per-window "
                     "Employer/Contractor overlap)"):
        if st.toggle("Run concurrency screening",
                     key=f"sub_conc_{page_key}"):
            concurrency_tab()
    with st.expander("🔎 Explain this delay (why did a milestone move?)"):
        if st.toggle("Run explain", key=f"sub_expl_{page_key}"):
            explain_tab()
