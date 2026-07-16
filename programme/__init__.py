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
from .asbuilt_path import (
    ActualTraceResult,
    AsBuiltPathResult,
    PersistenceEntry,
    StitchActivity,
    StitchWindow,
    TraceLink,
    TriangulationResult,
    analyse_asbuilt_path,
    extract_actual_trace,
    trace_end_candidates,
    triangulate,
)
from .comparison import (
    ActivityRef,
    ComparisonResult,
    FieldChange,
    LogicChange,
    compare_revisions,
)
from .critical_path import (
    CriticalPathResult,
    PathActivity,
    PathLink,
    end_activity_candidates,
    extract_critical_path,
    extract_longest_path,
)
from .float_erosion import (
    FloatDelta,
    FloatErosionResult,
    FloatSnapshot,
    WindowErosion,
    analyse_float_erosion,
)
from .gantt_html import build_gantt_html
from .hierarchy import (
    Dimension,
    sequence_dimension_mappings,
    GanttActivity,
    GanttNode,
    HierarchyResult,
    available_dimensions,
    build_hierarchy,
    config_from_json,
    config_to_json,
    tree_to_dict,
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
    build_asbuilt_prompt,
    build_comparison_prompt,
    build_critical_path_prompt,
    build_float_erosion_prompt,
    build_progress_prompt,
    build_resources_prompt,
    build_sequence_prompt,
    build_windows_prompt,
    build_inventory_prompt,
    build_milestone_prompt,
    build_variance_prompt,
)
from .report_docx import (
    BasisOfAnalysis,
    ReportSection,
    SourceFile,
    build_assembled_report,
)
from .report_xlsx import (
    build_asbuilt_xlsx,
    build_comparison_xlsx,
    build_critical_path_xlsx,
    build_float_erosion_xlsx,
    build_hierarchy_xlsx,
    build_progress_xlsx,
    build_resources_xlsx,
    build_sequence_xlsx,
    build_windows_xlsx,
    build_inventory_xlsx,
    build_milestone_xlsx,
    build_variance_xlsx,
)
from .resources import (
    HistogramPoint,
    ResourceInfo,
    ResourceLoadingResult,
    extract_resource_loading,
)
from .sequence_coding import (
    FrontStageBand,
    MappingRow,
    REVIEW_SYSTEM_PROMPT,
    STAGE_ORDER,
    UNCLASSIFIED,
    VIEW_ADVISOR_SYSTEM_PROMPT,
    SequenceMappingProposal,
    SequenceResult,
    analyse_sequence,
    build_mapping_review_prompt,
    build_view_advice_prompt,
    parse_mapping_review,
    parse_view_advice,
    propose_sequence_mapping,
)
from .variance import (
    VarianceGroup,
    VarianceResult,
    combine_mappings,
    compute_variance,
    compute_variance_by_mapping,
)
from .progress import (
    CurvePoint,
    ProgressResult,
    RevisionPoint,
    WEIGHT_OPTIONS,
    compute_progress,
)
from .windows import (
    PathShift,
    WindowRow,
    WindowsResult,
    analyse_windows,
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
    # hierarchy rebuild + gantt viewer
    "Dimension",
    "GanttActivity",
    "GanttNode",
    "HierarchyResult",
    "available_dimensions",
    "build_hierarchy",
    "build_gantt_html",
    "config_from_json",
    "config_to_json",
    "tree_to_dict",
    "sequence_dimension_mappings",
    "build_hierarchy_xlsx",
    # as-built path
    "AsBuiltPathResult",
    "PersistenceEntry",
    "StitchActivity",
    "StitchWindow",
    "ActualTraceResult",
    "TraceLink",
    "TriangulationResult",
    "analyse_asbuilt_path",
    "extract_actual_trace",
    "trace_end_candidates",
    "triangulate",
    # comparison
    "ActivityRef",
    "ComparisonResult",
    "FieldChange",
    "LogicChange",
    "compare_revisions",
    # critical path
    "CriticalPathResult",
    "PathActivity",
    "PathLink",
    "end_activity_candidates",
    "extract_critical_path",
    "extract_longest_path",
    # float erosion
    "FloatDelta",
    "FloatErosionResult",
    "FloatSnapshot",
    "WindowErosion",
    "analyse_float_erosion",
    # progress
    "CurvePoint",
    "ProgressResult",
    "RevisionPoint",
    "WEIGHT_OPTIONS",
    "compute_progress",
    # resources
    "HistogramPoint",
    "ResourceInfo",
    "ResourceLoadingResult",
    "extract_resource_loading",
    # sequence coding
    "FrontStageBand",
    "MappingRow",
    "STAGE_ORDER",
    "SequenceMappingProposal",
    "SequenceResult",
    "analyse_sequence",
    "REVIEW_SYSTEM_PROMPT",
    "UNCLASSIFIED",
    "VIEW_ADVISOR_SYSTEM_PROMPT",
    "build_mapping_review_prompt",
    "build_view_advice_prompt",
    "parse_mapping_review",
    "parse_view_advice",
    "propose_sequence_mapping",
    # windows
    "PathShift",
    "WindowRow",
    "WindowsResult",
    "analyse_windows",
    # narrative prompts
    "build_asbuilt_prompt",
    "build_comparison_prompt",
    "build_float_erosion_prompt",
    "build_progress_prompt",
    "build_resources_prompt",
    "build_sequence_prompt",
    "build_windows_prompt",
    "build_critical_path_prompt",
    "build_inventory_prompt",
    "build_milestone_prompt",
    "build_variance_prompt",
    # assembled report (docx)
    "BasisOfAnalysis",
    "ReportSection",
    "SourceFile",
    "build_assembled_report",
    # excel
    "build_asbuilt_xlsx",
    "build_comparison_xlsx",
    "build_float_erosion_xlsx",
    "build_progress_xlsx",
    "build_resources_xlsx",
    "build_sequence_xlsx",
    "build_windows_xlsx",
    "build_critical_path_xlsx",
    "build_inventory_xlsx",
    "build_milestone_xlsx",
    "build_variance_xlsx",
]
