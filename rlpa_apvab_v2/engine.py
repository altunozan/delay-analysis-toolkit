"""Deterministic nine-step Retrospective Longest Path Analysis engine.

This module intentionally contains no model client and no contractual,
entitlement or concurrency classification.  It consumes programme data only.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from dcma.calendar import calendar_masks, working_days_between

from .adapter import GenealogySummary, build_genealogy, stable_id
from .config import RLPAConfig, UNCALIBRATED_STATEMENT
from .domain import (
    ActivityNode,
    AnalysisRun,
    BoundingEdge,
    CandidateInterpretation,
    ClassificationConfidence,
    DivergenceClass,
    EvidenceBundle,
    EvidenceFactor,
    EvidenceState,
    FitnessGate,
    FitnessReport,
    GateResult,
    GateStatus,
    HypothesisResult,
    InterruptionClass,
    InterruptionInterpretation,
    InterruptionNode,
    MigrationRecord,
    ModelAccessAudit,
    NegativeEvidenceBundle,
    NodeKind,
    OperatingMode,
    PathElement,
    PathInterpretation,
    ProgrammeSnapshot,
    RULESET_VERSION,
    ReviewPriority,
    SPECIFICATION_VERSION,
    SequenceEdge,
    Tier,
    WindowComparison,
)
from .graph import EvidenceGraph


_CALENDAR_MASK_CACHE: dict[str, dict[str, tuple]] = {}


@dataclass(frozen=True, slots=True)
class _Candidate:
    predecessor: ActivityNode
    successor: ActivityNode
    gates: tuple[GateResult, ...]
    admissible: bool
    exclusion_reason: str | None
    sequence_type: str
    interval: float
    assigned_logic: bool


@dataclass(frozen=True, slots=True)
class _Gap:
    predecessor: ActivityNode
    successor: ActivityNode
    start: datetime
    end: datetime
    working_days: float


@dataclass(slots=True)
class PipelineResult:
    run: AnalysisRun
    graph: EvidenceGraph
    snapshots: tuple[ProgrammeSnapshot, ...]
    candidate_interpretations: tuple[CandidateInterpretation, ...]
    interruption_interpretations: tuple[InterruptionInterpretation, ...]
    provisional_gap_count: int
    review_items: tuple[dict, ...] = field(default_factory=tuple)


def _classification_usable(node: ActivityNode, category: str) -> bool:
    item = node.classification(category)
    return bool(
        item and item.value and item.confidence in {
            ClassificationConfidence.EXPLICIT,
            ClassificationConfidence.DERIVED,
        }
    )


def _same_value(a: ActivityNode, b: ActivityNode, category: str) -> bool:
    av = a.classification(category)
    bv = b.classification(category)
    return bool(av and bv and av.value and bv.value
                and av.value.casefold() == bv.value.casefold())


def _class_value(node: ActivityNode, category: str) -> str:
    item = node.classification(category)
    return item.value if item and item.value else ""


def _work_type(node: ActivityNode) -> str:
    return _class_value(node, "work_type") or "general"


def _mask(snapshot: ProgrammeSnapshot, node: ActivityNode):
    masks = _CALENDAR_MASK_CACHE.get(snapshot.record.snapshot_id)
    if masks is None:
        # Bounded: a long-lived UI session re-running many uploads must not
        # pin every historical snapshot's masks in module memory.
        if len(_CALENDAR_MASK_CACHE) >= 16:
            _CALENDAR_MASK_CACHE.clear()
        masks = calendar_masks(snapshot.source_data)
        _CALENDAR_MASK_CACHE[snapshot.record.snapshot_id] = masks
    return masks.get(node.calendar_id)


def _working_days(
    snapshot: ProgrammeSnapshot,
    start: datetime,
    end: datetime,
    node: ActivityNode,
) -> float:
    return working_days_between(start, end, _mask(snapshot, node))


def _anchor_candidates(snapshot: ProgrammeSnapshot) -> list:
    result = [m for m in snapshot.milestone_nodes.values()
              if m.actual_date is not None]
    result.sort(key=lambda m: (m.relevance_rank,
                               -(m.actual_date.timestamp()
                                 if m.actual_date else 0)))
    return result


def _fitness(
    snapshots: tuple[ProgrammeSnapshot, ...],
    genealogy: GenealogySummary,
    config: RLPAConfig,
) -> FitnessReport:
    final = snapshots[-1]
    activities = [n for n in final.activity_nodes.values()
                  if n.task_type not in {"TT_LOE", "TT_WBS"}]
    actual_complete = sum(
        1 for n in activities if n.actual_start and n.actual_finish
    )
    actual_ratio = actual_complete / len(activities) if activities else 0.0

    starts: list[datetime] = []
    finishes: list[datetime] = []
    for activity in activities:
        start_value = activity.actual_start or activity.planned_start
        finish_value = activity.actual_finish or activity.planned_finish
        if start_value is not None:
            starts.append(start_value)
        if finish_value is not None:
            finishes.append(finish_value)
    if starts and finishes:
        span_days = max((max(finishes) - min(starts)).days, 1)
        density = len(activities) * 30.0 / span_days
    else:
        density = 0.0

    classed = sum(
        1 for n in activities
        if _classification_usable(n, "location")
        and _classification_usable(n, "discipline")
    )
    class_ratio = classed / len(activities) if activities else 0.0
    if len(snapshots) == 1:
        identity_status = GateStatus.RESTRICTED
        identity_ratio = 0.0
        identity_measured = "one programme only; migration unavailable"
    else:
        identity_ratio = genealogy.comparable_ratio
        identity_status = (
            GateStatus.PASS if identity_ratio
            >= config.comparable_identity_min else GateStatus.FAIL
        )
        identity_measured = f"{identity_ratio:.1%} comparable genealogy"
    anchor_count = len(_anchor_candidates(final))

    gates = (
        FitnessGate(
            "F1", GateStatus.PASS if actual_ratio
            >= config.actual_date_coverage_min else GateStatus.FAIL,
            f"{actual_ratio:.1%} reliable actual start-and-finish coverage",
            f">= {config.actual_date_coverage_min:.1%} (provisional)",
            "Below threshold: stop after Step 2 and title as planned-logic",
        ),
        FitnessGate(
            "F2", GateStatus.PASS if density
            >= config.activities_per_30_days_min else GateStatus.FAIL,
            f"{density:.2f} activities per 30 elapsed days",
            f">= {config.activities_per_30_days_min:.2f} (provisional)",
            "Below threshold: sequence/gaps only; no driving path",
        ),
        FitnessGate(
            "F3", GateStatus.PASS if class_ratio
            >= config.classification_yield_min else GateStatus.RESTRICTED,
            f"{class_ratio:.1%} location-and-discipline classification",
            f">= {config.classification_yield_min:.1%} (provisional)",
            "Restrict candidates to coded subsets; N1 not exhaustive",
        ),
        FitnessGate(
            "F4", identity_status, identity_measured,
            f">= {config.comparable_identity_min:.1%} (provisional)",
            "Suppress update transmission and Steps 7-8",
        ),
        FitnessGate(
            "F5", GateStatus.PASS if anchor_count else GateStatus.FAIL,
            f"{anchor_count} actual-dated completion/interface milestone(s)",
            ">= 1 relevant actual-dated milestone",
            "No backward trace anchor; suppress Step 6",
        ),
    )
    allowed = [1, 2, 9]
    if gates[0].status is GateStatus.PASS:
        allowed.extend([3, 5])
        if gates[1].status is GateStatus.PASS:
            allowed.append(4)
            if gates[4].status is GateStatus.PASS:
                allowed.append(6)
        if gates[3].status is GateStatus.PASS:
            allowed.extend([7, 8])
    failures = [g for g in gates if g.status is GateStatus.FAIL]
    restrictions = [g for g in gates if g.status is GateStatus.RESTRICTED]
    if any(g.gate in {"F1", "F5"} for g in failures):
        reliability = "Insufficient"
    elif failures or len(restrictions) >= 2:
        reliability = "Low"
    elif restrictions:
        reliability = "Medium"
    else:
        reliability = "High"
    reasons = tuple(
        f"{g.gate} {g.status.value}: {g.measured}" for g in gates
        if g.status is not GateStatus.PASS
    ) or ("All provisional fitness gates passed",)
    return FitnessReport(
        gates=gates,
        reliability=reliability,
        reasons=reasons,
        allowed_steps=tuple(sorted(set(allowed))),
    )


_TECHNICAL_ORDER = {
    "procurement": 1,
    "delivery": 2,
    "construction": 3,
    "installation": 3,
    "inspection": 4,
    "testing": 5,
    "energisation": 6,
    "commissioning": 7,
    "handover": 8,
    "completion": 9,
}


def _candidate_gates(
    snapshot: ProgrammeSnapshot,
    pred: ActivityNode,
    succ: ActivityNode,
    *,
    assigned: bool,
    config: RLPAConfig,
) -> tuple[tuple[GateResult, ...], str, float]:
    sequence_type = "uncertain"
    if pred.actual_finish and succ.actual_start:
        interval = _working_days(
            snapshot, pred.actual_finish, succ.actual_start, succ
        )
        temporal = pred.actual_finish <= succ.actual_start
        sequence_type = "finish-to-start" if temporal else "overlapping"
    else:
        interval = 0.0
        temporal = False
    g1 = temporal
    shared = [category for category in ("location", "system", "discipline")
              if _same_value(pred, succ, category)]
    release = any(token in pred.original_name.lower() for token in (
        "release", "access", "approval", "handover", "permit"
    ))
    g2 = bool(shared or assigned or release)
    classified = (
        pred.actual_start is not None and pred.actual_finish is not None
        and succ.actual_start is not None
        and ((
            _classification_usable(pred, "location")
            and _classification_usable(succ, "location")
        ) or assigned or release)
    )
    pred_order = _TECHNICAL_ORDER.get(_work_type(pred))
    succ_order = _TECHNICAL_ORDER.get(_work_type(succ))
    technical = not (
        pred_order is not None and succ_order is not None
        and pred_order > succ_order
    )
    if sequence_type == "overlapping":
        technical = False  # progressive inference is deliberately deferred
    constraint_aligned = False
    if succ.constraint_date and succ.actual_start:
        constraint_aligned = abs(_working_days(
            snapshot, succ.constraint_date, succ.actual_start, succ
        )) <= config.constraint_alignment_tolerance_days
    g5 = not constraint_aligned
    gates = (
        GateResult("G1", g1,
                   f"finish-to-start interval {interval:.2f} working days"
                   if pred.actual_finish and succ.actual_start else
                   "reliable bounding dates unavailable"),
        GateResult("G2", g2,
                   "shared " + ", ".join(shared) if shared else
                   "assigned/interface relationship" if assigned or release
                   else "no shared workfront, system or interface"),
        GateResult("G3", classified,
                   "actual dates and usable classification available"
                   if classified else "actual dates/classification insufficient"),
        GateResult("G4", technical,
                   "work-type order is technically possible"
                   if technical else "impossible or deferred progressive sequence"),
        GateResult("G5", g5,
                   "successor start is not aligned to a governing constraint"
                   if g5 else "successor start aligns with constraint date"),
    )
    return gates, sequence_type, interval


def _candidate_population(
    snapshot: ProgrammeSnapshot, config: RLPAConfig
) -> list[_Candidate]:
    nodes = list(snapshot.activity_nodes.values())
    actual = [n for n in nodes if n.actual_start and n.actual_finish is not None
              and n.task_type not in {"TT_LOE", "TT_WBS"}]
    by_task = snapshot.activity_nodes
    blocks: dict[tuple[str, str], list[ActivityNode]] = defaultdict(list)
    for node in actual:
        blocks[("workfront", node.workfront.casefold())].append(node)
        for category in ("location", "system", "discipline"):
            value = _class_value(node, category).casefold()
            if value:
                blocks[(category, value)].append(node)

    output: list[_Candidate] = []
    for succ in actual:
        succ_start = succ.actual_start
        if succ_start is None:
            continue
        candidates: dict[str, ActivityNode] = {}
        for pred_id in succ.predecessors:
            if pred_id in by_task:
                candidates[pred_id] = by_task[pred_id]
        # Exact workfront/location/system blocks are selective. Discipline is
        # used only as a fallback: a broad "Civil" or "MEP" code can otherwise
        # recreate the full Cartesian product on a field programme.
        for pred in blocks.get(("workfront", succ.workfront.casefold()), ()):
            candidates[pred.task_id] = pred
        for category in ("location", "system"):
            value = _class_value(succ, category).casefold()
            if value:
                for pred in blocks.get((category, value), ()):
                    candidates[pred.task_id] = pred
        if len(candidates) <= 1:
            value = _class_value(succ, "discipline").casefold()
            if value:
                for pred in blocks.get(("discipline", value), ()):
                    candidates[pred.task_id] = pred

        assigned_ids = set(succ.predecessors)
        assigned_candidates = [
            pred for task_id, pred in candidates.items()
            if task_id in assigned_ids
        ]
        nonassigned: list[ActivityNode] = []
        for task_id, pred in candidates.items():
            pred_finish = pred.actual_finish
            if task_id in assigned_ids or pred_finish is None:
                continue
            if pred_finish > succ_start:
                continue
            # Elapsed-day prefilter is intentionally generous; exact working
            # time is calculated only after the frontier is bounded.
            if (succ_start - pred_finish).days \
                    > config.candidate_temporal_window_working_days * 3:
                continue
            nonassigned.append(pred)
        nonassigned.sort(
            key=lambda pred: pred.actual_finish or datetime.min,
            reverse=True,
        )
        frontier = assigned_candidates + nonassigned[
            :config.max_nonassigned_candidates_per_successor
        ]
        seen_frontier: set[str] = set()
        for pred in frontier:
            if pred.task_id in seen_frontier:
                continue
            seen_frontier.add(pred.task_id)
            pred_finish = pred.actual_finish
            if pred.task_id == succ.task_id or pred_finish is None:
                continue
            assigned = pred.task_id in succ.predecessors
            raw_interval = _working_days(
                snapshot, pred_finish, succ_start, succ
            )
            if (not assigned and raw_interval
                    > config.candidate_temporal_window_working_days):
                continue
            gates, sequence_type, interval = _candidate_gates(
                snapshot, pred, succ, assigned=assigned, config=config
            )
            failed = [g for g in gates if not g.passed]
            output.append(_Candidate(
                predecessor=pred,
                successor=succ,
                gates=gates,
                admissible=not failed,
                exclusion_reason=(
                    "; ".join(f"{g.gate}: {g.observation}" for g in failed)
                    if failed else None
                ),
                sequence_type=sequence_type,
                interval=interval,
                assigned_logic=assigned,
            ))
    return output


def _factor_state(points: int) -> EvidenceState:
    if points >= 2:
        return EvidenceState.PRESENT
    if points == 1:
        return EvidenceState.PARTIAL
    return EvidenceState.ABSENT


def _dependency_factor(pred: ActivityNode, succ: ActivityNode) -> EvidenceFactor:
    pair = (_work_type(pred), _work_type(succ))
    necessary = pair in {
        ("procurement", "delivery"), ("delivery", "installation"),
        ("construction", "inspection"), ("installation", "testing"),
        ("inspection", "testing"), ("testing", "energisation"),
        ("testing", "commissioning"),
        ("energisation", "commissioning"),
        ("commissioning", "handover"),
        ("commissioning", "completion"),
        ("handover", "completion"),
    }
    if necessary:
        return EvidenceFactor(
            "E3", EvidenceState.PRESENT,
            f"{pair[0]} to {pair[1]} is a physically necessary sequence",
        )
    return EvidenceFactor(
        "E3", EvidenceState.PARTIAL,
        f"{pair[0]} to {pair[1]} is possible but necessity is not "
        "established by deterministic programme classification",
    )


def _update_transmission(
    snapshots: tuple[ProgrammeSnapshot, ...],
    pred_code: str,
    succ_code: str,
    genealogy: GenealogySummary,
) -> EvidenceFactor:
    observations = 0
    transmitted = 0
    boundaries = 0
    option_boundaries = 0
    for index, (old, new) in enumerate(
        zip(snapshots, snapshots[1:], strict=False)
    ):
        # §9.3.4 binding rule: E5 cannot be asserted across a
        # non-comparable genealogy boundary.
        blocked = (genealogy.pair_non_comparable[index]
                   if index < len(genealogy.pair_non_comparable)
                   else frozenset())
        if pred_code in blocked or succ_code in blocked:
            boundaries += 1
            continue
        # R9: retained-logic/progress-override discontinuities make
        # cross-boundary date-movement inference invalid.
        if old.scheduling_options != new.scheduling_options:
            option_boundaries += 1
            continue
        old_by_code = {n.task_code: n for n in old.activity_nodes.values()}
        new_by_code = {n.task_code: n for n in new.activity_nodes.values()}
        op, np = old_by_code.get(pred_code), new_by_code.get(pred_code)
        os, ns = old_by_code.get(succ_code), new_by_code.get(succ_code)
        if op is None or np is None or os is None or ns is None:
            boundaries += 1
            continue
        pred_old = op.actual_finish or op.planned_finish
        pred_new = np.actual_finish or np.planned_finish
        succ_old = os.actual_start or os.planned_start
        succ_new = ns.actual_start or ns.planned_start
        if (pred_old is None or pred_new is None
                or succ_old is None or succ_new is None):
            continue
        observations += 1
        dp = (pred_new - pred_old).total_seconds() / 86400.0
        ds = (succ_new - succ_old).total_seconds() / 86400.0
        if abs(dp) > 0.01 and abs(ds) > 0.01 and dp * ds > 0 \
                and abs(dp - ds) <= 2.0:
            transmitted += 1
    if transmitted:
        # §12.4 update-mode downgrade: transmission observed but part of
        # the update set was suppressed → Partial, never Present.
        state = (EvidenceState.PARTIAL if option_boundaries
                 else EvidenceState.PRESENT)
    elif observations:
        state = EvidenceState.ABSENT
    else:
        state = EvidenceState.NOT_APPLICABLE
    return EvidenceFactor(
        "E5", state,
        f"{transmitted}/{observations} comparable update interval(s) showed "
        f"aligned movement; {boundaries} identity boundary/boundaries and "
        f"{option_boundaries} scheduling-option boundary/boundaries omitted",
    )


def _base_factors(
    candidate: _Candidate,
    snapshots: tuple[ProgrammeSnapshot, ...],
    pattern_count: int,
    genealogy: GenealogySummary,
    config: RLPAConfig,
) -> tuple[EvidenceFactor, ...]:
    if candidate.interval <= config.temporal_adjacency_present_days:
        e1 = EvidenceState.PRESENT
    elif candidate.interval <= config.temporal_adjacency_partial_days:
        e1 = EvidenceState.PARTIAL
    else:
        e1 = EvidenceState.ABSENT
    shared = [category for category in ("location", "system", "discipline")
              if _same_value(candidate.predecessor,
                             candidate.successor, category)]
    e2 = (EvidenceState.PRESENT if len(shared) >= 2
          else EvidenceState.PARTIAL if shared else EvidenceState.ABSENT)
    e4 = (EvidenceState.PRESENT
          if pattern_count >= config.pattern_replication_min
          else EvidenceState.PARTIAL if pattern_count > 1
          else EvidenceState.ABSENT)
    return (
        EvidenceFactor(
            "E1", e1,
            f"{candidate.interval:.2f} working-day interval on successor calendar",
        ),
        EvidenceFactor(
            "E2", e2,
            "Shared " + ", ".join(shared) if shared
            else "No shared spatial/system/discipline classification",
        ),
        _dependency_factor(candidate.predecessor, candidate.successor),
        EvidenceFactor(
            "E4", e4,
            f"Equivalent work-type pairing observed in {pattern_count} "
            "classified workfront(s)",
        ),
        _update_transmission(
            snapshots,
            candidate.predecessor.task_code,
            candidate.successor.task_code,
            genealogy,
        ),
        EvidenceFactor(
            "E7",
            EvidenceState.PRESENT if candidate.assigned_logic
            else EvidenceState.ABSENT,
            "Assigned relationship exists; corroboration only"
            if candidate.assigned_logic else "No assigned relationship",
        ),
    )


def _internal_points(factors: Iterable[EvidenceFactor]) -> int:
    weights = {"E1": 3, "E2": 3, "E3": 4, "E4": 2,
               "E5": 3, "E7": 1}
    total = 0
    for factor in factors:
        if factor.state is EvidenceState.PRESENT:
            total += weights.get(factor.reference, 0)
        elif factor.state is EvidenceState.PARTIAL:
            total += 1
    return total


def _tier_from_factors(
    factors: tuple[EvidenceFactor, ...], clear_margin: bool,
    hypotheses: tuple[HypothesisResult, ...], config: RLPAConfig,
) -> Tier:
    by_ref = {f.reference: f for f in factors}
    core = all(by_ref[ref].state is EvidenceState.PRESENT
               for ref in ("E1", "E2", "E3"))
    corroborator = any(by_ref[ref].state is EvidenceState.PRESENT
                       for ref in ("E4", "E5", "E6"))
    replicated = (
        by_ref["E4"].state is EvidenceState.PRESENT
        or by_ref["E5"].state is EvidenceState.PRESENT
    )
    viable = any(h.viable for h in hypotheses)
    if core and replicated and clear_margin and not viable:
        return Tier.A
    if core and corroborator and not viable:
        return Tier.B
    if all(by_ref[r].state is not EvidenceState.ABSENT
           for r in ("E1", "E2", "E3")):
        return Tier.C
    return Tier.D


def _apply_cap(tier: Tier, cap: Tier) -> Tier:
    return tier if tier.rank <= cap.rank else cap


def _interpret_candidates(
    snapshot: ProgrammeSnapshot,
    snapshots: tuple[ProgrammeSnapshot, ...],
    candidates: list[_Candidate],
    graph: EvidenceGraph,
    genealogy: GenealogySummary,
    config: RLPAConfig,
) -> list[CandidateInterpretation]:
    pattern_locations: dict[tuple[str, str], set[str]] = defaultdict(set)
    for candidate in candidates:
        if candidate.admissible:
            pattern_locations[
                (_work_type(candidate.predecessor),
                 _work_type(candidate.successor))
            ].add(_class_value(candidate.successor, "location") or
                  candidate.successor.workfront)

    factor_map: dict[tuple[str, str], tuple[EvidenceFactor, ...]] = {}
    points: dict[tuple[str, str], int] = {}
    grouped: dict[str, list[_Candidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.successor.node_id].append(candidate)
        if not candidate.admissible:
            continue
        pattern_count = len(pattern_locations[
            (_work_type(candidate.predecessor),
             _work_type(candidate.successor))
        ])
        factors = _base_factors(
            candidate, snapshots, pattern_count, genealogy, config
        )
        key = (candidate.predecessor.node_id,
               candidate.successor.node_id)
        factor_map[key] = factors
        points[key] = _internal_points(factors)

    output: list[CandidateInterpretation] = []
    for _successor_id, group in grouped.items():
        ordered = sorted(
            (item for item in group if item.admissible),
            key=lambda item: points[(item.predecessor.node_id,
                                     item.successor.node_id)],
            reverse=True,
        )
        for candidate in group:
            key = (candidate.predecessor.node_id,
                   candidate.successor.node_id)
            interpretation_id = stable_id("candidate", *key)
            if not candidate.admissible:
                output.append(CandidateInterpretation(
                    interpretation_id=interpretation_id,
                    predecessor_node_id=key[0],
                    successor_node_id=key[1],
                    evidence_bundle_id=None,
                    gates=candidate.gates,
                    admissible=False,
                    exclusion_reason=candidate.exclusion_reason,
                    tier=Tier.D,
                    strongest_alternative_id=None,
                    alternative_comparison="Candidate excluded by binary gate",
                    uniqueness_margin="not applicable",
                    hypotheses=(),
                    caps_applied=(),
                    contest_flag=False,
                    review_priority=ReviewPriority.LOW,
                    discriminating_question="None; gate failure is deterministic",
                ))
                continue
            score = points[key]
            alternatives = [other for other in ordered
                            if other.predecessor.node_id != key[0]]
            alternative = alternatives[0] if alternatives else None
            alt_score = (points[(alternative.predecessor.node_id,
                                 alternative.successor.node_id)]
                         if alternative else None)
            margin_points = score - alt_score if alt_score is not None else 99
            margin = ("clear" if margin_points
                      >= config.clear_margin_internal_points else "narrow")
            e6_state = (EvidenceState.PRESENT if margin == "clear"
                        else EvidenceState.ABSENT)
            factors = factor_map[key] + (EvidenceFactor(
                "E6", e6_state,
                "Clear separation from strongest admissible alternative"
                if margin == "clear" else
                "Strongest admissible alternative is materially similar",
            ),)
            pred, succ = candidate.predecessor, candidate.successor
            same_party = _same_value(pred, succ, "responsible_party")
            h1 = same_party and _dependency_factor(
                pred, succ).state is not EvidenceState.PRESENT
            h2 = bool(succ.constraint_date and not candidate.gates[4].passed)
            h4 = len(group) >= config.coincidence_density_count
            options_changed = any(
                old.scheduling_options != new.scheduling_options
                for old, new in zip(snapshots, snapshots[1:], strict=False)
            )
            # H5 is a per-candidate artefact signature. A set-wide
            # scheduling-option change is NOT one: its consequence is the
            # §12.4 update-mode cap below (E5 downgraded; max Tier B when
            # E5 was the sole corroborator), never a blanket Tier C.
            h5 = candidate.sequence_type == "overlapping"
            hypotheses = (
                HypothesisResult(
                    "H1", h1,
                    "Shared responsible party and no programme-established "
                    "technical necessity" if h1 else
                    "Resource continuity signature not observed",
                ),
                HypothesisResult(
                    "H2", h2,
                    "Constraint/calendar governance remains viable" if h2
                    else "Constraint/calendar governance not observed",
                ),
                HypothesisResult(
                    "H3", False,
                    "Assessed at successor-set and interruption stage",
                ),
                HypothesisResult(
                    "H4", h4,
                    f"{len(group)} blocked candidates around successor",
                ),
                HypothesisResult(
                    "H5", h5,
                    "Overlapping actuals observed on this pair"
                    if h5 else "No scheduling artefact signature observed",
                ),
            )
            tier = _tier_from_factors(
                factors, margin == "clear", hypotheses, config
            )
            caps: list[str] = []
            if h1:
                tier = _apply_cap(tier, Tier.C)
                caps.append("resource continuity cap: maximum Tier C")
            if h5:
                tier = _apply_cap(tier, Tier.C)
                caps.append("artefact cap: maximum Tier C")
            if options_changed:
                by_ref = {f.reference: f for f in factors}
                other_corroborator = any(
                    by_ref[ref].state is EvidenceState.PRESENT
                    for ref in ("E4", "E6")
                )
                if not other_corroborator:
                    tier = _apply_cap(tier, Tier.B)
                    caps.append(
                        "update-mode cap: scheduling options differ across "
                        "the update set and E5 was the only corroborating "
                        "route; maximum Tier B"
                    )
            if alternatives and margin == "narrow":
                tier = _apply_cap(tier, Tier.C)
                caps.append("narrow/equal alternative cap: maximum Tier C")
            if candidate.interval > config.temporal_adjacency_partial_days:
                e4 = next(f for f in factors if f.reference == "E4")
                e5 = next(f for f in factors if f.reference == "E5")
                if (e4.state is not EvidenceState.PRESENT
                        and e5.state is not EvidenceState.PRESENT):
                    tier = _apply_cap(tier, Tier.C)
                    caps.append("R4 remote-predecessor cap: maximum Tier C")
            contest = (
                tier in {Tier.C, Tier.D} or margin == "narrow"
                or any(h.viable for h in hypotheses) or bool(caps)
            )
            bundle_id = stable_id("evidence", *key)
            graph.add_evidence_bundle(EvidenceBundle(
                bundle_id=bundle_id,
                predecessor_node_id=key[0],
                successor_node_id=key[1],
                factors=factors,
                source_refs=pred.source_refs + succ.source_refs,
            ))
            graph.add_edge(SequenceEdge(
                edge_id=stable_id("sequence", *key),
                predecessor_node_id=key[0],
                successor_node_id=key[1],
                sequence_type=candidate.sequence_type,
                interval_working_days=candidate.interval,
                source_refs=pred.source_refs + succ.source_refs,
            ))
            alternative_id = (
                stable_id("candidate", alternative.predecessor.node_id,
                          alternative.successor.node_id)
                if alternative else None
            )
            output.append(CandidateInterpretation(
                interpretation_id=interpretation_id,
                predecessor_node_id=key[0],
                successor_node_id=key[1],
                evidence_bundle_id=bundle_id,
                gates=candidate.gates,
                admissible=True,
                exclusion_reason=None,
                tier=tier,
                strongest_alternative_id=alternative_id,
                alternative_comparison=(
                    f"Strongest alternative is {alternative.predecessor.task_code}; "
                    f"margin is {margin}." if alternative else
                    "No other admissible candidate in the blocked population."
                ),
                uniqueness_margin=margin,
                hypotheses=hypotheses,
                caps_applied=tuple(caps),
                contest_flag=contest,
                review_priority=(ReviewPriority.CRITICAL if contest
                                 else ReviewPriority.MEDIUM),
                discriminating_question=(
                    f"Could {succ.task_code} physically proceed before "
                    f"{pred.task_code} reached the recorded condition?"
                ),
            ))
    return output


def _provisional_gaps(
    snapshot: ProgrammeSnapshot, config: RLPAConfig
) -> list[_Gap]:
    workfronts: dict[str, list[ActivityNode]] = defaultdict(list)
    for node in snapshot.activity_nodes.values():
        if node.actual_start and node.actual_finish \
                and node.task_type not in {"TT_LOE", "TT_WBS"}:
            workfronts[node.workfront].append(node)
    gaps: list[_Gap] = []
    for nodes in workfronts.values():
        nodes.sort(key=lambda n: (n.actual_start, n.actual_finish))
        # A workfront is interrupted only when NO activity is in progress:
        # merge the actual intervals and report the holes. Pairing
        # consecutive starts instead would invent gaps behind overlapping
        # chains and miss the true idle periods.
        frontier: ActivityNode | None = None
        for node in nodes:
            if node.actual_start is None or node.actual_finish is None:
                continue
            if frontier is None:
                frontier = node
                continue
            frontier_finish = frontier.actual_finish
            assert frontier_finish is not None
            if node.actual_start > frontier_finish:
                days = _working_days(
                    snapshot, frontier_finish, node.actual_start, node
                )
                if days >= config.provisional_gap_min_working_days:
                    gaps.append(_Gap(
                        frontier, node, frontier_finish,
                        node.actual_start, days,
                    ))
            if node.actual_finish > frontier_finish:
                frontier = node
    return gaps


def _completion_correspondence(
    snapshots: tuple[ProgrammeSnapshot, ...],
    gap: _Gap,
    genealogy: GenealogySummary,
) -> tuple[EvidenceState, str]:
    """N6: does completion movement in the update period covering the gap
    match the interruption duration? Working days, R9/§9.3.4 respected."""
    if len(snapshots) < 2:
        return (EvidenceState.NOT_APPLICABLE,
                "Completion correspondence requires a comparable update pair")
    for index, (old, new) in enumerate(
        zip(snapshots, snapshots[1:], strict=False)
    ):
        old_date, new_date = old.record.data_date, new.record.data_date
        if old_date is None or new_date is None:
            continue
        if not (old_date <= gap.end and new_date >= gap.start):
            continue
        if old.scheduling_options != new.scheduling_options:
            return (EvidenceState.NOT_APPLICABLE,
                    "Covering update pair spans a scheduling-option change; "
                    "movement comparison suppressed")
        blocked = (genealogy.pair_non_comparable[index]
                   if index < len(genealogy.pair_non_comparable)
                   else frozenset())
        old_by_code = {n.task_code: n for n in old.activity_nodes.values()}
        new_by_code = {n.task_code: n for n in new.activity_nodes.values()}
        for milestone in _anchor_candidates(new) or list(
            new.milestone_nodes.values()
        ):
            code = milestone.task_code
            if code in blocked:
                continue
            old_node = old_by_code.get(code)
            new_node = new_by_code.get(code)
            if old_node is None or new_node is None:
                continue
            old_finish = (old_node.actual_finish or old_node.planned_finish
                          or old_node.actual_start)
            new_finish = (new_node.actual_finish or new_node.planned_finish
                          or new_node.actual_start)
            if old_finish is None or new_finish is None:
                continue
            if new_finish >= old_finish:
                movement = _working_days(new, old_finish, new_finish, new_node)
            else:
                movement = -_working_days(new, new_finish, old_finish, new_node)
            observation = (
                f"Milestone {code} moved {movement:.1f} working day(s) "
                f"across updates {old_date.date()}→{new_date.date()}; "
                f"interruption is {gap.working_days:.1f} working day(s)"
            )
            if abs(movement - gap.working_days) <= max(
                2.0, 0.25 * gap.working_days
            ):
                return (EvidenceState.PRESENT,
                        observation + " — correspondence present, "
                        "not exclusive")
            if movement > 0.01:
                return (EvidenceState.PARTIAL,
                        observation + " — movement present but does not "
                        "match the interruption duration")
            return (EvidenceState.ABSENT,
                    observation + " — no completion movement in the period")
    return (EvidenceState.NOT_APPLICABLE,
            "No update pair with data dates covering the interruption period")


def _interruption_analysis(
    snapshot: ProgrammeSnapshot,
    snapshots: tuple[ProgrammeSnapshot, ...],
    gaps: list[_Gap],
    interpretations: list[CandidateInterpretation],
    graph: EvidenceGraph,
    genealogy: GenealogySummary,
    fitness: FitnessReport,
    config: RLPAConfig,
) -> list[InterruptionInterpretation]:
    by_successor: dict[str, list[CandidateInterpretation]] = defaultdict(list)
    for item in interpretations:
        by_successor[item.successor_node_id].append(item)
    all_nodes = list(snapshot.activity_nodes.values())
    output: list[InterruptionInterpretation] = []
    for gap in gaps:
        if gap.working_days < config.interruption_report_min_working_days:
            continue
        population = by_successor.get(gap.successor.node_id, [])
        strong = [item for item in population
                  if item.admissible and item.tier in {Tier.A, Tier.B}]
        constraint = bool(gap.successor.constraint_type)
        party = _class_value(gap.successor, "responsible_party")
        resource_elsewhere = False
        if party:
            resource_elsewhere = any(
                node.node_id not in {gap.predecessor.node_id,
                                     gap.successor.node_id}
                and _class_value(node, "responsible_party") == party
                and node.actual_start and node.actual_finish
                and node.actual_start < gap.end
                and node.actual_finish > gap.start
                for node in all_nodes
            )
        f3_ok = fitness.gate("F3").status is GateStatus.PASS
        same_workfront = [n for n in all_nodes
                          if n.workfront == gap.successor.workfront]
        classified = sum(
            1 for n in same_workfront
            if _classification_usable(n, "location")
            and _classification_usable(n, "discipline")
        )
        coverage = classified / len(same_workfront) if same_workfront else 0.0
        exhaustive = f3_ok and coverage >= config.classification_yield_min
        comparable_gaps = sum(
            1 for other in gaps
            if other is not gap
            and _work_type(other.predecessor) == _work_type(gap.predecessor)
            and _work_type(other.successor) == _work_type(gap.successor)
            and abs(other.working_days - gap.working_days) <= 1.0
        )
        exclusions = tuple(
            f"{item.interpretation_id}: "
            + (item.exclusion_reason or f"retained at {item.tier.value}")
            for item in population if item not in strong
        )
        n6_state, n6_observation = _completion_correspondence(
            snapshots, gap, genealogy
        )
        negative_id = stable_id(
            "negative", gap.predecessor.node_id, gap.successor.node_id,
            gap.start.isoformat(), gap.end.isoformat(),
        )
        negative = NegativeEvidenceBundle(
            bundle_id=negative_id,
            factors=(
                EvidenceFactor(
                    "N1",
                    EvidenceState.PRESENT if exhaustive
                    else EvidenceState.PARTIAL,
                    f"{len(population)} blocked candidate(s) tested; "
                    f"{len(strong)} Tier A/B explanation(s)",
                ),
                EvidenceFactor(
                    "N2", EvidenceState.PRESENT,
                    f"{gap.working_days:.2f} working days on successor calendar",
                ),
                EvidenceFactor(
                    "N3", EvidenceState.ABSENT if constraint
                    else EvidenceState.PRESENT,
                    "Bounding successor has a constraint" if constraint
                    else "No governing constraint recorded",
                ),
                EvidenceFactor(
                    "N4", EvidenceState.ABSENT if resource_elsewhere
                    else EvidenceState.PRESENT,
                    "Responsible party engaged elsewhere in programme"
                    if resource_elsewhere else
                    "No programme-visible engagement elsewhere",
                ),
                EvidenceFactor(
                    "N5", EvidenceState.PRESENT if comparable_gaps == 0
                    else EvidenceState.PARTIAL,
                    f"{comparable_gaps} equivalent gap(s) in other workfronts",
                ),
                EvidenceFactor("N6", n6_state, n6_observation),
                EvidenceFactor(
                    "N7", EvidenceState.PRESENT if exhaustive
                    else EvidenceState.PARTIAL,
                    f"Workfront classification coverage {coverage:.1%}; "
                    f"F3 {fitness.gate('F3').status.value}",
                ),
            ),
        )
        graph.add_negative_bundle(negative)
        node_id = stable_id(
            "interruption", gap.predecessor.node_id,
            gap.successor.node_id, gap.start.isoformat(), gap.end.isoformat()
        )
        interruption = InterruptionNode(
            node_id=node_id,
            snapshot_id=snapshot.record.snapshot_id,
            workfront=gap.successor.workfront,
            period_start=gap.start,
            period_end=gap.end,
            working_days=gap.working_days,
            calendar_id=gap.successor.calendar_id,
            bounding_predecessor_node_id=gap.predecessor.node_id,
            bounding_successor_node_id=gap.successor.node_id,
            candidate_population=tuple(
                item.interpretation_id for item in population
            ),
            exclusion_set=exclusions,
            negative_evidence_bundle_id=negative_id,
            source_refs=(gap.predecessor.source_refs
                         + gap.successor.source_refs),
        )
        graph.add_node(interruption)
        graph.add_edge(BoundingEdge(
            stable_id("bound", gap.predecessor.node_id, node_id),
            gap.predecessor.node_id, node_id, "before",
        ))
        graph.add_edge(BoundingEdge(
            stable_id("bound", node_id, gap.successor.node_id),
            node_id, gap.successor.node_id, "after",
        ))
        if strong:
            classification = InterruptionClass.EXPLAINED_PREDECESSOR
            tier = max((item.tier for item in strong), key=lambda t: t.rank)
        elif constraint:
            classification = InterruptionClass.EXPLAINED_CONSTRAINT
            tier = Tier.B
        elif resource_elsewhere:
            classification = InterruptionClass.EXPLAINED_RESOURCE
            tier = Tier.C
        elif exhaustive:
            classification = InterruptionClass.UNEXPLAINED
            tier = Tier.C
        else:
            classification = InterruptionClass.UNEXPLAINED_WITHIN_COVERAGE
            tier = Tier.C
        unexplained = classification in {
            InterruptionClass.UNEXPLAINED,
            InterruptionClass.UNEXPLAINED_WITHIN_COVERAGE,
        }
        result = InterruptionInterpretation(
            interpretation_id=stable_id("interrupt_i", node_id),
            interruption_node_id=node_id,
            classification=classification,
            tier=tier,
            review_priority=(ReviewPriority.CRITICAL if unexplained
                             else ReviewPriority.HIGH),
            completion_correspondence=n6_observation,
            coverage_qualification=(
                "exhaustiveness supported" if exhaustive
                else "unexplained only within available classified coverage"
            ),
            discriminating_question=(
                f"What prevented {gap.successor.task_code} from commencing "
                f"during {gap.start.date()}–{gap.end.date()}?"
            ),
        )
        graph.add_interruption_interpretation(result)
        output.append(result)
    # §13.4 ranking: unexplained first, then duration, then N6
    # correspondence (already summarised in the interpretation text).
    durations = {
        item.interpretation_id: gap.working_days
        for item, gap in zip(output, [
            g for g in gaps
            if g.working_days >= config.interruption_report_min_working_days
        ], strict=False)
    }
    output.sort(key=lambda item: (
        item.classification not in {
            InterruptionClass.UNEXPLAINED,
            InterruptionClass.UNEXPLAINED_WITHIN_COVERAGE,
        },
        -durations.get(item.interpretation_id, 0.0),
    ))
    return output


def _choose_anchor(
    snapshot: ProgrammeSnapshot, anchor_task_code: str | None
):
    candidates = _anchor_candidates(snapshot)
    if anchor_task_code:
        for milestone in candidates:
            if milestone.task_code == anchor_task_code:
                return milestone
        return None
    return candidates[0] if candidates else None


def _derive_path(
    snapshot: ProgrammeSnapshot,
    graph: EvidenceGraph,
    interpretations: list[CandidateInterpretation],
    interruptions: list[InterruptionInterpretation],
    anchor_task_code: str | None,
    rejected_element_ids: set[str],
) -> PathInterpretation | None:
    anchor = _choose_anchor(snapshot, anchor_task_code)
    if anchor is None:
        return None
    activity = snapshot.activity_nodes.get(anchor.task_id)
    if activity is None:
        return None
    incoming: dict[str, list[CandidateInterpretation]] = defaultdict(list)
    for item in interpretations:
        if item.admissible and item.tier is not Tier.D \
                and item.interpretation_id not in rejected_element_ids \
                and item.predecessor_node_id not in rejected_element_ids:
            incoming[item.successor_node_id].append(item)
    interruption_by_successor: dict[str, list[tuple[
        InterruptionNode, InterruptionInterpretation
    ]]] = defaultdict(list)
    for interruption_item in interruptions:
        interruption_node = graph.nodes[
            interruption_item.interruption_node_id
        ]
        assert isinstance(interruption_node, InterruptionNode)
        if interruption_item.interpretation_id in rejected_element_ids \
                or interruption_node.node_id in rejected_element_ids:
            continue
        if interruption_item.classification in {
            InterruptionClass.UNEXPLAINED,
            InterruptionClass.UNEXPLAINED_WITHIN_COVERAGE,
        }:
            interruption_by_successor[
                interruption_node.bounding_successor_node_id
            ].append((interruption_node, interruption_item))

    backward: list[tuple[str, NodeKind, Tier, str, str | None]] = [
        (anchor.node_id, NodeKind.MILESTONE, Tier.B,
         "actual-dated programme milestone selected as anchor", None)
    ]
    alternatives: list[tuple[str, ...]] = []
    warnings: list[str] = []
    current = activity.node_id
    visited = {current}
    while True:
        options = incoming.get(current, [])
        strong = [item for item in options if item.tier in {Tier.A, Tier.B}]
        gaps = interruption_by_successor.get(current, [])
        if gaps and not strong:
            node, gap_i = max(gaps, key=lambda pair: pair[0].working_days)
            backward.append((
                node.node_id, NodeKind.INTERRUPTION, gap_i.tier,
                f"{node.working_days:.2f} working-day "
                f"{gap_i.classification.value}", None,
            ))
            current = node.bounding_predecessor_node_id
            if current in visited:
                warnings.append("Backward trace encountered a cycle")
                break
            visited.add(current)
            continue
        eligible = sorted(options, key=lambda item: item.tier.rank,
                          reverse=True)
        if not eligible:
            warnings.append(
                "Trace terminated at indeterminacy: no Tier C or better "
                "incoming candidate and no reportable interruption."
            )
            break
        best_tier = eligible[0].tier
        best = [item for item in eligible if item.tier is best_tier]
        selected = best[0]
        if len(best) > 1:
            alternatives.append(tuple(
                item.predecessor_node_id for item in best[1:]
            ))
            warnings.append(
                "Equal-tier branch retained; branch output is not a "
                "concurrency assessment."
            )
        pred_node = graph.nodes[selected.predecessor_node_id]
        assert isinstance(pred_node, ActivityNode)
        backward.append((
            pred_node.node_id, NodeKind.ACTIVITY, selected.tier,
            f"selected by {selected.interpretation_id}; "
            f"alternative margin {selected.uniqueness_margin}",
            "; ".join(selected.caps_applied) or None,
        ))
        current = pred_node.node_id
        if current in visited:
            warnings.append("Backward trace encountered a cycle")
            break
        visited.add(current)
        if not incoming.get(current) and not interruption_by_successor.get(current):
            break
    ordered = list(reversed(backward))
    elements = tuple(PathElement(
        order=index,
        node_id=node_id,
        element_type=kind,
        tier=tier,
        basis=basis,
        governing_cap=cap,
    ) for index, (node_id, kind, tier, basis, cap)
      in enumerate(ordered, 1))
    weakest = min((e.tier for e in elements), key=lambda tier: tier.rank)
    query = (
        "Backward from actual-dated anchor; admit Activity and unexplained "
        "Interruption nodes; choose highest tier; retain equal-tier branches; "
        "apply Layer 3 rejections; terminate at commencement/indeterminacy."
    )
    path_id = stable_id(
        "path", graph.version, anchor.node_id, query,
        ",".join(e.node_id for e in elements),
    )
    return PathInterpretation(
        path_id=path_id,
        graph_version=graph.version,
        anchor_node_id=anchor.node_id,
        query_definition=query,
        elements=elements,
        alternative_paths=tuple(alternatives),
        weakest_tier=weakest,
        contested_count=sum(1 for e in elements if e.tier in {Tier.C, Tier.D}),
        warnings=tuple(warnings),
    )


def _planned_path(snapshot: ProgrammeSnapshot) -> tuple[str, ...]:
    nodes = [n for n in snapshot.activity_nodes.values()
             if n.longest_path_flag or n.critical_flag
             or (n.total_float_days is not None and n.total_float_days <= 0)]
    nodes.sort(key=lambda n: (
        n.planned_start or datetime.max,
        n.planned_finish or datetime.max,
    ))
    return tuple(n.task_code for n in nodes)


def _relationship_set(snapshot: ProgrammeSnapshot) -> set[tuple[str, str, str]]:
    by_task = snapshot.activity_nodes
    return {
        (by_task[r.pred_task_id].task_code,
         by_task[r.task_id].task_code, r.pred_type)
        for r in snapshot.source_data.relationships
        if r.pred_task_id in by_task and r.task_id in by_task
    }


def _anchor_date(snapshot: ProgrammeSnapshot, code: str) -> datetime | None:
    for node in snapshot.activity_nodes.values():
        if node.task_code == code:
            return node.actual_finish or node.planned_finish \
                or node.actual_start or node.planned_start
    return None


def _windows_and_migrations(
    snapshots: tuple[ProgrammeSnapshot, ...],
    path: PathInterpretation | None,
    graph: EvidenceGraph,
    fitness: FitnessReport,
) -> tuple[list[WindowComparison], list[MigrationRecord]]:
    if (len(snapshots) < 2 or path is None
            or 7 not in fitness.allowed_steps or 8 not in fitness.allowed_steps
            or fitness.gate("F4").status is not GateStatus.PASS):
        return [], []
    planned = _planned_path(snapshots[0])
    path_codes: list[str] = []
    # Dated path elements — activities AND interruptions — so each window
    # can show the controlling chain WITHIN it (§15.3), not the whole path.
    dated_elements: list[tuple[str, datetime, datetime]] = []
    if path:
        for element in path.elements:
            node = graph.nodes[element.node_id]
            if isinstance(node, ActivityNode):
                path_codes.append(node.task_code)
                if node.actual_start and node.actual_finish:
                    dated_elements.append((
                        node.task_code, node.actual_start, node.actual_finish
                    ))
            elif isinstance(node, InterruptionNode):
                dated_elements.append((
                    f"[interruption {node.working_days:.0f}wd "
                    f"{node.workfront}]",
                    node.period_start, node.period_end,
                ))
    anchor_code = ""
    if path:
        anchor_node = graph.nodes[path.anchor_node_id]
        anchor_code = getattr(anchor_node, "task_code", "")
    windows: list[WindowComparison] = []
    migrations: list[MigrationRecord] = []
    previous_workfront = ""
    for index, (old, new) in enumerate(
        zip(snapshots, snapshots[1:], strict=False), 1
    ):
        options_changed = old.scheduling_options != new.scheduling_options
        old_codes = {n.task_code for n in old.activity_nodes.values()}
        new_codes = {n.task_code for n in new.activity_nodes.values()}
        scope_changed = old_codes != new_codes
        logic_changed = _relationship_set(old) != _relationship_set(new)
        if options_changed:
            divergence = DivergenceClass.ARTEFACT
        elif scope_changed:
            divergence = DivergenceClass.SCOPE
        elif logic_changed:
            divergence = DivergenceClass.LOGIC
        else:
            divergence = DivergenceClass.EXECUTION
        old_finish = _anchor_date(old, anchor_code) if anchor_code else None
        new_finish = _anchor_date(new, anchor_code) if anchor_code else None
        movement = None
        if old_finish and new_finish and not options_changed:
            movement = (new_finish - old_finish).total_seconds() / 86400.0
        start = old.record.data_date
        end = new.record.data_date
        active_workfronts: list[str] = []
        if start and end:
            for node in new.activity_nodes.values():
                if node.task_code not in path_codes or not node.actual_start:
                    continue
                finish = node.actual_finish or node.actual_start
                if node.actual_start <= end and finish >= start:
                    active_workfronts.append(node.workfront)
        workfront = (Counter(active_workfronts).most_common(1)[0][0]
                     if active_workfronts else "indeterminate")
        window_id = f"W{index:02d}"
        if start and end:
            window_path = tuple(
                label for label, el_start, el_finish in dated_elements
                if el_start <= end and el_finish >= start
            )
        else:
            window_path = tuple(path_codes)
        windows.append(WindowComparison(
            window_id=window_id,
            start=start,
            end=end,
            start_snapshot_id=old.record.snapshot_id,
            end_snapshot_id=new.record.snapshot_id,
            planned_path=planned,
            probable_as_built_path=window_path,
            completion_movement_working_days=movement,
            displaced_from_planned=tuple(sorted(set(planned) - set(path_codes))),
            entered_as_built=tuple(sorted(set(path_codes) - set(planned))),
            divergence=divergence,
            date_movement_suppressed=options_changed,
            suppression_reason=(
                "SCHEDOPTIONS changed across boundary" if options_changed
                else None
            ),
            tier=Tier.D if options_changed else Tier.C,
        ))
        if previous_workfront and workfront != previous_workfront:
            migrations.append(MigrationRecord(
                window_id=window_id,
                previous_controlling_path=previous_workfront,
                new_controlling_path=workfront,
                migration_point=(end.isoformat() if end else window_id),
                tier=Tier.C,
                explanation="Dominant classified workfront on derived chain changed",
                artefact_or_execution=(
                    "artefact" if divergence is DivergenceClass.ARTEFACT
                    else "execution"
                ),
            ))
        previous_workfront = workfront
    return windows, migrations


def _default_model_audit(activity_count: int) -> ModelAccessAudit:
    return ModelAccessAudit(
        operating_mode=OperatingMode.DETERMINISTIC,
        key_source="none",
        key_fingerprint="not_applicable",
        endpoint="none",
        egress_occurred=False,
        transmitted_fields=(),
        model_identifier="none",
        model_version="none",
        prompt_version="none",
        temperature=None,
        seed=None,
        deterministic_count=activity_count,
        model_assisted_count=0,
        degraded_count=0,
    )


def analyse(
    snapshots: Iterable[ProgrammeSnapshot],
    *,
    anchor_task_code: str | None = None,
    config: RLPAConfig | None = None,
    rejected_element_ids: Iterable[str] = (),
    model_access: ModelAccessAudit | None = None,
) -> PipelineResult:
    """Run Steps 1-9 without mutating any source programme or toolkit file."""
    config = config or RLPAConfig()
    ordered = tuple(sorted(
        snapshots,
        key=lambda item: item.record.data_date or datetime.min,
    ))
    if not ordered:
        raise ValueError("At least one programme snapshot is required")
    graph = EvidenceGraph()
    for snapshot in ordered:
        for activity_node in snapshot.activity_nodes.values():
            graph.add_node(activity_node)
        for milestone_node in snapshot.milestone_nodes.values():
            graph.add_node(milestone_node)
    genealogy = build_genealogy(ordered, graph)
    fitness = _fitness(ordered, genealogy, config)
    final = ordered[-1]
    candidates: list[_Candidate] = []
    interpretations: list[CandidateInterpretation] = []
    gaps: list[_Gap] = []
    interruptions: list[InterruptionInterpretation] = []
    if 3 in fitness.allowed_steps:
        candidates = _candidate_population(final, config)
    if 4 in fitness.allowed_steps:
        interpretations = _interpret_candidates(
            final, ordered, candidates, graph, genealogy, config
        )
        for item in interpretations:
            graph.add_interpretation(item)
    else:
        # Preserve binary gate/exclusion results even when F2 blocks driving.
        for candidate in candidates:
            item = CandidateInterpretation(
                interpretation_id=stable_id(
                    "candidate", candidate.predecessor.node_id,
                    candidate.successor.node_id,
                ),
                predecessor_node_id=candidate.predecessor.node_id,
                successor_node_id=candidate.successor.node_id,
                evidence_bundle_id=None,
                gates=candidate.gates,
                admissible=candidate.admissible,
                exclusion_reason=(candidate.exclusion_reason or
                                  "F2 density gate blocked driving assessment"),
                tier=Tier.D,
                strongest_alternative_id=None,
                alternative_comparison="Driving interpretation suppressed by F2",
                uniqueness_margin="not tested",
                hypotheses=(), caps_applied=("F2 density cap",),
                contest_flag=True,
                review_priority=ReviewPriority.HIGH,
                discriminating_question="Increase programme detail before inference",
            )
            interpretations.append(item)
            graph.add_interpretation(item)
    if 5 in fitness.allowed_steps:
        gaps = _provisional_gaps(final, config)
        interruptions = _interruption_analysis(
            final, ordered, gaps, interpretations, graph, genealogy,
            fitness, config
        )
    graph.seal()
    path = None
    if 6 in fitness.allowed_steps:
        path = _derive_path(
            final, graph, interpretations, interruptions,
            anchor_task_code, set(rejected_element_ids),
        )
    windows, migrations = _windows_and_migrations(
        ordered, path, graph, fitness
    )
    warnings = [warning for record in ordered
                for warning in record.record.warnings]
    if fitness.gate("F4").status is not GateStatus.PASS:
        warnings.append(
            "APvAB windows and critical-path migration were suppressed: "
            + fitness.gate("F4").measured
        )
    if windows:
        warnings.append(
            "The as-planned critical path is a calculated path in an "
            "unexecuted network; it carries the reliability of the "
            "baseline logic and no more."
        )
    if path:
        warnings.extend(path.warnings)
    model_access = model_access or _default_model_audit(
        len(final.activity_nodes)
    )
    run_seed = {
        "ruleset": RULESET_VERSION,
        "graph": graph.version,
        "anchor": path.anchor_node_id if path else None,
        "rejections": sorted(rejected_element_ids),
    }
    run_id = "run_" + hashlib.sha256(json.dumps(
        run_seed, sort_keys=True
    ).encode("utf-8")).hexdigest()[:20]
    run = AnalysisRun(
        run_id=run_id,
        ruleset_version=RULESET_VERSION,
        specification_version=SPECIFICATION_VERSION,
        created_utc=datetime.now(timezone.utc),
        ingestion=tuple(snapshot.record for snapshot in ordered),
        fitness=fitness,
        model_access=model_access,
        graph_version=graph.version,
        anchor_node_id=path.anchor_node_id if path else None,
        path=path,
        windows=tuple(windows),
        migrations=tuple(migrations),
        warnings=tuple(warnings),
        calibration_statement=UNCALIBRATED_STATEMENT,
    )
    review_items: list[dict] = []
    for candidate_item in interpretations:
        if candidate_item.review_priority in {
            ReviewPriority.CRITICAL, ReviewPriority.HIGH
        }:
            review_items.append({
                "priority": candidate_item.review_priority.value,
                "element": candidate_item.interpretation_id,
                "question": candidate_item.discriminating_question,
                "engine_reading": candidate_item.tier.value,
                "records_to_obtain": "factual workfront and technical records",
            })
    for interruption_item in interruptions:
        if interruption_item.review_priority is ReviewPriority.CRITICAL:
            review_items.append({
                "priority": interruption_item.review_priority.value,
                "element": interruption_item.interruption_node_id,
                "question": interruption_item.discriminating_question,
                "engine_reading": interruption_item.classification.value,
                "records_to_obtain": "access, RFI, inspection and daily records",
            })
    return PipelineResult(
        run=run,
        graph=graph,
        snapshots=ordered,
        candidate_interpretations=tuple(interpretations),
        interruption_interpretations=tuple(interruptions),
        provisional_gap_count=len(gaps),
        review_items=tuple(review_items),
    )


def rerun_with_rejections(
    result: PipelineResult, rejected_element_ids: Iterable[str]
) -> PipelineResult:
    """Rebuild Layer 2/path from immutable inputs; Layer 1 source is unchanged."""
    return analyse(
        result.snapshots,
        anchor_task_code=(
            getattr(result.graph.nodes[result.run.anchor_node_id],
                    "task_code", None)
            if result.run.anchor_node_id else None
        ),
        rejected_element_ids=rejected_element_ids,
        model_access=result.run.model_access,
    )
