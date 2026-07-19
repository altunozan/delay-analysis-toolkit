"""Module 15 — Prospective Time Impact Analysis (TIA).

The prospective workflow: take the current approved update, describe a
delay event, build a fragnet (AI-drafted or analyst-built, always
analyst-confirmed), insert it into a CONTROLLED IN-MEMORY COPY of the
network, run a simplified CPM forward pass, and compare pre-impact vs
post-impact milestone forecasts.

Design principles (non-negotiable, mirrored from the retrospective side):
- The source programme is never modified — the insertion exists only in
  this analysis run.
- The AI recommends a fragnet with evidence and assumptions; it cannot
  insert anything. The analyst edits and confirms every row.
- Pre- and post-impact forecasts are computed by the SAME simplified CPM,
  so the measured impact is method-consistent; the gap between this
  engine's pre-impact forecast and P6's own dates is disclosed as a
  calibration figure, never hidden.
- Durations, logic, and lags carry their source and assumptions into the
  report.

The CPM here is a screening-level forward pass: remaining durations from
the data date, FS/SS/FF/SF with lags, working days approximated as elapsed
days at each activity's calendar rate. It is designed to measure the
DELTA a fragnet causes, and must be confirmed in P6 before contractual
reliance — the standing caveats say so.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from dcma.config import DCMAConfig
from dcma.xer_parser import XerData

STANDING_CAVEATS = [
    "Performed as a prospective Time Impact Analysis in line with AACE RP "
    "52R-06: the fragnet models the event with the fewest activities "
    "practical, is inserted into the most recent accepted schedule update "
    "prior to the event, and the time impact is the difference between "
    "the pre- and post-insertion completion forecasts. Excusability and "
    "compensability are contractual determinations outside this "
    "calculation.",
    "The impact is measured as post-impact minus pre-impact under one and "
    "the same simplified CPM forward pass (remaining durations from the "
    "data date; FS/SS/FF/SF with lags; working days approximated as "
    "elapsed days at each activity's calendar rate). Deltas are therefore "
    "method-consistent, but absolute dates should be confirmed by "
    "re-scheduling in Primavera P6 before contractual reliance.",
    "The fragnet is inserted into an in-memory copy only — the source "
    "programme is unchanged and remains the record copy.",
    "The fragnet, its durations, logic, and lags are the analyst's "
    "confirmed representation of the event; where the AI drafted "
    "components, their sources and assumptions are disclosed per row.",
    "A forecast impact is not an entitlement conclusion: responsibility, "
    "notice compliance, and concurrency fall to the contractual analysis, "
    "not this calculation.",
]

LINK_TYPES = ("FS", "SS", "FF", "SF")
_REL_TO_SHORT = {"PR_FS": "FS", "PR_SS": "SS", "PR_FF": "FF", "PR_SF": "SF"}


# --------------------------------------------------------------------------- #
# Event + fragnet model
# --------------------------------------------------------------------------- #

@dataclass
class DelayEvent:
    event_id: str
    title: str
    description: str = ""
    date_raised: datetime | None = None
    responsibility_asserted: str = ""     # asserted, never concluded
    evidence_note: str = ""
    area: str = ""
    discipline: str = ""
    project_context: str = ""
    work_package: str = ""


@dataclass
class EventScopeAssessment:
    """Transparent, reviewable interpretation before any fragnet exists."""
    work_nature: str
    lifecycle_stages: list[str]
    enabling_requirements: list[str]
    search_terms: list[str]
    unanswered_questions: list[str]


def assess_event_scope(event: DelayEvent) -> EventScopeAssessment:
    """Create a conservative retrieval brief from the recorded event facts.

    This does not create activities. It makes the assumptions and missing
    information visible before programme retrieval or AI drafting.
    """
    text = " ".join((event.title, event.description, event.work_package,
                     event.area, event.discipline)).lower()
    stages: list[str] = []
    enabling: list[str] = []
    if any(k in text for k in ("design", "drawing", "ifc", "shop drawing")):
        stages.append("Design / information release")
    if any(k in text for k in ("approve", "review", "submittal", "rfi")):
        stages.append("Review / approval")
    if any(k in text for k in ("procure", "material", "equipment", "vendor")):
        stages.append("Procurement / delivery")
    if any(k in text for k in ("test", "commission", "inspect", "handover")):
        stages.append("Testing / inspection / handover")
    stages.append("Construction / implementation")
    if any(k in text for k in ("access", "permit", "survey", "mobil")):
        enabling.append("Access / permit / survey / mobilisation")
    if any(k in text for k in ("temporary", "shoring", "scaffold", "cofferdam")):
        enabling.append("Temporary works")
    if any(k in text for k in ("rework", "remove", "demol", "replace")):
        nature = "Rework / replacement"
    elif any(k in text for k in ("additional", "new", "variation", "instruct")):
        nature = "Additional / changed permanent work"
    else:
        nature = "Unclassified — analyst confirmation required"
    words = [w for w in re.findall(r"[a-z]{3,}", text) if w not in _STOP]
    search_terms = list(dict.fromkeys(words))[:20]
    questions = []
    if not event.area:
        questions.append("Which location, system or workface is affected?")
    if not event.discipline:
        questions.append("Which discipline owns the physical scope?")
    if not event.work_package:
        questions.append("What construction work package best represents the event?")
    if not event.evidence_note:
        questions.append("Which instruction, drawing, RFI or notice evidences the scope?")
    if not any(s.startswith("Design") for s in stages):
        questions.append("Is design or information release required before execution?")
    if not any(s.startswith("Procurement") for s in stages):
        questions.append("Are procurement or delivery activities required?")
    return EventScopeAssessment(nature, list(dict.fromkeys(stages)),
                                list(dict.fromkeys(enabling)), search_terms,
                                questions)


@dataclass
class FragnetLink:
    other_id: str          # existing activity code OR another fragnet id
    link_type: str = "FS"
    lag_days: float = 0.0


@dataclass
class FragnetActivity:
    act_id: str
    name: str
    duration_days: float
    predecessors: list[FragnetLink] = field(default_factory=list)
    successors: list[FragnetLink] = field(default_factory=list)
    rationale: str = ""            # evidence / source / template
    assumptions: str = ""
    confidence: str = "medium"     # low | medium | high
    calendar_id: str = ""          # selected P6 calendar; calculation caveat applies


def parse_links(text: str) -> list[FragnetLink]:
    """'A1000:FS:0; F1:SS:5' -> FragnetLinks (type/lag optional)."""
    out: list[FragnetLink] = []
    for part in re.split(r"[;,]", text or ""):
        part = part.strip()
        if not part:
            continue
        bits = part.split(":")
        link = FragnetLink(other_id=bits[0].strip())
        if len(bits) > 1 and bits[1].strip().upper() in LINK_TYPES:
            link.link_type = bits[1].strip().upper()
        if len(bits) > 2:
            try:
                link.lag_days = float(bits[2])
            except ValueError:
                pass
        out.append(link)
    return out


def links_to_text(links: list[FragnetLink]) -> str:
    return "; ".join(f"{l.other_id}:{l.link_type}:{l.lag_days:g}"
                     for l in links)


# --------------------------------------------------------------------------- #
# Template search — comparable activities in the current programme
# --------------------------------------------------------------------------- #

_STOP = {"the", "of", "and", "for", "to", "in", "on", "at", "a", "an",
         "works", "work", "new", "with"}


def find_template_activities(
    data: XerData, text: str, top_n: int = 12,
) -> list[dict]:
    """Rank existing activities by token overlap with the event text.

    Returns dicts with code, name, duration_days, matched tokens — the
    project-specific evidence base for durations and logic patterns.
    """
    config = DCMAConfig()
    tokens = {w for w in re.findall(r"[a-z]{3,}", (text or "").lower())
              if w not in _STOP}
    if not tokens:
        return []
    scored = []
    for t in data.tasks:
        if t.is_loe_or_wbs:
            continue
        name_tokens = set(re.findall(r"[a-z]{3,}", t.name.lower()))
        hit = tokens & name_tokens
        if not hit:
            continue
        hpd = data.hours_per_day(t, config)
        scored.append({
            "code": t.task_code, "name": t.name,
            "duration_days": t.original_duration_days(hpd),
            "matched": ", ".join(sorted(hit)),
            "score": len(hit) / max(len(name_tokens), 1) + 0.1 * len(hit),
        })
    scored.sort(key=lambda s: -s["score"])
    return scored[:top_n]


def find_template_work_packages(
    data: XerData, text: str, top_n: int = 5,
) -> list[dict]:
    """Rank project WBS work packages and expose their existing sequence.

    The recommendation remains retrieval-led: each candidate is made only
    from activities already present in the uploaded programme.
    """
    matches = find_template_activities(data, text, top_n=40)
    if not matches:
        return []
    match_by_code = {m["code"]: m for m in matches}
    task_rows = data.raw_tables.get("TASK", [])
    wbs_rows = data.raw_tables.get("PROJWBS", [])
    wbs_name = {r.get("wbs_id", ""): (r.get("wbs_short_name")
                or r.get("wbs_name") or r.get("wbs_id", ""))
                for r in wbs_rows}
    wbs_for = {r.get("task_id", ""): r.get("wbs_id", "")
               for r in task_rows}
    packages: dict[str, dict] = {}
    for task in data.tasks:
        if task.task_code not in match_by_code:
            continue
        wid = wbs_for.get(task.task_id, "") or "unassigned"
        pkg = packages.setdefault(wid, {
            "wbs_id": wid, "wbs_name": wbs_name.get(wid, wid),
            "score": 0.0, "activities": [], "matched": set(),
        })
        pkg["score"] += match_by_code[task.task_code]["score"]
        pkg["matched"].update(match_by_code[task.task_code]["matched"].split(", "))
    for wid, pkg in packages.items():
        members = [t for t in data.tasks
                   if wbs_for.get(t.task_id, "") == wid
                   and not t.is_loe_or_wbs]
        members.sort(key=lambda t: (t.target_start or t.early_start
                                    or t.act_start or datetime.max,
                                    t.task_code))
        pkg["activities"] = [{
            "code": t.task_code, "name": t.name,
            "duration_days": t.original_duration_days(
                data.hours_per_day(t, DCMAConfig())),
        } for t in members[:25]]
        pkg["matched"] = ", ".join(sorted(x for x in pkg["matched"] if x))
        pkg["activity_count"] = len(members)
    ranked = sorted(packages.values(), key=lambda p: -p["score"])
    return ranked[:top_n]


# --------------------------------------------------------------------------- #
# Validation — before anything is inserted
# --------------------------------------------------------------------------- #

def validate_fragnet(
    data: XerData, fragnet: list[FragnetActivity],
) -> list[str]:
    """Screening checks; every issue is a plain-language string."""
    issues: list[str] = []
    existing = {t.task_code for t in data.tasks}
    frag_ids = [f.act_id for f in fragnet]
    frag_set = set(frag_ids)

    if len(frag_set) != len(frag_ids):
        issues.append("Duplicate fragnet activity IDs.")
    clash = frag_set & existing
    if clash:
        issues.append("Fragnet IDs clash with existing activities: "
                      + ", ".join(sorted(clash)[:6]))
    known = existing | frag_set
    has_succ_to_network = False
    for f in fragnet:
        if f.duration_days is None or f.duration_days < 0:
            issues.append(f"{f.act_id}: negative or missing duration.")
        elif f.duration_days == 0:
            issues.append(f"{f.act_id}: zero duration — a 0d step cannot "
                          "delay anything; enter the forecast duration.")
        elif f.duration_days > 365:
            issues.append(f"{f.act_id}: duration {f.duration_days:.0f}d "
                          "exceeds a year — check the estimate.")
        if f.calendar_id and f.calendar_id not in data.calendars:
            issues.append(f"{f.act_id}: unknown calendar "
                          f"'{f.calendar_id}'.")
        if not f.predecessors:
            issues.append(f"{f.act_id}: open start (no predecessor) — the "
                          "event work would float free of the network.")
        if not f.successors and not any(
                f.act_id == l.other_id
                for g in fragnet for l in g.predecessors):
            issues.append(f"{f.act_id}: open end (no successor) — the "
                          "impact cannot reach any milestone.")
        for l in f.predecessors + f.successors:
            if l.other_id not in known:
                issues.append(f"{f.act_id}: link references unknown "
                              f"activity '{l.other_id}'.")
            if l.link_type not in LINK_TYPES:
                issues.append(f"{f.act_id}: invalid link type "
                              f"'{l.link_type}'.")
            if abs(l.lag_days) > 60:
                issues.append(f"{f.act_id} -> {l.other_id}: lag "
                              f"{l.lag_days:+.0f}d is excessive — model "
                              "waiting time as an activity instead.")
        for l in f.successors:
            if l.other_id in existing:
                has_succ_to_network = True
    if fragnet and not has_succ_to_network:
        issues.append("No fragnet successor ties back into the existing "
                      "network — the insertion cannot impact completion.")

    # circular logic within the fragnet
    adj = {f.act_id: [l.other_id for l in f.successors
                      if l.other_id in frag_set]
           for f in fragnet}
    for f in fragnet:
        for l in f.predecessors:
            if l.other_id in frag_set:
                adj[l.other_id].append(f.act_id)
    seen: dict[str, int] = {}

    def dfs(u):
        seen[u] = 1
        for v in adj.get(u, []):
            if seen.get(v) == 1:
                return True
            if seen.get(v) is None and dfs(v):
                return True
        seen[u] = 2
        return False

    if any(seen.get(fid) is None and dfs(fid) for fid in frag_set):
        issues.append("Circular logic inside the fragnet.")
    return issues


# --------------------------------------------------------------------------- #
# Simplified CPM forward pass (pre- and post-impact under one method)
# --------------------------------------------------------------------------- #

@dataclass
class MilestoneImpact:
    code: str
    name: str
    pre: datetime | None
    post: datetime | None

    @property
    def delta_days(self) -> float | None:
        if self.pre and self.post:
            return round((self.post - self.pre).total_seconds() / 86400, 1)
        return None


@dataclass
class TIAResult:
    programme_label: str
    event: DelayEvent
    fragnet: list[FragnetActivity]
    data_date: datetime | None = None
    completion_pre: datetime | None = None
    completion_post: datetime | None = None
    completion_delta_days: float | None = None
    milestone_impacts: list[MilestoneImpact] = field(default_factory=list)
    fragnet_dates: dict = field(default_factory=dict)   # act_id -> (ES, EF)
    calibration_days: float | None = None   # our pre vs P6's own forecast
    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


def _forward_pass(
    nodes: dict[str, float],                 # id -> remaining duration days
    preds: dict[str, list[tuple[str, str, float]]],  # id -> (pred, type, lag)
    start: datetime,
    started_at: dict[str, datetime],
) -> tuple[dict[str, datetime], dict[str, datetime], list[str]]:
    """Kahn-ordered forward pass. Returns (ES, EF, warnings)."""
    warnings: list[str] = []
    succs: dict[str, list[str]] = {n: [] for n in nodes}
    indeg = {n: 0 for n in nodes}
    for n, plist in preds.items():
        for p, _, _ in plist:
            if p in nodes:
                succs[p].append(n)
                indeg[n] += 1
    queue = [n for n, d in indeg.items() if d == 0]
    order: list[str] = []
    while queue:
        u = queue.pop()
        order.append(u)
        for v in succs[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                queue.append(v)
    if len(order) < len(nodes):
        warnings.append(
            f"{len(nodes) - len(order)} activities sit in circular logic "
            "and were scheduled from the data date."
        )
        order += [n for n in nodes if n not in set(order)]

    ES: dict[str, datetime] = {}
    EF: dict[str, datetime] = {}
    for n in order:
        dur = timedelta(days=max(nodes[n], 0.0))
        es = started_at.get(n, start)
        ef_c = None
        for p, ltype, lag in preds.get(n, []):
            if p not in EF:
                continue
            lagd = timedelta(days=lag)
            if ltype == "FS":
                es = max(es, EF[p] + lagd)
            elif ltype == "SS":
                es = max(es, ES[p] + lagd)
            elif ltype == "FF":
                c = EF[p] + lagd
                ef_c = c if ef_c is None else max(ef_c, c)
            elif ltype == "SF":
                c = ES[p] + lagd
                ef_c = c if ef_c is None else max(ef_c, c)
        ef = es + dur
        if ef_c is not None and ef_c > ef:
            ef = ef_c
            es = ef - dur
        ES[n], EF[n] = es, ef
    return ES, EF, warnings


def run_tia(
    data: XerData,
    programme_label: str,
    event: DelayEvent,
    fragnet: list[FragnetActivity],
    *,
    config: DCMAConfig | None = None,
    top_milestones: int = 15,
    target_milestone: str | None = None,
) -> TIAResult:
    """Pre- vs post-impact forecast under one simplified CPM."""
    config = config or DCMAConfig()
    result = TIAResult(programme_label=programme_label, event=event,
                       fragnet=fragnet)
    result.caveats.extend(STANDING_CAVEATS)
    dd = data.project.data_date if data.project else None
    if dd is None:
        result.warnings.append("No data date — cannot run the forward pass.")
        return result
    result.data_date = dd

    # --- network of incomplete activities -------------------------------
    inc = {t.task_id: t for t in data.tasks
           if not t.is_loe_or_wbs and t.is_incomplete}
    code_of = {tid: t.task_code for tid, t in inc.items()}
    nodes: dict[str, float] = {}
    started: dict[str, datetime] = {}
    for t in inc.values():
        hpd = data.hours_per_day(t, config)
        rem = t.remaining_duration_days(hpd)
        if rem is None:
            rem = t.original_duration_days(hpd) or 0.0
        nodes[t.task_code] = max(rem, 0.0)
        if t.act_start is not None:
            started[t.task_code] = dd
    preds: dict[str, list[tuple[str, str, float]]] = {n: [] for n in nodes}
    for rel in data.relationships:
        s = code_of.get(rel.task_id)
        p = code_of.get(rel.pred_task_id)
        if s is None or p is None:
            continue
        t = inc[rel.pred_task_id]
        hpd = data.hours_per_day(t, config)
        lag = (rel.lag_hr / hpd) if rel.lag_hr else 0.0
        preds[s].append((p, _REL_TO_SHORT.get(rel.pred_type, "FS"), lag))

    ES0, EF0, w0 = _forward_pass(dict(nodes), {k: list(v) for k, v
                                               in preds.items()}, dd, started)

    # --- insert the fragnet into a COPY ----------------------------------
    nodes_p = dict(nodes)
    preds_p = {k: list(v) for k, v in preds.items()}
    for f in fragnet:
        nodes_p[f.act_id] = max(f.duration_days or 0.0, 0.0)
        preds_p.setdefault(f.act_id, [])
        for l in f.predecessors:
            preds_p[f.act_id].append((l.other_id, l.link_type, l.lag_days))
        for l in f.successors:
            preds_p.setdefault(l.other_id, []).append(
                (f.act_id, l.link_type, l.lag_days))
    ES1, EF1, w1 = _forward_pass(nodes_p, preds_p, dd, started)
    result.warnings.extend(sorted(set(w0 + w1)))
    result.fragnet_dates = {f.act_id: (ES1.get(f.act_id),
                                       EF1.get(f.act_id))
                            for f in fragnet}

    # --- milestone + completion impacts ----------------------------------
    ms = [t for t in inc.values() if t.is_milestone]
    impacts = []
    for t in ms:
        c = t.task_code
        impacts.append(MilestoneImpact(
            code=c, name=t.name, pre=EF0.get(c), post=EF1.get(c)))
    impacts.sort(key=lambda m: -(m.delta_days or 0))
    if target_milestone:
        targeted = [m for m in impacts if m.code == target_milestone]
        remainder = [m for m in impacts if m.code != target_milestone]
        result.milestone_impacts = (targeted + remainder)[:top_milestones]
    else:
        result.milestone_impacts = impacts[:top_milestones]

    if EF0:
        result.completion_pre = max(EF0.values())
    if EF1:
        result.completion_post = max(
            ef for code, ef in EF1.items())
    if result.completion_pre and result.completion_post:
        result.completion_delta_days = round(
            (result.completion_post
             - result.completion_pre).total_seconds() / 86400, 1)

    # --- calibration vs P6's own forecast ---------------------------------
    p6_fin = data.project.scheduled_finish if data.project else None
    if p6_fin and result.completion_pre:
        result.calibration_days = round(
            (result.completion_pre - p6_fin).total_seconds() / 86400, 1)
        result.warnings.append(
            f"Calibration: this engine's pre-impact completion "
            f"({result.completion_pre:%Y-%m-%d}) differs from P6's own "
            f"scheduled finish ({p6_fin:%Y-%m-%d}) by "
            f"{result.calibration_days:+.0f} days — the approximation "
            "error of the simplified CPM. Judge the IMPACT (delta), not "
            "the absolute dates, and confirm in P6."
        )
    if (result.completion_delta_days is not None
            and result.completion_delta_days <= 0 and fragnet):
        chain_fins = [EF1[f.act_id] for f in fragnet if f.act_id in EF1]
        detail = ""
        if chain_fins and result.completion_pre:
            headroom = (result.completion_pre
                        - max(chain_fins)).total_seconds() / 86400
            detail = (f" The event chain finishes "
                      f"{max(chain_fins):%Y-%m-%d}, "
                      f"{headroom:.0f} days before pre-impact completion "
                      f"({result.completion_pre:%Y-%m-%d}) — the delay "
                      "is absorbed by that headroom. A longer chain, a "
                      "later start, or a tighter tie-in would surface an "
                      "impact.")
        result.warnings.append(
            "Favourable/neutral: the fragnet as modelled does not move "
            "forecast completion — the impacted path carries float, or "
            "the event ties into non-critical work." + detail
        )
    return result


# --------------------------------------------------------------------------- #
# AI fragnet draft — prompt + strict parser (no API calls here)
# --------------------------------------------------------------------------- #

FRAGNET_SYSTEM_PROMPT = (
    "You are a senior construction planning engineer drafting a TIA "
    "fragnet per AACE RP 52R-06: model the event with the FEWEST "
    "activities practical, with durations as reasonable forecasts. You return ONLY valid JSON — no commentary, no fences. You "
    "never invent activity IDs for the existing programme: you may only "
    "reference the candidate activities you are given. Durations must "
    "come from the comparable activities where possible; anything else "
    "must be labelled an assumption."
)

LOGIC_SYSTEM_PROMPT = (
    "You are a senior construction planning engineer recommending TIA "
    "network tie-ins. Return ONLY valid JSON. Prefer logic patterns and "
    "activities in the supplied programme. Never invent an existing "
    "activity ID. Treat responsibility as asserted, not determined. "
    "Recommendations are drafts requiring planner confirmation."
)


def build_logic_recommendation_prompt(
    event: DelayEvent,
    fragnet: list[FragnetActivity],
    data: XerData,
    templates: list[dict] | None = None,
) -> str:
    """Ask the session AI to rank network tie-ins and impacted sections."""
    templates = templates or find_template_activities(
        data, f"{event.title} {event.description} {event.work_package}", 15)
    config = DCMAConfig()
    candidates = []
    for task in data.tasks:
        if task.is_loe_or_wbs or not task.is_incomplete:
            continue
        tf = task.total_float_days(data.hours_per_day(task, config))
        candidates.append((tf if tf is not None else 99999, task))
    candidates.sort(key=lambda item: item[0])
    lines = [
        "<task>Recommend possible predecessor tie-ins, successor tie-ins, "
        "and potentially impacted sections or milestones for the confirmed "
        "fragnet. Rank alternatives; do not insert or approve logic.</task>",
        f"<event>{event.event_id}: {event.title}; {event.description}; "
        f"area={event.area or 'unknown'}; discipline={event.discipline or 'unknown'}; "
        f"work_package={event.work_package or 'unknown'}</event>",
        "<confirmed_fragnet>",
    ]
    for f in fragnet:
        lines.append(
            f"- {f.act_id} '{f.name}' {f.duration_days:g}d; "
            f"current predecessors={links_to_text(f.predecessors) or 'none'}; "
            f"current successors={links_to_text(f.successors) or 'none'}")
    lines += ["</confirmed_fragnet>", "<comparable_project_activities>"]
    for item in templates[:15]:
        lines.append(f"- {item['code']} '{item['name']}'")
    lines += ["</comparable_project_activities>",
              "<allowed_existing_activities>"]
    for _, task in candidates[:80]:
        marker = " MILESTONE" if task.is_milestone else ""
        lines.append(f"- {task.task_code} '{task.name}'{marker}")
    lines += [
        "</allowed_existing_activities>",
        '<output>Return ONLY JSON: {"predecessors":[{"id":"A100",'
        '"type":"FS","lag_days":0,"rationale":"...","confidence":"high"}],'
        '"successors":[...],"impacted_sections":[{"id":"M100",'
        '"rationale":"...","confidence":"medium"}],'
        '"warnings":["..."]}. Use only IDs in allowed_existing_activities. '
        "Provide up to five ranked candidates in each list. If no reliable "
        "project analogue exists, state that in warnings and label inferred "
        "recommendations low confidence.</output>",
    ]
    return "\n".join(lines)


def parse_logic_recommendation_json(text: str, data: XerData) -> dict:
    """Strict parser: removes every invented programme activity ID."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        obj = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return {}
    if not isinstance(obj, dict):
        return {}
    existing = {t.task_code for t in data.tasks}

    def clean_items(key: str, links: bool) -> list[dict]:
        out = []
        for item in obj.get(key, []) or []:
            if not isinstance(item, dict):
                continue
            activity_id = str(item.get("id", "")).strip()
            if activity_id not in existing:
                continue
            row = {
                "id": activity_id,
                "rationale": str(item.get("rationale", ""))[:400],
                "confidence": str(item.get("confidence", "low")).lower(),
            }
            if links:
                link_type = str(item.get("type", "FS")).upper()
                row["type"] = link_type if link_type in LINK_TYPES else "FS"
                try:
                    row["lag_days"] = float(item.get("lag_days", 0) or 0)
                except (TypeError, ValueError):
                    row["lag_days"] = 0.0
            out.append(row)
        return out[:5]

    return {
        "predecessors": clean_items("predecessors", True),
        "successors": clean_items("successors", True),
        "impacted_sections": clean_items("impacted_sections", False),
        "warnings": [str(w)[:400] for w in obj.get("warnings", [])
                     if isinstance(w, str)][:10],
    }


