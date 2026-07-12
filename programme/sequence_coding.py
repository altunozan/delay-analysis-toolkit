"""Module 13 — Sequence Coding (propose-confirm work front × stage).

Where activity codes are incomplete and the WBS unhelpful, an analyst
recodes the programme to expose the construction sequence: a work-front
dimension (where the work is) crossed with a stage dimension (what kind of
work it is). This module automates the PROPOSAL of that coding from the
evidence in the file — activity-ID tokens, WBS fallback, and stage keyword
rules on activity names — and every assignment carries its evidence so the
analyst can confirm or override it. Nothing downstream runs on an
unconfirmable black box: the final mapping is a disclosed, editable table
that prints with the report.

Deterministic analysis on the confirmed mapping: actual-date bands per
(front, stage), the stage sequence per front, and the late-running fronts
that drove completion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from dcma.config import DCMAConfig
from dcma.xer_parser import XerData

from .wbs import task_wbs_assignments

STANDING_CAVEATS = [
    "The work-front x stage coding is an analytical overlay proposed from "
    "evidence in the programme file (activity-ID tokens, WBS, and activity-"
    "name keywords) and confirmed or amended by the analyst. The full "
    "mapping, with the evidence for each assignment, is disclosed in the "
    "report so it can be independently tested.",
    "Bands per work front and stage bracket the earliest actual start and "
    "latest actual finish of the mapped activities — as-recorded dates, "
    "not independently verified progress.",
    "The coding shows where and when work ran; it does not by itself "
    "attribute the cause of any front running late.",
]

# Stage rules: applied in order, first match wins. 9 stages + Unclassified
# keeps the categorical palette within accessible limits.
STAGE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Design, Submittals & Approvals",
     ("submission", "submittal", "shop drawing", "design", "ifc",
      "review", "approval", "sample", "mock")),
    ("Procurement & Fabrication",
     ("procure", "fabricat", "delivery", "order", "purchase",
      "manufactur")),
    ("Enabling, Access & MEP",
     ("mobiliz", "site access", "possession", "commencement", "enabling",
      "mep", "1st fix", "first fix", "2nd fix", "clearance", "framing",
      "prerequisite")),
    ("Structure & Screed",
     ("screed", "concrete", "block", "masonry", "structure", "slab")),
    ("Ceilings & Closures", ("ceiling", "closure")),
    ("Walls, Glazing & Cladding",
     ("cladding", "glaz", "aluminium", "panel", "wall system",
      "partition", "curtain", "wall cladding")),
    ("Joinery, Doors & Flooring",
     ("joinery", "carpentry", "door", "ironmonger", "tiling", "floor",
      "wood")),
    ("Finishes & Fit-Out",
     ("paint", "wall cover", "wallpaper", "light", "electrical",
      "sanitary", "fixture", "fitting", "trim", "finish")),
    ("Snagging & Handover",
     ("snag", "handover", "taking over", "completion", "punch")),
]
UNCLASSIFIED = "Unclassified"
STAGE_ORDER: list[str] = [name for name, _ in STAGE_RULES] + [UNCLASSIFIED]

_TOKEN_RE = re.compile(r"^[A-Za-z]{1,3}\d{0,3}$")


@dataclass
class MappingRow:
    task_code: str
    name: str
    front: str
    stage: str
    front_evidence: str
    stage_evidence: str
    act_start: datetime | None = None
    act_finish: datetime | None = None
    is_complete: bool = False


@dataclass
class SequenceMappingProposal:
    programme_label: str
    rows: list[MappingRow] = field(default_factory=list)
    fronts: list[str] = field(default_factory=list)      # by activity count
    stage_coverage_pct: float = 0.0     # rows with a matched stage
    front_coverage_pct: float = 0.0     # rows with a token/WBS front
    warnings: list[str] = field(default_factory=list)


def propose_sequence_mapping(
    data: XerData, programme_label: str
) -> SequenceMappingProposal:
    """Propose front x stage per activity, with evidence per assignment."""
    prop = SequenceMappingProposal(programme_label=programme_label)
    wbs2 = task_wbs_assignments(data, level=2)

    front_counts: dict[str, int] = {}
    stage_hits = front_hits = 0
    for t in data.tasks:
        if t.is_loe_or_wbs:
            continue
        # --- work front: leading activity-ID token, WBS level 2 fallback
        parts = t.task_code.split("-")
        if len(parts) >= 2 and _TOKEN_RE.match(parts[0]):
            front = parts[0].upper()
            f_ev = f"ID token '{parts[0]}'"
            front_hits += 1
        else:
            wbs = wbs2.get(t.task_id)
            if wbs:
                front = wbs
                f_ev = "WBS level 2"
                front_hits += 1
            else:
                front, f_ev = "General", "no token or WBS"
        # --- stage: first keyword rule matching the activity name
        low = t.name.lower()
        stage, s_ev = UNCLASSIFIED, "no keyword matched"
        for stage_name, keywords in STAGE_RULES:
            hit = next((k for k in keywords if k in low), None)
            if hit:
                stage, s_ev = stage_name, f"keyword '{hit}'"
                stage_hits += 1
                break
        prop.rows.append(MappingRow(
            task_code=t.task_code, name=t.name, front=front, stage=stage,
            front_evidence=f_ev, stage_evidence=s_ev,
            act_start=t.act_start, act_finish=t.act_finish,
            is_complete=t.is_complete))
        front_counts[front] = front_counts.get(front, 0) + 1

    total = len(prop.rows)
    if total:
        prop.stage_coverage_pct = round(100.0 * stage_hits / total, 1)
        prop.front_coverage_pct = round(100.0 * front_hits / total, 1)
    prop.fronts = sorted(front_counts, key=lambda f: -front_counts[f])

    if prop.stage_coverage_pct < 70:
        prop.warnings.append(
            f"Only {prop.stage_coverage_pct:.0f}% of activities matched a "
            "stage keyword — review the Unclassified rows before relying "
            "on the sequence view."
        )
    if len(prop.fronts) > 60:
        prop.warnings.append(
            f"{len(prop.fronts)} distinct work fronts proposed — consider "
            "merging related ID tokens in the mapping table."
        )
    return prop


@dataclass
class FrontStageBand:
    front: str
    stage: str
    activity_count: int
    complete_count: int
    act_start: datetime | None
    act_finish: datetime | None


@dataclass
class SequenceResult:
    programme_label: str
    mapping_confirmed: bool
    bands: list[FrontStageBand] = field(default_factory=list)
    fronts_by_finish: list[tuple[str, datetime | None]] = field(
        default_factory=list)                 # latest actual finish first
    stage_order: list[str] = field(default_factory=list)
    mapped_activities: int = 0
    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


def analyse_sequence(
    rows: list[MappingRow],
    programme_label: str,
    *,
    mapping_confirmed: bool = False,
    min_front_activities: int = 3,
    config: DCMAConfig | None = None,
) -> SequenceResult:
    """Actual-date bands per (front, stage) from the (confirmed) mapping."""
    result = SequenceResult(programme_label=programme_label,
                            mapping_confirmed=mapping_confirmed,
                            stage_order=list(STAGE_ORDER))
    result.caveats.extend(STANDING_CAVEATS)
    if not mapping_confirmed:
        result.caveats.append(
            "The mapping in use is the AUTO-PROPOSED coding; it has not "
            "been confirmed by the analyst in this session."
        )

    groups: dict[tuple[str, str], list[MappingRow]] = {}
    for r in rows:
        if r.act_start is None:
            continue
        groups.setdefault((r.front, r.stage), []).append(r)
    result.mapped_activities = sum(len(v) for v in groups.values())

    finish_by_front: dict[str, datetime | None] = {}
    count_by_front: dict[str, int] = {}
    for (front, stage), members in sorted(groups.items()):
        starts = [m.act_start for m in members if m.act_start]
        finishes = [m.act_finish for m in members if m.act_finish]
        band = FrontStageBand(
            front=front, stage=stage,
            activity_count=len(members),
            complete_count=sum(1 for m in members if m.is_complete),
            act_start=min(starts) if starts else None,
            act_finish=max(finishes) if finishes else None)
        result.bands.append(band)
        count_by_front[front] = count_by_front.get(front, 0) + len(members)
        if band.act_finish is not None:
            cur = finish_by_front.get(front)
            if cur is None or band.act_finish > cur:
                finish_by_front[front] = band.act_finish

    result.fronts_by_finish = sorted(
        ((f, fin) for f, fin in finish_by_front.items()
         if count_by_front.get(f, 0) >= min_front_activities),
        key=lambda x: (x[1] is None, x[1]), reverse=True)

    if result.fronts_by_finish:
        top = result.fronts_by_finish[:3]
        result.warnings.append(
            "Last-finishing work fronts (as recorded): "
            + "; ".join(f"{f} ({fin:%Y-%m-%d})" for f, fin in top
                        if fin is not None)
            + " — the fronts that drove recorded completion of the works "
            "performed to date."
        )
    incomplete_fronts = sorted(
        {r.front for r in rows if not r.is_complete and r.act_start})
    if incomplete_fronts:
        result.warnings.append(
            f"{len(incomplete_fronts)} work fronts still carry started-but-"
            "unfinished activities as at the data date."
        )
    return result
