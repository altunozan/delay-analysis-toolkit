"""Narrow adapter over the toolkit's existing XER/model/calendar services."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from dcma.calendar import calendar_masks, working_days_between
from dcma.config import DCMAConfig
from dcma.models import STATUS_COMPLETE
from dcma.xer_parser import XerData, parse_xer
from programme.basis import sched_options_row

from .config import RLPAConfig
from .domain import (
    ActivityNode,
    Classification,
    ClassificationConfidence,
    Comparability,
    GenealogyEdge,
    IngestionRecord,
    MilestoneNode,
    ProgrammeSnapshot,
    ResolutionStatus,
    SourceRef,
)
from .graph import EvidenceGraph


def stable_id(prefix: str, *parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(raw).hexdigest()[:20]}"


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _wbs_paths(data: XerData) -> dict[str, str]:
    rows = data.raw_tables.get("PROJWBS", [])
    nodes = {
        _clean(row.get("wbs_id")): (
            _clean(row.get("wbs_name") or row.get("wbs_short_name")),
            _clean(row.get("parent_wbs_id")),
        )
        for row in rows if _clean(row.get("wbs_id"))
    }
    cache: dict[str, str] = {}

    def path_for(wbs_id: str) -> str:
        if wbs_id in cache:
            return cache[wbs_id]
        names: list[str] = []
        seen: set[str] = set()
        current = wbs_id
        while current in nodes and current not in seen:
            seen.add(current)
            name, parent = nodes[current]
            if name:
                names.append(name)
            current = parent
        result = " / ".join(reversed(names))
        cache[wbs_id] = result
        return result

    return {
        _clean(row.get("task_id")): path_for(_clean(row.get("wbs_id")))
        for row in data.raw_tables.get("TASK", [])
        if _clean(row.get("task_id"))
    }


def _activity_codes(data: XerData) -> dict[str, dict[str, str]]:
    type_names = {
        _clean(row.get("actv_code_type_id")): _clean(
            row.get("actv_code_type") or row.get("actv_code_type_name")
        )
        for row in data.raw_tables.get("ACTVTYPE", [])
    }
    code_values: dict[str, tuple[str, str]] = {}
    for row in data.raw_tables.get("ACTVCODE", []):
        code_id = _clean(row.get("actv_code_id"))
        type_id = _clean(row.get("actv_code_type_id"))
        value = _clean(
            row.get("actv_code_name") or row.get("short_name") or code_id
        )
        if code_id:
            code_values[code_id] = (type_names.get(type_id, type_id), value)
    result: dict[str, dict[str, str]] = {}
    for row in data.raw_tables.get("TASKACTV", []):
        task_id = _clean(row.get("task_id"))
        code_id = _clean(row.get("actv_code_id"))
        if task_id and code_id in code_values:
            type_name, value = code_values[code_id]
            result.setdefault(task_id, {})[type_name] = value
    return result


_CATEGORY_TOKENS = {
    "location": (
        "location", "area", "building", "structure", "floor", "level",
        "zone", "chainage", "room",
    ),
    "discipline": ("discipline", "trade"),
    "system": ("system", "subsystem"),
    "package": ("package", "work package", "scope"),
    "responsible_party": (
        "responsible", "contractor", "subcontractor", "company", "party",
    ),
    "phase": ("phase", "stage"),
}

_DISCIPLINES = (
    "civil", "structural", "architectural", "electrical", "mechanical",
    "plumbing", "mep", "hvac", "fire", "instrumentation", "commissioning",
)
_SYSTEMS = (
    "chilled water", "power", "lighting", "fire alarm", "drainage",
    "waterproofing", "facade", "façade", "bms", "ict", "security",
)


def _explicit_category(
    codes: dict[str, str], category: str
) -> tuple[str, str] | None:
    tokens = _CATEGORY_TOKENS[category]
    for type_name, value in codes.items():
        normalised_type = _normalise(type_name)
        if any(token in normalised_type for token in tokens):
            return value, type_name
    return None


def _derived_classification(
    category: str, name: str, wbs_path: str
) -> tuple[str | None, str]:
    source = f"{wbs_path} {name}".strip()
    lowered = source.lower()
    if category == "location":
        match = re.search(
            r"\b(?:zone|area|level|floor|building|room)\s*[-:]?\s*"
            r"([a-z0-9]+(?:[- ][a-z0-9]+)?)\b", lowered,
        )
        if match:
            label = source[match.start():match.end()]
            return _clean(label), "location token in WBS/name"
    if category == "discipline":
        for token in _DISCIPLINES:
            if token in lowered:
                return token.title(), "discipline token in WBS/name"
    if category == "system":
        for token in _SYSTEMS:
            if token in lowered:
                return token.title(), "system token in WBS/name"
    if category == "package" and wbs_path:
        return wbs_path.split(" / ")[-1], "deepest WBS node"
    return None, "no deterministic structured or naming evidence"


def _classifications(
    name: str, wbs_path: str, codes: dict[str, str]
) -> tuple[Classification, ...]:
    output: list[Classification] = []
    for category in _CATEGORY_TOKENS:
        explicit = _explicit_category(codes, category)
        if explicit:
            value, type_name = explicit
            output.append(Classification(
                category, value, ClassificationConfidence.EXPLICIT,
                "activity_code", f"Activity code type '{type_name}'",
            ))
            continue
        derived_value, reason = _derived_classification(
            category, name, wbs_path
        )
        output.append(Classification(
            category, derived_value,
            ClassificationConfidence.DERIVED if derived_value
            else ClassificationConfidence.AMBIGUOUS,
            "wbs_and_name" if derived_value else "none", reason,
        ))

    lowered = name.lower()
    work_type = "general"
    for token, label in (
        ("procure", "procurement"), ("deliver", "delivery"),
        ("install", "installation"), ("erect", "installation"),
        ("construct", "construction"), ("inspect", "inspection"),
        ("test", "testing"), ("energ", "energisation"),
        ("commission", "commissioning"), ("handover", "handover"),
        ("completion", "completion"),
    ):
        if token in lowered:
            work_type = label
            break
    output.append(Classification(
        "work_type", work_type,
        ClassificationConfidence.DERIVED,
        "activity_name", "deterministic work-type token",
    ))
    return tuple(output)


def _assessed_type(data: XerData) -> str:
    eligible = [t for t in data.tasks if not t.is_loe_or_wbs]
    if eligible and all(t.status == STATUS_COMPLETE for t in eligible):
        return "as-built"
    if eligible and not any(t.act_start or t.act_finish for t in eligible):
        return "baseline"
    return "update"


def _source_tool(data: XerData) -> str:
    header = " | ".join(data.header)
    return header or "Primavera P6 XER (version not recorded)"


def _source_encoding(data: XerData) -> str | None:
    """This toolkit's parser records the decode path in parse_notes."""
    for note in data.parse_notes:
        lowered = note.lower()
        for token in ("utf-8-sig", "utf-16", "utf-8", "cp1252", "latin-1"):
            if token in lowered:
                return token
    return None