def build_fragnet_prompt(
    event: DelayEvent,
    templates: list[dict],
    data: XerData,
    max_candidates: int = 40,
) -> str:
    """Ask the model to draft ONE realistic fragnet, evidence-first."""
    config = DCMAConfig()
    scope = assess_event_scope(event)
    packages = find_template_work_packages(
        data, f"{event.title} {event.description} {event.work_package}")
    cands = []
    for t in data.tasks:
        if t.is_loe_or_wbs or not t.is_incomplete:
            continue
        hpd = data.hours_per_day(t, config)
        tf = t.total_float_days(hpd)
        cands.append((tf if tf is not None else 9999, t))
    cands.sort(key=lambda x: x[0])
    lines = [
        "<task>Draft a REALISTIC fragnet representing this delay event, "
        "for insertion into the current programme. Include normal design/"
        "approval/procurement/execution steps only where the event "
        "description supports them.</task>",
        "",
        f"<event id='{event.event_id}'>",
        f"Title: {event.title}",
        f"Description: {event.description}",
        f"Area: {event.area or 'not established'}",
        f"Discipline: {event.discipline or 'not established'}",
        f"Project context: {event.project_context or 'not established'}",
        f"Work package: {event.work_package or 'not established'}",
        f"Date raised: "
        f"{event.date_raised:%Y-%m-%d}" if event.date_raised else "",
        "</event>", "",
        "<scope_assessment>This is a retrieval brief, not established fact:",
        f"Work nature: {scope.work_nature}",
        "Potential lifecycle stages: " + ", ".join(scope.lifecycle_stages),
        "Potential enabling requirements: "
        + (", ".join(scope.enabling_requirements) or "none identified"),
        "Unanswered questions: "
        + ("; ".join(scope.unanswered_questions) or "none"),
        "</scope_assessment>", "",
        "<work_package_candidates>Prefer cloning/adapting one of these "
        "project-specific packages before inventing a generic sequence:",
    ]
    for package in packages:
        lines.append(
            f"- WBS {package['wbs_id']} '{package['wbs_name']}' "
            f"({package['activity_count']} activities; matched "
            f"{package['matched'] or 'event terms'})")
        for act in package["activities"][:12]:
            dur = (f"{act['duration_days']:.0f}d"
                   if act.get("duration_days") is not None else "?")
            lines.append(f"  · {act['code']} '{act['name']}' [{dur}]")
    lines += [
        "</work_package_candidates>", "",
        "<allowed_calendars>Use only these calendar IDs:",
    ]
    for calendar_id, calendar in data.calendars.items():
        lines.append(f"- {calendar_id}: {calendar.name} "
                     f"({calendar.day_hr_cnt:g} hours/day)")
    lines += [
        "</allowed_calendars>", "",
        "<comparable_activities>These existing activities matched the "
        "event text — use their durations as the evidence base:",
    ]
    for tpl in templates[:12]:
        d = (f"{tpl['duration_days']:.0f}d"
             if tpl.get("duration_days") is not None else "?")
        lines.append(f"- {tpl['code']} '{tpl['name']}' [{d}]")
    lines += ["</comparable_activities>", "",
              "<tie_in_candidates>Incomplete activities you may reference "
              "as predecessors/successors (lowest float first):"]
    for _, t in cands[:max_candidates]:
        lines.append(f"- {t.task_code} '{t.name}'"
                     + (" [MILESTONE]" if t.is_milestone else ""))
    lines += [
        "</tie_in_candidates>", "",
        '<output>Return ONLY JSON: {"activities": [{"id": "TIA-010", '
        '"name": "...", "duration_days": N, '
        '"calendar_id": "existing calendar id", '
        '"predecessors": [{"id": "...", "type": "FS", "lag_days": 0}], '
        '"successors": [{"id": "...", "type": "FS", "lag_days": 0}], '
        '"rationale": "duration from <code> / logic because ...", '
        '"assumptions": "..." }]}. '
        "Fragnet ids must start with 'TIA-'. Every predecessor/successor "
        "id must be a TIA- id or one of the tie-in candidates. At least "
        "one successor must tie back into the existing network. Use the "
        "fewest activities practical, but retain the necessary work-package "
        "sequence; do not exceed 12 activities without explaining why.</output>",
        "<reasoning_rules>Prefer project-specific work-package sequence, "
        "WBS placement and comparable durations. Add design, approval, "
        "procurement, access, temporary works, testing or commissioning "
        "only when evidenced or explicitly labelled as an assumption. "
        "Explain predecessor and successor tie-ins. Generic AI knowledge "
        "is a last resort and must be labelled low confidence.</reasoning_rules>",
    ]
    return "\n".join(x for x in lines if x is not None)


