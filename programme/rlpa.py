"""Retrospective longest path with analyst-logic (inferred) links.

The programme's recorded network misses dependencies a delay analyst
would find on inspection — blockwork closing a zone before first-fix
electrical can progress, with no link ever drawn between them. This
module lets the AI PROPOSE such links, under hard deterministic rails:

1. The engine screens every unlinked completed pair first. The AI only
   ever chooses from that pre-screened list — it cannot invent
   activities, dates or pairs that failed the screen.
2. The same question is asked ``runs`` times independently. Votes map
   to a WORD, never a number: proposed in every run = strong, in a
   majority = medium, once = poor. Poor links are excluded from the
   path unless the trace cannot stay continuous without them, and are
   always disclosed.
3. The longest path is then re-derived DETERMINISTICALLY over the
   recorded network plus the adopted inferred links, by the same
   as-built walk the toolkit already uses. Up to three path options
   are kept (strong-only / strong+medium / plus poor-if-needed).

Inferred links are analyst-proposed OPINION evidence, never programme
fact; every output row says which it is.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime

from dcma.calendar import calendar_masks, working_days_between
from dcma.models import Relationship
from dcma.xer_parser import XerData

from .asbuilt_path import ActualTraceResult, extract_asbuilt_longest_path

CONFIDENCE_WORDS = ("strong", "medium", "poor")

RLPA_CAVEATS = [
    "Inferred links are ANALYST-PROPOSED logic: the AI selected them "
    "from a deterministically screened list of unlinked pairs, with its "
    "reasoning recorded. They are opinion evidence for review, never "
    "programme fact, and every one is labelled INFERRED wherever it "
    "appears.",
    "Confidence is stated in words (strong / medium / poor) from "
    "agreement across independent AI runs plus the deterministic "
    "screen. It is not a probability and is never expressed as a "
    "number.",
    "The longest path itself is derived deterministically over the "
    "recorded network plus the adopted inferred links — the AI never "
    "chooses the path, only proposes candidate logic.",
    "This page determines the retrospective longest path; delay "
    "quantum is measured in steps ②-④ exactly as in the As-Planned vs "
    "As-Built method (window intervals), not by the inference.",
]

# work types that can plausibly precede one another; mirrors the
# deterministic classifier used across the toolkit
_WORK_ORDER = {
    "procure": 1, "deliver": 2, "mobilis": 2,
    "excavat": 3, "foundation": 3, "structur": 3, "blockwork": 4,
    "construct": 4, "erect": 4, "install": 5, "first fix": 5,
    "second fix": 6, "finish": 6, "inspect": 7, "test": 7,
    "energis": 8, "commission": 8, "snag": 9, "handover": 9,
    "training": 9, "completion": 10,
}

_INTERFACE_TOKENS = ("release", "access", "approval", "permit",
                     "handover", "energis", "possession")


def _work_rank(name: str) -> int | None:
    lowered = name.lower()
    for token, rank in _WORK_ORDER.items():
        if token in lowered:
            return rank
    return None


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower())
            if len(w) > 2}


@dataclass
class CandidatePair:
    """One unlinked pair that survived the deterministic screen."""
    pred_code: str
    pred_name: str
    pred_finish: datetime
    succ_code: str
    succ_name: str
    succ_start: datetime
    gap_working_days: float
    shared_context: str          # why the screen kept it


@dataclass
class InferredLink:
    pred_code: str
    succ_code: str
    votes: int
    runs: int
    confidence: str              # strong | medium | poor
    reasons: list[str] = field(default_factory=list)


@dataclass
class RLPAResult:
    candidates: list[CandidatePair] = field(default_factory=list)
    links: list[InferredLink] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)   # verbatim failures
    # up to three (label, basis_note, trace) options, main first
    options: list[tuple[str, str, ActualTraceResult]] = \
        field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


def screen_missing_links(
    data: XerData,
    *,
    max_gap_working_days: float = 30.0,
    max_pairs: int = 120,
    max_per_successor: int = 4,
) -> list[CandidatePair]:
    """Deterministic screen: unlinked completed pairs the AI may consider.

    Gates, all binary: no recorded relationship either way (direct);
    the predecessor's actual finish precedes the successor's actual
    start; the working-day gap on the successor's calendar is within
    the window; the pair shares naming/WBS context (or the predecessor
    is an interface-type activity); the work-type order is not
    physically backwards.
    """
    tasks = [t for t in data.tasks
             if not t.is_loe_or_wbs and t.act_start and t.act_finish]
    linked: set[tuple[str, str]] = set()
    ids = {t.task_id: t.task_code for t in data.tasks}
    for rel in data.relationships:
        p, s = ids.get(rel.pred_task_id), ids.get(rel.task_id)
        if p and s:
            linked.add((p, s))
            linked.add((s, p))
    masks = calendar_masks(data)
    finished = sorted(tasks, key=lambda t: t.act_finish)
    out: list[CandidatePair] = []
    per_succ: dict[str, int] = {}
    for succ in sorted(tasks, key=lambda t: t.act_start):
        succ_tokens = _tokens(succ.name)
        succ_rank = _work_rank(succ.name)
        for pred in finished:
            if pred.task_id == succ.task_id:
                continue
            if pred.act_finish > succ.act_start:
                continue
            if (pred.task_code, succ.task_code) in linked:
                continue
            if per_succ.get(succ.task_code, 0) >= max_per_successor:
                break
            gap = working_days_between(
                pred.act_finish, succ.act_start, masks.get(succ.clndr_id))
            if gap > max_gap_working_days:
                continue
            shared = succ_tokens & _tokens(pred.name)
            interface = any(tok in pred.name.lower()
                            for tok in _INTERFACE_TOKENS)
            prefix = (pred.task_code.split("-")[0]
                      == succ.task_code.split("-")[0])
            if not (shared or interface or prefix):
                continue
            pred_rank = _work_rank(pred.name)
            if (pred_rank is not None and succ_rank is not None
                    and pred_rank > succ_rank):
                continue
            context = (("shared: " + ", ".join(sorted(shared)[:3]))
                       if shared else
                       "interface activity" if interface else
                       "same work area prefix")
            out.append(CandidatePair(
                pred_code=pred.task_code, pred_name=pred.name,
                pred_finish=pred.act_finish,
                succ_code=succ.task_code, succ_name=succ.name,
                succ_start=succ.act_start,
                gap_working_days=round(gap, 1),
                shared_context=context,
            ))
            per_succ[succ.task_code] = per_succ.get(succ.task_code, 0) + 1
    out.sort(key=lambda c: c.gap_working_days)
    return out[:max_pairs]


def build_inference_prompt(pairs: list[CandidatePair],
                           max_links: int = 12) -> str:
    """One AI pass: pick the pairs a delay analyst would call REAL
    dependencies. Strict JSON, choices only from the supplied list."""
    lines = [
        f"{c.pred_code} | {c.pred_name} | finished "
        f"{c.pred_finish:%Y-%m-%d} ->> {c.succ_code} | {c.succ_name} | "
        f"started {c.succ_start:%Y-%m-%d} | gap {c.gap_working_days} "
        f"working days | {c.shared_context}"
        for c in pairs
    ]
    return (
        "You are a forensic delay analyst reviewing an as-built "
        "construction programme. Each line below is a PAIR of completed "
        "activities with NO relationship recorded in the programme, "
        "where the first finished before the second started. Select "
        "only the pairs where the second activity physically or "
        "procedurally COULD NOT have progressed until the first was "
        "complete (e.g. first-fix electrical cannot proceed in a zone "
        "until blockwork closes it; testing cannot precede "
        "installation; an approval releases the work behind it). "
        "Reject pairs that are merely date-adjacent, resource-driven "
        "or coincidental.\n\n"
        "Rules: choose ONLY from the list; at most "
        f"{max_links} pairs; one short physical/procedural reason "
        "each; NO probabilities or percentages; respond with JSON "
        "ONLY, exactly this shape:\n"
        '{"links":[{"pred":"<ID>","succ":"<ID>","reason":"<why>"}]}\n\n'
        "PAIRS:\n" + "\n".join(lines)
    )


def parse_inference(text: str,
                    pairs: list[CandidatePair],
                    ) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Verbatim-verified parse: only pairs from the screened list
    survive; everything else is recorded as rejected, never used."""
    allowed = {(c.pred_code, c.succ_code) for c in pairs}
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return [], ["response carried no JSON object"]
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return [], ["response JSON did not parse"]
    accepted: list[tuple[str, str, str]] = []
    rejected: list[str] = []
    seen: set[tuple[str, str]] = set()
    for item in payload.get("links", []) or []:
        if not isinstance(item, dict):
            continue
        pred = str(item.get("pred", "")).strip()
        succ = str(item.get("succ", "")).strip()
        reason = " ".join(str(item.get("reason", "")).split())[:200]
        if (pred, succ) in seen:
            continue
        seen.add((pred, succ))
        if (pred, succ) in allowed:
            accepted.append((pred, succ, reason))
        else:
            rejected.append(f"{pred} → {succ}: not in the screened "
                            "candidate list — discarded")
    return accepted, rejected


