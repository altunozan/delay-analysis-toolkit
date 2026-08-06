"""WBS breakdown helper.

Real-world XER exports frequently carry no activity codes, but always carry a
WBS (PROJWBS table + TASK.wbs_id). This module lets the variance engine slice
the programme by WBS level instead: "level 1" is the band of nodes directly
under the project node (typically phases/areas), level 2 the next band, etc.

Only reads ``XerData.raw_tables`` — no parser changes required.
"""

from __future__ import annotations

from dataclasses import dataclass

from dcma.xer_parser import XerData


@dataclass(frozen=True)
class WbsNode:
    wbs_id: str
    name: str
    parent_id: str
    is_project_node: bool


def _nodes(data: XerData) -> dict[str, WbsNode]:
    out: dict[str, WbsNode] = {}
    for row in data.raw_tables.get("PROJWBS", []):
        wbs_id = row.get("wbs_id", "").strip()
        if not wbs_id:
            continue
        name = (row.get("wbs_name") or "").strip() or (
            row.get("wbs_short_name") or ""
        ).strip() or wbs_id
        out[wbs_id] = WbsNode(
            wbs_id=wbs_id,
            name=name,
            parent_id=row.get("parent_wbs_id", "").strip(),
            is_project_node=(row.get("proj_node_flag", "").strip() == "Y"),
        )
    return out


def _ancestry(node: WbsNode, nodes: dict[str, WbsNode]) -> list[WbsNode]:
    """Chain from the root (project node) down to ``node`` inclusive."""
    chain = [node]
    seen = {node.wbs_id}
    cur = node
    while cur.parent_id in nodes and cur.parent_id not in seen:
        cur = nodes[cur.parent_id]
        seen.add(cur.wbs_id)
        chain.append(cur)
    chain.reverse()
    # Drop the project root node(s) so level 1 = first real WBS band.
    while chain and chain[0].is_project_node:
        chain = chain[1:]
    return chain


def max_wbs_depth(data: XerData) -> int:
    """Deepest WBS level below the project node (0 = no usable WBS)."""
    nodes = _nodes(data)
    if not nodes:
        return 0
    return max((len(_ancestry(n, nodes)) for n in nodes.values()), default=0)


def task_wbs_assignments(data: XerData, level: int) -> dict[str, str]:
    """Map task_id -> the name of its WBS ancestor at ``level`` (1-based).

    Tasks whose WBS branch is shallower than ``level`` are labelled with their
    deepest available node, so nothing silently drops out of the breakdown.
    """
    nodes = _nodes(data)
    if not nodes:
        return {}

    # Resolve each wbs_id once — many tasks share the same node.
    label_cache: dict[str, str] = {}

    def label_for(wbs_id: str) -> str | None:
        if wbs_id in label_cache:
            return label_cache[wbs_id]
        node = nodes.get(wbs_id)
        if node is None:
            return None
        chain = _ancestry(node, nodes)
        if not chain:
            return None
        pick = chain[min(level, len(chain)) - 1]
        label_cache[wbs_id] = pick.name
        return pick.name

    out: dict[str, str] = {}
    for row in data.raw_tables.get("TASK", []):
        task_id = row.get("task_id", "").strip()
        wbs_id = row.get("wbs_id", "").strip()
        if not task_id or not wbs_id:
            continue
        label = label_for(wbs_id)
        if label:
            out[task_id] = label
    return out
