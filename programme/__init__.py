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
from .comparison_impact import (
    ComparisonImpact,
    ProvenanceResult,
    ProvenanceWindow,
    RankedChange,
    assess_comparison_impact,
    build_provenance,
)
from .basis import (
    SCHED_OPTION_LABELS,
    progress_treatment,
    sched_options_row,
    sched_options_summary,
)
from .concurrency import (
    CONCURRENCY_CAVEATS,
    ConcurrencyResult,
    ConcurrencyWindow,
    EventSpan,
    classify_responsibility,
    screen_concurrency,
)
from .impacted_asplanned import IAP_CAVEATS, run_impacted_asplanned
from .oos import (
    OOS_CAVEATS,
    OOSEvolution,
    OOSWindow,
    OutOfSequenceFlag,
    REPAIR_CAVEATS,
    RepairItem,
    RepairReport,
    apply_asbuilt_repairs,
    build_repair_plan,
    oos_evolution,
    out_of_sequence_flags,
)
from .critical_path import (
    CriticalPathResult,
    PathActivity,
    PathLink,
    end_activity_candidates,
    extract_critical_path,
    extract_longest_path,
)
from .events_extract import (
    EXTRACTION_SYSTEM_PROMPT,
    EventCandidate,
    RP52R06_CAVEAT,
    build_event_extraction_prompt,
    parse_event_candidates,
    truncation_notes,
    read_document,
    recommended_analysis_schedule,
)
from .explain import (
    DriverShift,
    ExplainResult,
    ExplainWindow,
    ForecastPoint,
    explain_delay,
)
from .float_erosion import (
    FloatDelta,
    FloatErosionResult,
    FloatSnapshot,
    WindowErosion,
    analyse_float_erosion,
)
from .gantt_html import build_gantt_html, group_tree
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
    build_explain_prompt,
    build_float_erosion_prompt,
    build_progress_prompt,
    build_resources_prompt,
    build_sequence_prompt,
    build_tia_prompt,
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
    build_custody_xlsx,
    build_impact_xlsx,
    build_transfer_xlsx,
    build_oos_xlsx,
    build_concurrency_xlsx,
    build_iap_xlsx,
    build_critical_path_xlsx,
    build_explain_xlsx,
    build_float_erosion_xlsx,
    build_hierarchy_xlsx,
    build_progress_xlsx,
    build_resources_xlsx,
    build_sequence_xlsx,
    build_tia_xlsx,
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
from .tia import (
    DelayEvent,
    EventScopeAssessment,
    FRAGNET_SYSTEM_PROMPT,
    LOGIC_SYSTEM_PROMPT,
    FragnetActivity,
    FragnetLink,
    MilestoneImpact,
    TIAResult,
    FRAGNET_VARIANTS,
    build_fragnet_prompt,
    build_fragnet_variant_prompt,
    build_logic_recommendation_prompt,
    assess_event_scope,
    event_from_dict,
    event_to_dict,
    find_template_activities,
    find_template_work_packages,
    register_from_json,
    register_to_json,
    links_to_text,
    parse_fragnet_json,
    parse_logic_recommendation_json,
    parse_links,
    run_tia,
    run_cumulative_tia,
    CUMULATIVE_CAVEAT,
    validate_fragnet,
)
from .progress_transfer import (
    ProgressTransferResult,
    TransferMilestone,
    run_progress_transfer,
)
from .store import (
    STORE_CAVEATS,
    AnalysisRecord,
    FileRecord,
    ProjectStore,
)
from .xer_export import EXPORT_CAVEAT, build_impacted_xer
from .variance import (
    VarianceGroup,
    VarianceResult,
    combine_mappings,
    compute_variance,
    compute_variance_by_mapping,
)
from .notice import (
    CLAUSE_SYSTEM_PROMPT,
    NOTICE_CAVEAT,
    NoticeAssessment,
    assess_notice,
    build_clause_extraction_prompt,
    parse_clause_extraction,
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
    "group_tree",
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
    # comparison impact & materiality
    "ComparisonImpact",
    "OutOfSequenceFlag",
    "ProvenanceResult",
    "ProvenanceWindow",
    "RankedChange",
    "assess_comparison_impact",
    "build_provenance",
    "out_of_sequence_flags",
    "oos_evolution",
    "OOSEvolution",
    "OOSWindow",
    "OOS_CAVEATS",
    "REPAIR_CAVEATS",
    "RepairItem",
    "RepairReport",
    "apply_asbuilt_repairs",
    "build_repair_plan",
    # progress transfer
    "ProgressTransferResult",
    "TransferMilestone",
    "run_progress_transfer",
    # project library / custody register
    "STORE_CAVEATS",
    "AnalysisRecord",
    "FileRecord",
    "ProjectStore",
    # critical path
    "CriticalPathResult",
    "PathActivity",
    "PathLink",
    "end_activity_candidates",
    "extract_critical_path",
    "extract_longest_path",
    # event extraction (TIA intake)
    "EXTRACTION_SYSTEM_PROMPT",
    "EventCandidate",
    "RP52R06_CAVEAT",
    "build_event_extraction_prompt",
    "parse_event_candidates",
    "truncation_notes",
    "read_document",
    "recommended_analysis_schedule",
    # explain this delay
    "DriverShift",
    "ExplainResult",
    "ExplainWindow",
    "ForecastPoint",
    "explain_delay",
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
    # tia
    "DelayEvent",
    "EventScopeAssessment",
    "FRAGNET_SYSTEM_PROMPT",
    "LOGIC_SYSTEM_PROMPT",
    "FragnetActivity",
    "FragnetLink",
    "MilestoneImpact",
    "TIAResult",
    "FRAGNET_VARIANTS",
    "build_fragnet_prompt",
    "build_fragnet_variant_prompt",
    "build_logic_recommendation_prompt",
    "assess_event_scope",
    "event_from_dict",
    "event_to_dict",
    "register_from_json",
    "register_to_json",
    "find_template_activities",
    "find_template_work_packages",
    "links_to_text",
    "parse_fragnet_json",
    "parse_logic_recommendation_json",
    "parse_links",
    "run_tia",
    "run_cumulative_tia",
    "CLAUSE_SYSTEM_PROMPT",
    "NOTICE_CAVEAT",
    "NoticeAssessment",
    "assess_notice",
    "build_clause_extraction_prompt",
    "parse_clause_extraction",
    "CUMULATIVE_CAVEAT",
    "EXPORT_CAVEAT",
    "build_impacted_xer",
    "validate_fragnet",
    # windows
    "PathShift",
    "WindowRow",
    "WindowsResult",
    "analyse_windows",
    # narrative prompts
    "build_asbuilt_prompt",
    "build_comparison_prompt",
    "build_explain_prompt",
    "build_float_erosion_prompt",
    "build_progress_prompt",
    "build_resources_prompt",
    "build_sequence_prompt",
    "build_tia_prompt",
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
    "build_custody_xlsx",
    "build_impact_xlsx",
    "build_transfer_xlsx",
    "build_oos_xlsx",
    "build_concurrency_xlsx",
    "build_iap_xlsx",
    "SCHED_OPTION_LABELS",
    "progress_treatment",
    "sched_options_row",
    "sched_options_summary",
    "CONCURRENCY_CAVEATS",
    "ConcurrencyResult",
    "ConcurrencyWindow",
    "EventSpan",
    "classify_responsibility",
    "screen_concurrency",
    "IAP_CAVEATS",
    "run_impacted_asplanned",
    "build_explain_xlsx",
    "build_float_erosion_xlsx",
    "build_progress_xlsx",
    "build_resources_xlsx",
    "build_sequence_xlsx",
    "build_tia_xlsx",
    "build_windows_xlsx",
    "build_critical_path_xlsx",
    "build_inventory_xlsx",
    "build_milestone_xlsx",
    "build_variance_xlsx",
]