def aggregate_votes(runs: list[list[tuple[str, str, str]]],
                    ) -> list[InferredLink]:
    """Self-consistency vote across independent runs → confidence WORD.

    Proposed in every run = strong; in a majority = medium; otherwise
    poor. No arithmetic ever reaches the output beyond the vote count
    itself, which is disclosed as n-of-m.
    """
    total = len(runs)
    tally: dict[tuple[str, str], InferredLink] = {}
    for run in runs:
        for pred, succ, reason in run:
            link = tally.setdefault((pred, succ), InferredLink(
                pred_code=pred, succ_code=succ,
                votes=0, runs=total, confidence="poor"))
            link.votes += 1
            if reason and reason not in link.reasons:
                link.reasons.append(reason)
    for link in tally.values():
        if link.votes == total and total > 1:
            link.confidence = "strong"
        elif link.votes * 2 > total:
            link.confidence = "medium"
        else:
            link.confidence = "poor"
    return sorted(tally.values(),
                  key=lambda l: (-l.votes, l.pred_code, l.succ_code))


def _with_links(data: XerData, links: list[InferredLink]) -> XerData:
    by_code = {t.task_code: t.task_id for t in data.tasks}
    extra = [Relationship(by_code[l.pred_code], by_code[l.succ_code],
                          "PR_FS", 0.0)
             for l in links
             if l.pred_code in by_code and l.succ_code in by_code]
    return replace(data, relationships=data.relationships + extra)