def parse_fragnet_json(
    text: str, data: XerData,
) -> list[FragnetActivity]:
    """Strictly parse the model's fragnet; drop anything invalid."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return []
    try:
        obj = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return []
    items = obj.get("activities") if isinstance(obj, dict) else None
    if not isinstance(items, list):
        return []
    existing = {t.task_code for t in data.tasks}
    frag_ids = {str(i.get("id", "")).strip() for i in items
                if isinstance(i, dict)}
    known = existing | frag_ids
    out: list[FragnetActivity] = []
    for i in items:
        if not isinstance(i, dict):
            continue
        fid = str(i.get("id", "")).strip()
        if not fid.upper().startswith("TIA-") or fid in existing:
            continue
        try:
            dur = float(i.get("duration_days", 0))
        except (TypeError, ValueError):
            dur = 0.0

        def _links(key):
            links = []
            for l in i.get(key, []) or []:
                if not isinstance(l, dict):
                    continue
                oid = str(l.get("id", "")).strip()
                if oid not in known:
                    continue
                lt = str(l.get("type", "FS")).upper()
                try:
                    lag = float(l.get("lag_days", 0) or 0)
                except (TypeError, ValueError):
                    lag = 0.0
                links.append(FragnetLink(
                    oid, lt if lt in LINK_TYPES else "FS", lag))
            return links

        out.append(FragnetActivity(
            act_id=fid, name=str(i.get("name", ""))[:120],
            duration_days=max(dur, 0.0),
            predecessors=_links("predecessors"),
            successors=_links("successors"),
            rationale=str(i.get("rationale", ""))[:300],
            assumptions=str(i.get("assumptions", ""))[:300],
            confidence="medium",
            calendar_id=(str(i.get("calendar_id", "")).strip()
                         if str(i.get("calendar_id", "")).strip()
                         in data.calendars else "")))
    return out


# --------------------------------------------------------------------------- #
# Event register — save / load events with their confirmed fragnets
# --------------------------------------------------------------------------- #

def event_to_dict(event: DelayEvent, fragnet: list[FragnetActivity],
                  result: "TIAResult | None" = None) -> dict:
    """JSON-safe record of one event + its confirmed fragnet (+ outcome)."""
    rec = {
        "version": 1,
        "event": {
            "event_id": event.event_id, "title": event.title,
            "description": event.description,
            "date_raised": (event.date_raised.strftime("%Y-%m-%d")
                            if event.date_raised else None),
            "responsibility_asserted": event.responsibility_asserted,
            "evidence_note": event.evidence_note,
            "area": event.area, "discipline": event.discipline,
            "project_context": event.project_context,
            "work_package": event.work_package,
        },
        "fragnet": [{
            "id": f.act_id, "name": f.name,
            "duration_days": f.duration_days,
            "predecessors": [{"id": l.other_id, "type": l.link_type,
                              "lag_days": l.lag_days}
                             for l in f.predecessors],
            "successors": [{"id": l.other_id, "type": l.link_type,
                            "lag_days": l.lag_days}
                           for l in f.successors],
            "rationale": f.rationale, "assumptions": f.assumptions,
            "confidence": f.confidence,
            "calendar_id": f.calendar_id,
        } for f in fragnet],
    }
    if result is not None and result.completion_delta_days is not None:
        rec["last_result"] = {
            "programme": result.programme_label,
            "completion_delta_days": result.completion_delta_days,
            "completion_post": (result.completion_post.strftime("%Y-%m-%d")
                                if result.completion_post else None),
        }
    return rec


def event_from_dict(rec: dict) -> tuple[DelayEvent,
                                        list[FragnetActivity]] | None:
    """Validate + rebuild an event record; None if malformed."""
    try:
        e = rec["event"]
        date = (datetime.strptime(e["date_raised"], "%Y-%m-%d")
                if e.get("date_raised") else None)
        event = DelayEvent(
            str(e["event_id"]), str(e.get("title", "")),
            str(e.get("description", "")), date,
            str(e.get("responsibility_asserted", "")),
            str(e.get("evidence_note", "")),
            str(e.get("area", "")), str(e.get("discipline", "")),
            str(e.get("project_context", "")),
            str(e.get("work_package", "")))
        fragnet = []
        for f in rec.get("fragnet", []):
            def _ls(key):
                return [FragnetLink(str(l["id"]),
                                    str(l.get("type", "FS")).upper()
                                    if str(l.get("type", "FS")).upper()
                                    in LINK_TYPES else "FS",
                                    float(l.get("lag_days", 0) or 0))
                        for l in f.get(key, []) if l.get("id")]
            fragnet.append(FragnetActivity(
                act_id=str(f["id"]), name=str(f.get("name", "")),
                duration_days=float(f.get("duration_days", 0) or 0),
                predecessors=_ls("predecessors"),
                successors=_ls("successors"),
                rationale=str(f.get("rationale", "")),
                assumptions=str(f.get("assumptions", "")),
                confidence=str(f.get("confidence", "medium")),
                calendar_id=str(f.get("calendar_id", ""))))
        return event, fragnet
    except (KeyError, TypeError, ValueError):
        return None


def register_to_json(records: list[dict]) -> str:
    return json.dumps({"version": 1, "events": records}, indent=2)


def register_from_json(text: str) -> list[dict]:
    """Parse a register file; silently drops malformed event records."""
    try:
        obj = json.loads(text)
        events = obj.get("events", [])
    except (json.JSONDecodeError, AttributeError):
        return []
    return [r for r in events
            if isinstance(r, dict) and event_from_dict(r) is not None]


# --------------------------------------------------------------------------- #
# Fragnet draft variants (spec step 8) — one prompt, three disciplines
# --------------------------------------------------------------------------- #

FRAGNET_VARIANTS = {
    "minimal": (
        "Draft a MINIMAL-IMPACT fragnet: include ONLY the activities "
        "strictly necessary to represent the event itself — no allowances, "
        "no optional interfaces. Typically 1-3 activities."
    ),
    "realistic": (
        "Draft a REALISTIC construction fragnet: include the normal "
        "design, approval, procurement, enabling, execution, and "
        "inspection steps ONLY where the event description and the "
        "comparable activities support them."
    ),
    "conservative": (
        "Draft a CONSERVATIVE fragnet: you may include additional risk or "
        "interface activities where justifiable, but EVERY such allowance "
        "must state in its 'assumptions' field that it is an allowance, "
        "not an evidenced fact. Do not inflate durations to manufacture "
        "an outcome."
    ),
}


def build_fragnet_variant_prompt(
    event: DelayEvent, templates: list[dict], data: XerData,
    variant: str = "realistic",
) -> str:
    base = build_fragnet_prompt(event, templates, data)
    instruction = FRAGNET_VARIANTS.get(variant,
                                       FRAGNET_VARIANTS["realistic"])
    return base.replace(
        "<task>Draft a REALISTIC fragnet representing this delay event, "
        "for insertion into the current programme. Include normal design/"
        "approval/procurement/execution steps only where the event "
        "description supports them.</task>",
        f"<task>{instruction} The fragnet is for insertion into the "
        "current programme.</task>")