def load_xer_snapshot(
    path: str | Path,
    *,
    declared_programme_type: str = "unspecified",
    config: DCMAConfig | None = None,
    rlpa_config: RLPAConfig | None = None,
) -> ProgrammeSnapshot:
    """Parse with the existing parser and normalise without mutating it."""
    source_path = Path(path)
    content = source_path.read_bytes()
    data = parse_xer(content, config=config)
    return snapshot_from_xer_data(
        data,
        filename=source_path.name,
        content=content,
        declared_programme_type=declared_programme_type,
        config=config,
        rlpa_config=rlpa_config,
    )


def snapshot_from_xer_data(
    data: XerData,
    *,
    filename: str,
    content: bytes,
    declared_programme_type: str = "unspecified",
    config: DCMAConfig | None = None,
    rlpa_config: RLPAConfig | None = None,
) -> ProgrammeSnapshot:
    config = config or DCMAConfig()
    anchor_tokens = (rlpa_config or RLPAConfig()).anchor_name_tokens
    digest = hashlib.sha256(content).hexdigest()
    project = data.project
    snapshot_id = stable_id(
        "snapshot", digest, project.proj_id if project else ""
    )
    record = IngestionRecord(
        snapshot_id=snapshot_id,
        filename=filename,
        sha256=digest,
        size_bytes=len(content),
        source_format="Primavera P6 XER",
        source_tool=_source_tool(data),
        project_id=project.proj_id if project else "",
        project_name=project.short_name if project else "",
        data_date=project.data_date if project else None,
        declared_programme_type=declared_programme_type,
        assessed_programme_type=_assessed_type(data),
        source_encoding=_source_encoding(data),
        warnings=tuple(data.parse_notes),
    )
    snapshot = ProgrammeSnapshot(
        record=record,
        source_data=data,
        scheduling_options=sched_options_row(data),
    )
    wbs_paths = _wbs_paths(data)
    code_map = _activity_codes(data)
    masks = calendar_masks(data)
    task_rows = {
        _clean(row.get("task_id")): (index, row)
        for index, row in enumerate(data.raw_tables.get("TASK", []), 1)
    }
    predecessors: dict[str, list[str]] = {}
    successors: dict[str, list[str]] = {}
    for rel in data.relationships:
        predecessors.setdefault(rel.task_id, []).append(rel.pred_task_id)
        successors.setdefault(rel.pred_task_id, []).append(rel.task_id)

    for task in data.tasks:
        row_number, raw = task_rows.get(task.task_id, (0, {}))
        hpd = data.hours_per_day(task, config)
        mask = masks.get(task.clndr_id)
        actual_duration = None
        if task.act_start and task.act_finish:
            actual_duration = working_days_between(
                task.act_start, task.act_finish, mask
            )
        wbs_path = wbs_paths.get(task.task_id, "")
        classes = _classifications(
            task.name, wbs_path, code_map.get(task.task_id, {})
        )
        fingerprint = hashlib.sha256(
            "|".join((
                task.task_id, _normalise(task.name), wbs_path,
                ",".join(sorted(code_map.get(task.task_id, {}).values())),
                str(task.target_drtn_hr), task.clndr_id,
                ",".join(sorted(predecessors.get(task.task_id, []))),
                ",".join(sorted(successors.get(task.task_id, []))),
            )).encode("utf-8")
        ).hexdigest()
        refs = tuple(SourceRef(
            digest, "TASK", row_number, field_name,
            _clean(raw.get(field_name)),
        ) for field_name in (
            "task_id", "task_code", "task_name", "act_start_date",
            "act_end_date", "target_start_date", "target_end_date",
            "clndr_id", "cstr_type", "cstr_date",
        ) if raw.get(field_name))
        node_id = stable_id("activity", snapshot_id, task.task_id)
        total_float = task.total_float_days(hpd)
        free_float = (task.free_float_hr / hpd
                      if task.free_float_hr is not None else None)
        node = ActivityNode(
            node_id=node_id,
            snapshot_id=snapshot_id,
            task_id=task.task_id,
            task_code=task.task_code,
            original_name=task.name,
            normalised_name=_normalise(task.name),
            wbs_path=wbs_path,
            task_type=task.task_type,
            status=task.status,
            actual_start=task.act_start,
            actual_finish=task.act_finish,
            planned_start=task.target_start or task.early_start,
            planned_finish=task.target_finish or task.early_finish,
            original_duration_days=task.original_duration_days(hpd),
            actual_duration_working_days=actual_duration,
            remaining_duration_days=task.remaining_duration_days(hpd),
            data_date=project.data_date if project else None,
            calendar_id=task.clndr_id,
            classifications=classes,
            predecessors=tuple(sorted(predecessors.get(task.task_id, []))),
            successors=tuple(sorted(successors.get(task.task_id, []))),
            constraint_type=task.cstr_type or task.cstr_type2,
            constraint_date=task.cstr_date or task.cstr_date2,
            total_float_days=total_float,
            free_float_days=free_float,
            longest_path_flag=_clean(
                raw.get("driving_path_flag") or raw.get("longest_path_flag")
            ).upper() == "Y",
            critical_flag=_clean(
                raw.get("critical_path_flag") or raw.get("critical_flag")
            ).upper() == "Y",
            identity_fingerprint=fingerprint,
            resolution_status=ResolutionStatus.CONFIRMED,
            comparability=Comparability.COMPARABLE,
            source_refs=refs,
        )
        snapshot.activity_nodes[task.task_id] = node
        if task.is_milestone:
            name_lower = task.name.lower()
            rank = 50
            category = "interface"
            # Rank by the deployment's anchor token list (earlier = more
            # relevant), not a hard-coded trio: the spec's anchor set spans
            # sectional/mechanical completion, energisation and approvals.
            for position, token in enumerate(anchor_tokens):
                if token in name_lower:
                    rank, category = position + 1, "completion"
                    break
            milestone = MilestoneNode(
                node_id=stable_id("milestone", snapshot_id, task.task_id),
                snapshot_id=snapshot_id,
                task_id=task.task_id,
                task_code=task.task_code,
                name=task.name,
                actual_date=task.act_finish or task.act_start,
                milestone_category=category,
                relevance_rank=rank,
                constraint_type=task.cstr_type or task.cstr_type2,
                constraint_date=task.cstr_date or task.cstr_date2,
                source_refs=refs,
            )
            snapshot.milestone_nodes[task.task_id] = milestone
    return snapshot


