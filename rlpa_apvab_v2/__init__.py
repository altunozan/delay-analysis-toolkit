"""Isolated programme-only RLPA/APvAB v2 module."""

from .adapter import load_xer_snapshot, snapshot_from_xer_data
from .config import RLPAConfig, UNCALIBRATED_STATEMENT
from .domain import RULESET_VERSION, SPECIFICATION_VERSION
from .engine import PipelineResult, analyse, rerun_with_rejections
from .reporting import html_report, report_sections, write_report_bundle
from .store import LayerStore

__all__ = [
    "LayerStore",
    "PipelineResult",
    "RLPAConfig",
    "RULESET_VERSION",
    "SPECIFICATION_VERSION",
    "UNCALIBRATED_STATEMENT",
    "analyse",
    "html_report",
    "load_xer_snapshot",
    "report_sections",
    "rerun_with_rejections",
    "snapshot_from_xer_data",
    "write_report_bundle",
]

