"""Module 14 — Hierarchy Rebuild (configurable re-grouping overlay).

Reorganises a programme by disregarding its stored WBS arrangement and
grouping activities under a user-defined hierarchy built from any ordered
combination of WBS levels and activity-code types, e.g.:

    WBS Level 3 > WBS Level 5 > Code X > Code Y > activities

Strictly non-destructive: the engine only READS the parsed file and builds
an overlay tree. Activity IDs, names, dates, durations, progress,
relationships, constraints, calendars, and the original WBS/code data are
untouched — the same XerData keeps feeding every other module. Activities
missing a value at any level group under "Unassigned" so nothing drops out.

Every build returns a validation block proving completeness (all source
activities present, none duplicated) alongside the tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from dcma.models import TYPE_WBS
from dcma.xer_parser import XerData

from .activity_codes import activity_code_types, task_code_assignments
from .wbs import _ancestry, _nodes, max_wbs_depth

UNASSIGNED = "Unassigned"


# --------------------------------------------------------------------------- #
# Available dimensions
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Dimension:
    """One selectable hierarchy level: a WBS depth or an activity-code type."""

    dim_id: str          # "wbs:3" | "code:<actv_code_type_id>"
    label: str           # "WBS Level 3" | "Code: Zone"


def available_dimensions(data: XerData) -> list[Dimension]:
    """Every WBS level and activity-code type present in this file."""
    dims: list[Dimension] = []
    for lvl in range(1, max_wbs_depth(data) + 1):
        dims.append(Dimension(f"wbs:{lvl}", f"WBS Level {lvl}"))
    for ct in activity_code_types(data):
        dims.append(Dimension(f"code:{ct.type_id}",
                              f"Code: {ct.name} "
                              f"({ct.assigned_task_count} assigned)"))
    return dims


def _strict_wbs_level(data: XerData, level: int) -> dict[str, str]:
    """task_id -> WBS ancestor name at exactly ``level``; absent if shallower.

    Unlike variance's forgiving lookup, the rebuild must NOT substitute a
    deeper/shallower node — a missing value belongs under Unassigned.
    """
    nodes = _nodes(data)
    if not nodes:
        return {}
    label_cache: dict[str, str | None] = {}

    def label_for(wbs_id: str) -> str | None:
        if wbs_id not in label_cache:
            node = nodes.get(wbs_id)
            chain = _ancestry(node, nodes) if node else []
            label_cache[wbs_id] = (chain[level - 1].name
                                   if len(chain) >= level else None)
        return label_cache[wbs_id]

    out: dict[str, str] = {}
    for row in data.raw_tables.get("TASK", []):
        task_id = row.get("task_id", "").strip()
        label = label_for(row.get("wbs_id", "").strip())
        if task_id and label:
            out[task_id] = label
    return out


def _dimension_mapping(data: XerData, dim_id: str) -> dict[str, str]:
    kind, _, key = dim_id.partition(":")
    if kind == "wbs":
        return _strict_wbs_level(data, int(key))
    if kind == "code":
        return task_code_assignments(data, key)
    raise ValueError(f"Unknown dimension id: {dim_id}")


# --------------------------------------------------------------------------- #
# The overlay tree
# --------------------------------------------------------------------------- #

@dataclass
class GanttActivity:
    task_code: str
    name: str
    start: datetime | None       # actual start, else early start
    finish: datetime | None      # actual finish, else early finish
    is_milestone: bool
    status: str                  # "complete" | "in progress" | "not started"


@dataclass
class GanttNode:
    name: str
    level: int                   # 0-based depth of this group
    children: dict[str, "GanttNode"] = field(default_factory=dict)
    activities: list[GanttActivity] = field(default_factory=list)
    start: datetime | None = None    # rollup: earliest child start
    finish: datetime | None = None   # rollup: latest child finish
    activity_count: int = 0          # rollup incl. all descendants
    complete_count: int = 0


@dataclass
class HierarchyResult:
    programme_label: str
    dimension_labels: list[str]
    root: GanttNode = field(default_factory=lambda: GanttNode("root", -1))
    # --- validation block ---
    source_activities: int = 0
    placed_activities: int = 0
    duplicate_ids: int = 0
    unassigned_per_level: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return (self.placed_activities == self.source_activities
                and self.duplicate_ids == 0)


def build_hierarchy(
    data: XerData,
    dim_ids: list[str],
    programme_label: str,
    *,
    dim_labels: list[str] | None = None,
) -> HierarchyResult:
    """Group every activity under the ordered dimensions (read-only)."""
    labels = dim_labels or dim_ids
    result = HierarchyResult(programme_label=programme_label,
                             dimension_labels=list(labels))
    result.caveats.append(
        "The rebuilt hierarchy is a read-only grouping overlay: activity "
        "IDs, names, dates, durations, progress, logic, constraints, "
        "calendars, and the original WBS/code data are unchanged; group "
        "summary bars bracket the earliest start and latest finish of the "
        "activities beneath them."
    )
    mappings = [_dimension_mapping(data, d) for d in dim_ids]
    result.unassigned_per_level = [0] * len(dim_ids)

    seen_ids: set[str] = set()
    for t in data.tasks:
        if t.task_type == TYPE_WBS:      # summary rows are structure, not work
            continue
        result.source_activities += 1
        if t.task_id in seen_ids:
            result.duplicate_ids += 1
            continue
        seen_ids.add(t.task_id)

        node = result.root
        for lvl, mapping in enumerate(mappings):
            value = mapping.get(t.task_id) or UNASSIGNED
            if value == UNASSIGNED:
                result.unassigned_per_level[lvl] += 1
            node = node.children.setdefault(value, GanttNode(value, lvl))

        status = ("complete" if t.is_complete
                  else "in progress" if t.act_start is not None
                  else "not started")
        node.activities.append(GanttActivity(
            task_code=t.task_code, name=t.name,
            start=t.act_start or t.early_start,
            finish=t.act_finish or t.early_finish,
            is_milestone=t.is_milestone, status=status))
        result.placed_activities += 1

    _rollup(result.root)

    if not result.is_complete:
        result.warnings.append(
            f"Validation FAILED: {result.source_activities} source "
            f"activities vs {result.placed_activities} placed "
            f"({result.duplicate_ids} duplicate ids) — do not rely on this "
            "view."
        )
    for lvl, n in enumerate(result.unassigned_per_level):
        if n:
            result.warnings.append(
                f"{n} activities carry no value for "
                f"'{labels[lvl]}' and group under '{UNASSIGNED}' at that "
                "level."
            )
    return result


def _rollup(node: GanttNode) -> None:
    """Depth-first min-start / max-finish and counts for every group."""
    starts: list[datetime] = []
    finishes: list[datetime] = []
    node.activity_count = len(node.activities)
    node.complete_count = sum(1 for a in node.activities
                              if a.status == "complete")
    for a in node.activities:
        if a.start:
            starts.append(a.start)
        if a.finish:
            finishes.append(a.finish)
    for child in node.children.values():
        _rollup(child)
        node.activity_count += child.activity_count
        node.complete_count += child.complete_count
        if child.start:
            starts.append(child.start)
        if child.finish:
            finishes.append(child.finish)
    node.start = min(starts) if starts else None
    node.finish = max(finishes) if finishes else None


# --------------------------------------------------------------------------- #
# Serialisation for the interactive viewer + config save/load
# --------------------------------------------------------------------------- #

def tree_to_dict(node: GanttNode) -> dict:
    """JSON-safe nested dict for the HTML gantt component."""
    def iso(d: datetime | None) -> str | None:
        return d.strftime("%Y-%m-%d") if d else None

    return {
        "name": node.name,
        "level": node.level,
        "start": iso(node.start),
        "finish": iso(node.finish),
        "count": node.activity_count,
        "complete": node.complete_count,
        "children": [tree_to_dict(c) for c in sorted(
            node.children.values(),
            key=lambda c: (c.start or datetime.max, c.name))],
        "activities": [{
            "id": a.task_code, "name": a.name,
            "start": iso(a.start), "finish": iso(a.finish),
            "milestone": a.is_milestone, "status": a.status,
        } for a in sorted(node.activities,
                          key=lambda a: (a.start or datetime.max,
                                         a.task_code))],
    }


def config_to_json(name: str, dim_ids: list[str],
                   dim_labels: list[str]) -> str:
    import json
    return json.dumps({"name": name, "dimensions": dim_ids,
                       "labels": dim_labels, "version": 1}, indent=2)


def config_from_json(text: str) -> tuple[str, list[str], list[str]] | None:
    import json
    try:
        obj = json.loads(text)
        dims = [str(d) for d in obj["dimensions"]]
        if not dims or not all(d.partition(":")[0] in ("wbs", "code")
                               for d in dims):
            return None
        labels = [str(x) for x in obj.get("labels", dims)]
        if len(labels) != len(dims):
            labels = dims
        return str(obj.get("name", "saved view")), dims, labels
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