def derive_paths(
    data: XerData,
    links: list[InferredLink],
    *,
    end_task_code: str | None = None,
    max_gap_days: float = 240.0,
) -> RLPAResult:
    """Up to three deterministic longest-path options over the recorded
    network plus adopted inferred links, main option first."""
    result = RLPAResult(links=links, caveats=list(RLPA_CAVEATS))
    strong = [l for l in links if l.confidence == "strong"]
    medium = [l for l in links if l.confidence == "medium"]
    poor = [l for l in links if l.confidence == "poor"]

    def _run(subset: list[InferredLink]) -> ActualTraceResult:
        return extract_asbuilt_longest_path(
            _with_links(data, subset), end_task_code=end_task_code,
            max_gap_days=max_gap_days)

    adopted = _run(strong + medium)
    options: list[tuple[str, str, ActualTraceResult]] = [(
        "Adopted — strong + medium inferred links",
        f"{len(strong)} strong + {len(medium)} medium inferred "
        "link(s) joined to the recorded network", adopted)]
    if strong or medium:
        strict = _run(strong)
        if [a.task_code for a in strict.activities] != \
                [a.task_code for a in adopted.activities]:
            options.append((
                "Strict — strong inferred links only",
                f"{len(strong)} strong inferred link(s) only; medium "
                "proposals set aside", strict))
    if poor:
        extended = _run(strong + medium + poor)
        if len(extended.activities) > len(adopted.activities):
            options.append((
                "Extended — poor links admitted for continuity only",
                f"{len(poor)} poor link(s) admitted solely because "
                "they carry the chain further back than the adopted "
                "option reaches", extended))
            result.warnings.append(
                "The extended option leans on poor-confidence links; "
                "treat every such hand-off as an open question for the "
                "factual record.")
    result.options = options[:3]
    inferred_set = {(l.pred_code, l.succ_code) for l in links}
    for _, _, trace in result.options:
        for lk in trace.links:
            if (lk.pred_code, lk.succ_code) in inferred_set:
                lk.kind = "inferred"
    return result


def path_idle_gaps(trace: ActualTraceResult, data: XerData,
                   top: int = 5) -> list[dict]:
    """The largest working-day hand-off gaps along the chain — often
    the finding itself (the workfront stood idle)."""
    masks = calendar_masks(data)
    by_code = {t.task_code: t for t in data.tasks}
    rows = []
    for prev, cur in zip(trace.activities, trace.activities[1:]):
        if not (prev.act_finish and cur.act_start):
            continue
        if cur.act_start <= prev.act_finish:
            continue
        succ_task = by_code.get(cur.task_code)
        gap = working_days_between(
            prev.act_finish, cur.act_start,
            masks.get(succ_task.clndr_id) if succ_task else None)
        if gap >= 1.0:
            rows.append({
                "after": f"{prev.task_code} — {prev.name[:40]}",
                "before": f"{cur.task_code} — {cur.name[:40]}",
                "from": prev.act_finish, "to": cur.act_start,
                "working_days": round(gap, 1),
            })
    rows.sort(key=lambda r: -r["working_days"])
    return rows[:top]
