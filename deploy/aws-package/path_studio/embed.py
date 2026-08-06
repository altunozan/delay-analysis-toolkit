"""The bidirectional path-gantt component, embedded in the RLPA page.

``component/index.html`` is a static Streamlit component: checkbox and
ordering edits inside the chart stream back to Python as the component
value ``{"path_codes": [...], "edited": True}``. The same file doubles
as the standalone-HTML export (see renderer.py).
"""

from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_COMPONENT_DIR = Path(__file__).parent / "component"
_studio_gantt = components.declare_component(
    "rlpa_path_studio", path=str(_COMPONENT_DIR))


def studio_gantt(payload: dict, *, key: str, height: int = 790):
    """Render the gantt; returns the analyst's working path or None."""
    return _studio_gantt(payload=payload, key=key, default=None,
                         height=height)
