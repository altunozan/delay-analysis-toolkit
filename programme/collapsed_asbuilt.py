"""Collapsed As-Built (but-for) analysis.

Only requires the as-built programme. The as-built model is UNSTATUSED
(actual durations kept, actual dates released), rescheduled to validate
it reproduces the as-built completion, then the analyst-confirmed event
activities are removed (zero duration) and the model rescheduled again:
where the programme "collapses" back to is the but-for completion, and
the difference is the delay attributable to the extracted events.

The candidate-event grouping step may be AI-assisted (names / WBS /
activity codes -> proposed groups), but the extraction set is ALWAYS
analyst-confirmed and the collapse arithmetic is fully deterministic.

Pure engine + prompt/parse helpers. The LLM only proposes groupings of
verbatim activity codes; codes not present in the file are dropped.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from dcma.config import DCMAConfig
from dcma.xer_parser import XerData

CAB_CAVEATS = [
    "Collapsed as-built is a retrospective BUT-FOR model: the as-built "
    "programme is unstatused (actual durations kept, actual dates "
    "released), the extracted event activities are removed, and the "
    "model is rescheduled. Its central assumption — that without the "
    "extracted events the works would have proceeded in the same "
    "sequence at the same durations — is the method's classic point of "
    "attack; disclose it and test the collapsed sequence for realism.",
    "The as-built logic is CONSTRUCTED, not contemporaneous: the model "
    "uses the file's relationships as they stand (repair out-of-"
    "sequence logic first — see the OOS module — or the collapse can "
    "be distorted by links the works did not follow).",
    "Durations are the recorded ACTUAL durations in calendar days "
    "(finish minus start of the recorded actuals); activities never "
    "started are excluded and disclosed. Calendar working patterns are "
    "not re-applied to the collapsed model — the collapse is measured "
    "in calendar days on both runs, so the DELTA is like-for-like.",
    "Model validation is disclosed: the unstatused model's completion "
    "is compared against the recorded as-built completion before any "
    "collapse; a large gap means the file's logic does not explain its "
    "own actual dates and the collapse should not be relied on.",
    "AI-assisted grouping only PROPOSES candidate event activities from "
    "names / WBS / activity codes; the analyst confirms every code in "
    "the extraction set, and the arithmetic never involves the model.",
]


@dataclass
class CabActivity:
    task_code: str
    name: str
    start: datetime | None          # modelled (unstatused) start
    finish: datetime | None
    duration_days: float
    removed: bool = False


@dataclass
class CollapseResult:
    label: str = ""
    asbuilt_completion: datetime | None = None      # recorded (max AF)
    model_completion: datetime | None = None        # unstatused model
    collapsed_completion: datetime | None = None    # after extraction
    delta_days: float | None = None                 # model - collapsed
    calibration_days: float | None = None           # model vs recorded
    removed_codes: list[str] = field(default_factory=list)
    n_modelled: int = 0
    n_excluded_unstarted: int = 0
    critical_chain: list[CabActivity] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


_REL_LABEL = {"PR_FS": "FS", "PR_SS": "SS", "PR_FF": "FF", "PR_SF": "SF"}


def _actual_span_days(t, dd: datetime | None,
                      hpd: float) -> float | None:
    """Actual duration in calendar days; in-progress uses to-date +
    remaining converted at hours-per-day."""
    if t.act_start is None:
        return None
    if t.act_finish is not None:
        return max((t.act_finish - t.act_start).total_seconds() / 86400.0,
                   0.0)
    to_date = (max((dd - t.act_start).total_seconds() / 86400.0, 0.0)
               if dd else 0.0)
    remain = (t.remain_dur_hr / hpd
              if getattr(t, "remain_dur_hr", None) else 0.0)
    return to_date + remain


def _schedule(nodes: dict[str, float],
              rels: list[tuple[str, str, str, float]],
              anchor: datetime) -> tuple[dict, dict]:
    """Calendar-day forward pass honouring FS/SS/FF/SF (lags in days).

    Iterative relaxation with a pass cap — P6 networks are acyclic, but
    a cap keeps a malformed file from hanging the engine."""
    ES = {c: anchor for c in nodes}
    EF = {c: anchor + timedelta(days=d) for c, d in nodes.items()}
    for _ in range(len(nodes) + 50):
        changed = False
        for pred, succ, lt, lag in rels:
            if pred not in nodes or succ not in nodes:
                continue
            lagd = timedelta(days=lag)
            if lt == "SS":
                bound = ES[pred] + lagd
            elif lt == "FF":
                bound = EF[pred] + lagd - timedelta(days=nodes[succ])
            elif lt == "SF":
                bound = ES[pred] + lagd - timedelta(days=nodes[succ])
            else:                                   # FS
                bound = EF[pred] + lagd
            if bound > ES[succ]:
                ES[succ] = bound
                EF[succ] = bound + timedelta(days=nodes[succ])
                changed = True
        if not changed:
            break
    return ES, EF


def collapse_asbuilt(
    data: XerData,
    label: str,
    remove_codes: set[str],
    *,
    config: DCMAConfig | None = None,
) -> CollapseResult:
    """Unstatus, validate, extract, reschedule, measure."""
    config = config or DCMAConfig()
    result = CollapseResult(label=label, caveats=list(CAB_CAVEATS))
    dd = data.project.data_date if data.project else None

    started = [t for t in data.tasks
               if not t.is_loe_or_wbs and t.act_start is not None]
    unstarted = sum(1 for t in data.tasks
                    if not t.is_loe_or_wbs and t.act_start is None)
    result.n_excluded_unstarted = unstarted
    if not started:
        result.warnings.append("No activities with recorded actual "
                               "starts — nothing to model.")
        return result

    nodes: dict[str, float] = {}
    id_to_code: dict[str, str] = {}
    for t in started:
        hpd = data.hours_per_day(t, config)
        dur = _actual_span_days(t, dd, hpd)
        nodes[t.task_code] = dur or 0.0
        id_to_code[t.task_id] = t.task_code
    result.n_modelled = len(nodes)
    result.asbuilt_completion = max(
        (t.act_finish for t in started if t.act_finish), default=None)

    by_task_id = {t.task_id: t for t in started}
    rels: list[tuple[str, str, str, float]] = []
    for r in data.relationships:
        p, s = id_to_code.get(r.pred_task_id), id_to_code.get(r.task_id)
        if p and s:
            # lag hours -> calendar days at the successor's calendar
            # hours-per-day (matches how the OOS repair encodes lags)
            hpd_s = data.hours_per_day(by_task_id[r.task_id], config)
            lag_days = ((r.lag_hr or 0.0) / hpd_s) if r.lag_hr else 0.0
            rels.append((p, s, _REL_LABEL.get(r.pred_type, "FS"),
                         lag_days))
    anchor = min(t.act_start for t in started)

    # ---- run 1: unstatused as-built model (validation) -----------------
    _, EF1 = _schedule(dict(nodes), rels, anchor)
    result.model_completion = max(EF1.values()) if EF1 else None
    if result.model_completion and result.asbuilt_completion:
        result.calibration_days = round(
            (result.model_completion
             - result.asbuilt_completion).total_seconds() / 86400.0, 1)
        if abs(result.calibration_days) > 30:
            result.warnings.append(
                f"Model validation gap of {result.calibration_days:+.0f} "
                "calendar days between the unstatused model's completion "
                "and the recorded as-built completion — the file's logic "
                "does not reproduce its own actual dates at this scale. "
                "Repair out-of-sequence logic first (OOS module) or "
                "treat the collapse as unreliable.")

    # ---- run 2: collapsed (extracted activities at zero duration) ------
    missing = sorted(c for c in remove_codes if c not in nodes)
    if missing:
        result.warnings.append(
            f"{len(missing)} extraction code(s) are not in the modelled "
            "population (unstarted or not in the file) and were ignored: "
            + ", ".join(missing[:5])
            + (" …" if len(missing) > 5 else ""))
    result.removed_codes = sorted(c for c in remove_codes if c in nodes)
    collapsed_nodes = dict(nodes)
    for c in result.removed_codes:
        collapsed_nodes[c] = 0.0
    ES2, EF2 = _schedule(collapsed_nodes, rels, anchor)
    result.collapsed_completion = max(EF2.values()) if EF2 else None
    if result.model_completion and result.collapsed_completion:
        result.delta_days = round(
            (result.model_completion
             - result.collapsed_completion).total_seconds() / 86400.0, 1)

    # ---- collapsed model's controlling chain (for realism review) ------
    if EF2:
        by_code = {t.task_code: t for t in started}
        end = max(EF2, key=lambda c: EF2[c])
        chain, seen = [], set()
        cur = end
        preds_of: dict[str, list[tuple[str, str, float]]] = {}
        for p, s, lt, lag in rels:
            preds_of.setdefault(s, []).append((p, lt, lag))
        while cur and cur not in seen and len(chain) < 200:
            seen.add(cur)
            t = by_code[cur]
            chain.append(CabActivity(
                cur, t.name, ES2.get(cur), EF2.get(cur),
                collapsed_nodes.get(cur, 0.0),
                removed=cur in set(result.removed_codes)))
            best, best_gap = None, timedelta(days=0.51)
            for p, lt, lag in preds_of.get(cur, []):
                bound = (ES2[p] if lt in ("SS", "SF") else EF2[p])
                gap = ES2[cur] - bound
                if timedelta(days=-0.01) <= gap < best_gap:
                    best, best_gap = p, gap
            cur = best
        result.critical_chain = list(reversed(chain))
    return result


# --------------------------------------------------------------------------- #
# AI-assisted candidate grouping (proposal only; analyst confirms)
# --------------------------------------------------------------------------- #

GROUPING_SYSTEM_PROMPT = (
    "You are assisting a forensic delay analyst. You will receive a list "
    "of as-built activities (code, name, optional WBS/activity-code "
    "labels). Group activities that plausibly form DISCRETE DELAY "
    "EVENTS suitable for extraction in a collapsed as-built analysis — "
    "e.g. approval/review cycles, variations, remedial or rework "
    "chains, suspension periods. Use ONLY the codes provided, verbatim. "
    "Return STRICT JSON: {\"groups\": [{\"label\": str, \"codes\": "
    "[str], \"rationale\": str}]} and nothing else. Propose at most 12 "
    "groups; leave out activities that are ordinary works.")


def build_grouping_prompt(data: XerData, *, limit: int = 800) -> str:
    started = [t for t in data.tasks
               if not t.is_loe_or_wbs and t.act_start is not None]
    started.sort(key=lambda t: t.act_start)
    lines = [f"{t.task_code}\t{t.name}" for t in started[:limit]]
    note = ("" if len(started) <= limit
            else f"\n(NOTE: first {limit} of {len(started)} shown)")
    return ("Activities (code<TAB>name), in actual-start order:\n"
            + "\n".join(lines) + note)


def parse_grouping(text: str, data: XerData) -> tuple[list[dict], int]:
    """Parse the LLM's JSON; drop codes not verbatim in the file."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return [], 0
    try:
        payload = json.loads(m.group(0))
    except json.JSONDecodeError:
        return [], 0
    valid = {t.task_code for t in data.tasks if not t.is_loe_or_wbs}
    groups, dropped = [], 0
    for g in payload.get("groups", []):
        codes = [c for c in g.get("codes", []) if c in valid]
        dropped += len(g.get("codes", [])) - len(codes)
        if codes:
            groups.append({"label": str(g.get("label", "group")),
                           "codes": codes,
                           "rationale": str(g.get("rationale", ""))})
    return groups, dropped