@dataclass(frozen=True, slots=True)
class GenealogySummary:
    population: int
    comparable: int
    unresolved: int
    transitions: tuple[str, ...]
    added: int
    deleted: int
    # Task codes whose date movement is NOT comparable across each
    # consecutive snapshot pair (index-aligned with the pairs). E5 must
    # never be asserted across these boundaries (§9.3.4).
    pair_non_comparable: tuple[frozenset[str], ...] = ()

    @property
    def comparable_ratio(self) -> float:
        return self.comparable / self.population if self.population else 0.0


def build_genealogy(
    snapshots: Iterable[ProgrammeSnapshot], graph: EvidenceGraph
) -> GenealogySummary:
    ordered = sorted(
        snapshots,
        key=lambda item: item.record.data_date or datetime.min,
    )
    population = comparable = unresolved = added = deleted = 0
    transitions: list[str] = []
    pair_non_comparable: list[frozenset[str]] = []
    for previous, current in zip(ordered, ordered[1:], strict=False):
        prev_by_code = {n.task_code: n for n in previous.activity_nodes.values()}
        cur_by_code = {n.task_code: n for n in current.activity_nodes.values()}
        matched_current: set[str] = set()
        blocked: set[str] = set()
        for code, old in prev_by_code.items():
            population += 1
            new = cur_by_code.get(code)
            transition = "same"
            status = ResolutionStatus.CONFIRMED
            comparability_flag = Comparability.COMPARABLE
            reason = "Activity ID and code retained"
            if new is None:
                candidates = [node for node in current.activity_nodes.values()
                              if node.normalised_name == old.normalised_name
                              and node.wbs_path == old.wbs_path]
                if len(candidates) == 1:
                    new = candidates[0]
                    transition = "re-identified"
                    # §9.3.4: re-identified is Comparable only when the
                    # resolution is Confirmed. A unique name+WBS match with
                    # unchanged duration and calendar is treated as
                    # confirmed; anything looser stays Probable and its
                    # date movement is blocked from E5.
                    if (new.original_duration_days
                            == old.original_duration_days
                            and new.calendar_id == old.calendar_id):
                        status = ResolutionStatus.CONFIRMED
                        reason = ("Unique name+WBS match with unchanged "
                                  "duration and calendar; ID changed")
                    else:
                        status = ResolutionStatus.PROBABLE
                        comparability_flag = Comparability.NOT_COMPARABLE
                        reason = ("Unique name+WBS match only; duration or "
                                  "calendar changed with the ID")
                else:
                    unresolved += 1
                    deleted += 1
                    transitions.append("deleted_or_unresolved")
                    blocked.add(code)
                    continue
            elif new.normalised_name != old.normalised_name:
                transition = "renamed"
                reason = "Activity identity retained; name changed"
            matched_current.add(new.task_code)
            if comparability_flag is Comparability.COMPARABLE:
                comparable += 1
            else:
                blocked.add(code)
                blocked.add(new.task_code)
            transitions.append(transition)
            graph.add_edge(GenealogyEdge(
                edge_id=stable_id(
                    "genealogy", old.node_id, new.node_id, transition
                ),
                predecessor_node_id=old.node_id,
                successor_node_id=new.node_id,
                transition=transition,
                resolution_status=status,
                comparability=comparability_flag,
                reason=reason,
            ))
        added += len(set(cur_by_code) - matched_current)
        pair_non_comparable.append(frozenset(blocked))
    return GenealogySummary(
        population=population,
        comparable=comparable,
        unresolved=unresolved,
        transitions=tuple(transitions),
        added=added,
        deleted=deleted,
        pair_non_comparable=tuple(pair_non_comparable),
    )
