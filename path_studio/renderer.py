"""Standalone Path Studio HTML from the very same component file.

The live component and the downloadable HTML share one template
(``component/index.html``): the static file carries the sentinel
``/*PAYLOAD*/null/*END*/`` and waits for Streamlit's render event; the
export replaces the sentinel with the escaped payload and runs
self-contained.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import PathDraft, StudioDataset, ValidationIssue

_SENTINEL = "/*PAYLOAD*/null/*END*/"
_TEMPLATE_PATH = Path(__file__).parent / "component" / "index.html"


def _js(value: object) -> str:
    """Escape untrusted XER text before embedding it in a script block."""
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")


def build_path_studio_html(
    dataset: StudioDataset,
    draft: PathDraft,
    issues: list[ValidationIssue] | tuple[ValidationIssue, ...] = (),
) -> str:
    payload = {
        "dataset": dataset.to_dict(),
        "draft": draft.to_dict(),
        "issues": [issue.to_dict() for issue in issues],
    }
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.replace(_SENTINEL, _js(payload))
