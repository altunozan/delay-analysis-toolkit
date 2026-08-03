"""RLPA path gantt — the in-module, auditable critical-path editor.

Not a separate module: the RLPA page (As-Planned vs As-Built v2)
embeds this after path adoption in step ①, so the analyst can review
and adjust the as-built critical path — full programme, P6-style bars,
relationship arrows — before the analysis proceeds. Applying an
adjustment requires a written rationale and is disclosed in the basis
of analysis.

``embed`` (the Streamlit component wrapper) is imported by the view;
this package root stays free of Streamlit so engines and tests can
import it headlessly.
"""

from .adapter import analysis_key, dataset_from_xer
from .adjust import adjusted_basis, adjusted_path
from .models import (
    PathDraft, StudioActivity, StudioDataset, StudioRelationship,
    ValidationIssue,
)
from .renderer import build_path_studio_html
from .validation import validate_draft

__all__ = [
    "adjusted_basis", "adjusted_path", "analysis_key",
    "build_path_studio_html", "dataset_from_xer", "PathDraft",
    "StudioActivity", "StudioDataset", "StudioRelationship",
    "ValidationIssue", "validate_draft",
]
