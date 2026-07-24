"""Standalone DCMA 14-Point Schedule Quality Assessment module.

Public API:
    parse_xer(path_or_text) -> XerData
    run_all_checks(xer_data, config) -> list[CheckResult]
    DCMAConfig
"""

from .xer_parser import parse_xer, XerData
from .models import Project, Task, Relationship, Calendar
from .config import DCMAConfig
from .checks import run_all_checks, CheckResult, CheckStatus
from .trace import DCMATrace, annotate_path_position, build_dcma_trace

__all__ = [
    "parse_xer",
    "XerData",
    "Project",
    "Task",
    "Relationship",
    "Calendar",
    "DCMAConfig",
    "run_all_checks",
    "CheckResult",
    "CheckStatus",
    "DCMATrace",
    "annotate_path_position",
    "build_dcma_trace",
]
