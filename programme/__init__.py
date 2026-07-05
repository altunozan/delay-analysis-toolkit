"""Programme-based forensic analysis modules.

These operate on one or more parsed P6 XER exports (via the existing
``dcma.parse_xer``) and follow the same architecture as the DCMA engine:

    parser (dcma.parse_xer)  ->  pure engine functions returning structured
    result objects  ->  optional LLM narrative that only describes the numbers.

Modules
-------
inventory       Module 0 — intake & data inventory across revisions
milestones      Module 3 — milestone shift tracker
variance        Module 4 — preliminary as-planned vs as-recorded
activity_codes  helper — per-task activity code assignments from raw_tables

All engines are UI-independent so they can feed a CLI, the Streamlit app, or a
report assembler.
"""

from .activity_codes import (
    ActivityCodeType,
    activity_code_types,
    task_code_assignments,
)
from .critical_path import (
    CriticalPathResult,
    PathActivity,
    PathLink,
    end_activity_candidates,
    extract_critical_path,
    extract_longest_path,
)
from .inventory import ProgrammeInventory, RevisionInfo, build_inventory
from .milestones import (
    MilestoneMatch,
    MilestoneSeries,
    MilestoneShiftResult,
    ShiftPoint,
    match_milestones,
    track_milestone_shifts,
)
from .narrative import (
    build_critical_path_prompt,
    build_inventory_prompt,
    build_milestone_prompt,
    build_variance_prompt,
)
from .report_xlsx import (
    build_critical_path_xlsx,
    build_inventory_xlsx,
    build_milestone_xlsx,
    build_variance_xlsx,
)
from .variance import (
    VarianceGroup,
    VarianceResult,
    combine_mappings,
    compute_variance,
    compute_variance_by_mapping,
)
from .wbs import max_wbs_depth, task_wbs_assignments

__all__ = [
    # activity codes
    "ActivityCodeType",
    "activity_code_types",
    "task_code_assignments",
    # inventory
    "ProgrammeInventory",
    "RevisionInfo",
    "build_inventory",
    # milestones
    "MilestoneMatch",
    "MilestoneSeries",
    "MilestoneShiftResult",
    "ShiftPoint",
    "match_milestones",
    "track_milestone_shifts",
    # variance
    "VarianceGroup",
    "VarianceResult",
    "combine_mappings",
    "compute_variance",
    "compute_variance_by_mapping",
    # wbs
    "max_wbs_depth",
    "task_wbs_assignments",
    # critical path
    "CriticalPathResult",
    "PathActivity",
    "PathLink",
    "end_activity_candidates",
    "extract_critical_path",
    "extract_longest_path",
    # narrative prompts
    "build_critical_path_prompt",
    "build_inventory_prompt",
    "build_milestone_prompt",
    "build_variance_prompt",
    # excel
    "build_critical_path_xlsx",
    "build_inventory_xlsx",
    "build_milestone_xlsx",
    "build_variance_xlsx",
]
