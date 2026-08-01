"""Typed records for the isolated RLPA/APvAB v2 module.

The public types deliberately keep evidence, engine interpretation and expert
conclusion in different objects.  A report row can therefore be attributed to
one epistemic layer without smuggling an inference into a source observation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


RULESET_VERSION = "rlpa-apvab-v2.0.0"
SPECIFICATION_VERSION = "3.1"


class Layer(str, Enum):
    EVIDENCE = "layer_1_evidence"
    INTERPRETATION = "layer_2_interpretation"
    CONCLUSION = "layer_3_expert_conclusion"


class NodeKind(str, Enum):
    ACTIVITY = "activity"
    MILESTONE = "milestone"
    INTERRUPTION = "interruption"


class EdgeKind(str, Enum):
    SEQUENCE = "sequence"
    BOUNDING = "bounding"
    GENEALOGY = "genealogy"


class Tier(str, Enum):
    A = "A_strong"
    B = "B_supported"
    C = "C_weak"
    D = "D_insufficient"

    @property
    def rank(self) -> int:
        return {Tier.A: 4, Tier.B: 3, Tier.C: 2, Tier.D: 1}[self]


class EvidenceState(str, Enum):
    PRESENT = "present"
    PARTIAL = "partial"
    ABSENT = "absent"
    NOT_APPLICABLE = "not_applicable"


class ClassificationConfidence(str, Enum):
    EXPLICIT = "explicit"
    DERIVED = "derived"
    INFERRED = "inferred"
    AMBIGUOUS = "ambiguous"


class ResolutionStatus(str, Enum):
    CONFIRMED = "confirmed"
    PROBABLE = "probable"
    UNRESOLVED = "unresolved"


class Comparability(str, Enum):
    COMPARABLE = "comparable"
    NOT_COMPARABLE = "not_comparable"


class GateStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    RESTRICTED = "restricted"
    NOT_TESTED = "not_tested"


class InterruptionClass(str, Enum):
    EXPLAINED_PREDECESSOR = "explained_predecessor"
    EXPLAINED_CALENDAR = "explained_calendar"
    EXPLAINED_CONSTRAINT = "explained_constraint"
    EXPLAINED_RESOURCE = "explained_resource_programme_visible_only"
    UNEXPLAINED = "unexplained"
    UNEXPLAINED_WITHIN_COVERAGE = "unexplained_within_available_coverage"


class ReviewPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DivergenceClass(str, Enum):
    EXECUTION = "execution"
    SCOPE = "scope"
    LOGIC = "logic"
    ARTEFACT = "artefact"
    INDETERMINATE = "indeterminate"


class OperatingMode(str, Enum):
    DETERMINISTIC = "deterministic"
    MANAGED = "managed"
    BYOK = "byok"
    SELF_HOSTED = "self_hosted"


@dataclass(frozen=True, slots=True)
class SourceRef:
    file_hash: str
    table: str
    row: int
    field: str
    value: str


@dataclass(frozen=True, slots=True)
class Classification:
    category: str
    value: str | None
    confidence: ClassificationConfidence
    source: str
    reason: str


@dataclass(frozen=True, slots=True)
class ActivityNode:
    node_id: str
    snapshot_id: str
    task_id: str
    task_code: str
    original_name: str
    normalised_name: str
    wbs_path: str
    task_type: str
    status: str
    actual_start: datetime | None
    actual_finish: datetime | None
    planned_start: datetime | None
    planned_finish: datetime | None
    original_duration_days: float | None
    actual_duration_working_days: float | None
    remaining_duration_days: float | None
    data_date: datetime | None
    calendar_id: str
    classifications: tuple[Classification, ...]
    predecessors: tuple[str, ...]
    successors: tuple[str, ...]
    constraint_type: str
    constraint_date: datetime | None
    total_float_days: float | None
    free_float_days: float | None
    longest_path_flag: bool
    critical_flag: bool
    identity_fingerprint: str
    resolution_status: ResolutionStatus
    comparability: Comparability
    source_refs: tuple[SourceRef, ...]
    layer: Layer = field(default=Layer.EVIDENCE, init=False)
    kind: NodeKind = field(default=NodeKind.ACTIVITY, init=False)

    def classification(self, category: str) -> Classification | None:
        return next((c for c in self.classifications
                     if c.category == category), None)

    @property
    def workfront(self) -> str:
        parts = []
        for category in ("location", "system", "discipline", "package"):
            item = self.classification(category)
            if item and item.value:
                parts.append(item.value)
        return " | ".join(parts) or self.wbs_path or "unclassified"


@dataclass(frozen=True, slots=True)
class MilestoneNode:
    node_id: str
    snapshot_id: str
    task_id: str
    task_code: str
    name: str
    actual_date: datetime | None
    milestone_category: str
    relevance_rank: int
    constraint_type: str
    constraint_date: datetime | None
    source_refs: tuple[SourceRef, ...]
    layer: Layer = field(default=Layer.EVIDENCE, init=False)
    kind: NodeKind = field(default=NodeKind.MILESTONE, init=False)


@dataclass(frozen=True, slots=True)
class InterruptionNode:
    node_id: str
    snapshot_id: str
    workfront: str
    period_start: datetime
    period_end: datetime
    working_days: float
    calendar_id: str
    bounding_predecessor_node_id: str
    bounding_successor_node_id: str
    candidate_population: tuple[str, ...]
    exclusion_set: tuple[str, ...]
    negative_evidence_bundle_id: str
    source_refs: tuple[SourceRef, ...]
    layer: Layer = field(default=Layer.EVIDENCE, init=False)
    kind: NodeKind = field(default=NodeKind.INTERRUPTION, init=False)


@dataclass(frozen=True, slots=True)
class SequenceEdge:
    edge_id: str
    predecessor_node_id: str
    successor_node_id: str
    sequence_type: str
    interval_working_days: float
    source_refs: tuple[SourceRef, ...]
    layer: Layer = field(default=Layer.EVIDENCE, init=False)
    kind: EdgeKind = field(default=EdgeKind.SEQUENCE, init=False)


@dataclass(frozen=True, slots=True)
class BoundingEdge:
    edge_id: str
    source_node_id: str
    target_node_id: str
    boundary: str
    layer: Layer = field(default=Layer.EVIDENCE, init=False)
    kind: EdgeKind = field(default=EdgeKind.BOUNDING, init=False)


@dataclass(frozen=True, slots=True)
class GenealogyEdge:
    edge_id: str
    predecessor_node_id: str
    successor_node_id: str
    transition: str
    resolution_status: ResolutionStatus
    comparability: Comparability
    reason: str
    layer: Layer = field(default=Layer.EVIDENCE, init=False)
    kind: EdgeKind = field(default=EdgeKind.GENEALOGY, init=False)


@dataclass(frozen=True, slots=True)
class EvidenceFactor:
    reference: str
    state: EvidenceState
    observation: str
    layer: Layer = field(default=Layer.EVIDENCE, init=False)


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    bundle_id: str
    predecessor_node_id: str
    successor_node_id: str
    factors: tuple[EvidenceFactor, ...]
    source_refs: tuple[SourceRef, ...]
    layer: Layer = field(default=Layer.EVIDENCE, init=False)

    def factor(self, reference: str) -> EvidenceFactor:
        return next(f for f in self.factors if f.reference == reference)


@dataclass(frozen=True, slots=True)
class GateResult:
    gate: str
    passed: bool
    observation: str


@dataclass(frozen=True, slots=True)
class HypothesisResult:
    reference: str
    viable: bool
    observation: str


@dataclass(frozen=True, slots=True)
class CandidateInterpretation:
    interpretation_id: str
    predecessor_node_id: str
    successor_node_id: str
    evidence_bundle_id: str | None
    gates: tuple[GateResult, ...]
    admissible: bool
    exclusion_reason: str | None
    tier: Tier
    strongest_alternative_id: str | None
    alternative_comparison: str
    uniqueness_margin: str
    hypotheses: tuple[HypothesisResult, ...]
    caps_applied: tuple[str, ...]
    contest_flag: bool
    review_priority: ReviewPriority
    discriminating_question: str
    ruleset_version: str = RULESET_VERSION
    layer: Layer = field(default=Layer.INTERPRETATION, init=False)


@dataclass(frozen=True, slots=True)
class NegativeEvidenceBundle:
    bundle_id: str
    factors: tuple[EvidenceFactor, ...]
    layer: Layer = field(default=Layer.EVIDENCE, init=False)


@dataclass(frozen=True, slots=True)
class InterruptionInterpretation:
    interpretation_id: str
    interruption_node_id: str
    classification: InterruptionClass
    tier: Tier
    review_priority: ReviewPriority
    completion_correspondence: str
    coverage_qualification: str
    discriminating_question: str
    ruleset_version: str = RULESET_VERSION
    layer: Layer = field(default=Layer.INTERPRETATION, init=False)


@dataclass(frozen=True, slots=True)
class PathElement:
    order: int
    node_id: str
    element_type: NodeKind
    tier: Tier
    basis: str
    governing_cap: str | None


@dataclass(frozen=True, slots=True)
class PathInterpretation:
    path_id: str
    graph_version: str
    anchor_node_id: str
    query_definition: str
    elements: tuple[PathElement, ...]
    alternative_paths: tuple[tuple[str, ...], ...]
    weakest_tier: Tier
    contested_count: int
    warnings: tuple[str, ...]
    layer: Layer = field(default=Layer.INTERPRETATION, init=False)


@dataclass(frozen=True, slots=True)
class ExpertDecision:
    decision_id: str
    element_id: str
    engine_interpretation: str
    decision: str
    reason: str
    analyst: str
    timestamp: datetime
    downstream_regeneration: str
    layer: Layer = field(default=Layer.CONCLUSION, init=False)


@dataclass(frozen=True, slots=True)
class FitnessGate:
    gate: str
    status: GateStatus
    measured: str
    threshold: str
    consequence: str


@dataclass(frozen=True, slots=True)
class FitnessReport:
    gates: tuple[FitnessGate, ...]
    reliability: str
    reasons: tuple[str, ...]
    allowed_steps: tuple[int, ...]
    thresholds_provisional: bool = True
    layer: Layer = field(default=Layer.EVIDENCE, init=False)

    def gate(self, name: str) -> FitnessGate:
        return next(g for g in self.gates if g.gate == name)


@dataclass(frozen=True, slots=True)
class IngestionRecord:
    snapshot_id: str
    filename: str
    sha256: str
    size_bytes: int
    source_format: str
    source_tool: str
    project_id: str
    project_name: str
    data_date: datetime | None
    declared_programme_type: str
    assessed_programme_type: str
    source_encoding: str | None
    warnings: tuple[str, ...]
    layer: Layer = field(default=Layer.EVIDENCE, init=False)


@dataclass(frozen=True, slots=True)
class WindowComparison:
    window_id: str
    start: datetime | None
    end: datetime | None
    start_snapshot_id: str
    end_snapshot_id: str
    planned_path: tuple[str, ...]
    probable_as_built_path: tuple[str, ...]
    completion_movement_working_days: float | None
    displaced_from_planned: tuple[str, ...]
    entered_as_built: tuple[str, ...]
    divergence: DivergenceClass
    date_movement_suppressed: bool
    suppression_reason: str | None
    tier: Tier
    layer: Layer = field(default=Layer.INTERPRETATION, init=False)


@dataclass(frozen=True, slots=True)
class MigrationRecord:
    window_id: str
    previous_controlling_path: str
    new_controlling_path: str
    migration_point: str
    tier: Tier
    explanation: str
    artefact_or_execution: str
    layer: Layer = field(default=Layer.INTERPRETATION, init=False)


@dataclass(frozen=True, slots=True)
class ModelAccessAudit:
    operating_mode: OperatingMode
    key_source: str
    key_fingerprint: str
    endpoint: str
    egress_occurred: bool
    transmitted_fields: tuple[str, ...]
    model_identifier: str
    model_version: str
    prompt_version: str
    temperature: float | None
    seed: int | None
    deterministic_count: int
    model_assisted_count: int
    degraded_count: int


@dataclass(slots=True)
class ProgrammeSnapshot:
    record: IngestionRecord
    source_data: Any
    activity_nodes: dict[str, ActivityNode] = field(default_factory=dict)
    milestone_nodes: dict[str, MilestoneNode] = field(default_factory=dict)
    scheduling_options: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AnalysisRun:
    run_id: str
    ruleset_version: str
    specification_version: str
    created_utc: datetime
    ingestion: tuple[IngestionRecord, ...]
    fitness: FitnessReport
    model_access: ModelAccessAudit
    graph_version: str
    anchor_node_id: str | None
    path: PathInterpretation | None
    windows: tuple[WindowComparison, ...]
    migrations: tuple[MigrationRecord, ...]
    warnings: tuple[str, ...]
    calibration_statement: str

