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
    decision_grade: bool | None = None              # within tolerance
    removed_codes: list[str] = field(default_factory=list)
    n_modelled: int = 0
    n_excluded_unstarted: int = 0
    # Traceback: the controlling chain of BOTH runs, so the headline
    # delta is attributable — chain X (with the events) became chain Y
    # (without them), not just "the number moved".
    model_chain: list[CabActivity] = field(default_factory=list)
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
              anchor: datetime) -> tuple[dict, dict, bool]:
    """Calendar-day forward pass honouring FS/SS/FF/SF (lags in days).

    Iterative relaxation with a pass cap — P6 networks are acyclic, but
    a cap keeps a malformed file from hanging the engine.

    Returns (ES, EF, converged). (C3) A positive cycle never converges:
    the dates at the cap are a function of HOW MANY passes ran — i.e.
    of unrelated network size — so a non-converged result is
    arbitrary and the caller must SUPPRESS quantum, not present it.
    """
    ES = {c: anchor for c in nodes}
    EF = {c: anchor + timedelta(days=d) for c, d in nodes.items()}
    converged = False
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
            converged = True
            break
    return ES, EF, converged


def collapse_asbuilt(
    data: XerData,
    label: str,
    remove_codes: set[str],
    *,
    anchor_code: str | None = None,
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
            # lag basis = the file's own SCHEDOPTIONS election, via the
            # same central helper as the CPM kernel — converting with
            # the successor's h/day manufactured false calibration error
            # whenever the two calendars differed
            if r.lag_hr:
                from dcma.calendar import relationship_lag_hours_per_day
                _hpd, _ = relationship_lag_hours_per_day(
                    data, by_task_id[r.pred_task_id].clndr_id
                    if r.pred_task_id in by_task_id else "",
                    by_task_id[r.task_id].clndr_id, config)
                lag_days = r.lag_hr / _hpd
            else:
                lag_days = 0.0
            rels.append((p, s, _REL_LABEL.get(r.pred_type, "FS"),
                         lag_days))
    anchor = min(t.act_start for t in started)

    # ---- run 1: unstatused as-built model (validation) -----------------
    def _completion(EF: dict) -> "datetime | None":
        if anchor_code and anchor_code in EF:
            return EF[anchor_code]
        return max(EF.values()) if EF else None

    ES1, EF1, conv1 = _schedule(dict(nodes), rels, anchor)
    if not conv1:
        # (C3) non-convergence = a positive cycle: the dates are an
        # artefact of the pass cap and of unrelated network size.
        # QUANTUM IS SUPPRESSED — a warned-but-shown arbitrary number
        # is exactly what an audit will find.
        result.warnings.append(
            "QUANTUM SUPPRESSED: the as-built logic contains a "
            "positive cycle — the relaxation did not converge, so any "
            "completion date would be an artefact of iteration count, "
            "not of the network. Repair the circular logic (OOS "
            "module / revision comparison) and re-run; no collapse "
            "figures are reported from this model.")
        return result
    result.model_completion = _completion(EF1)
    if anchor_code and anchor_code not in nodes:
        result.warnings.append(
            f"Contractual completion milestone '{anchor_code}' is not "
            "in the modelled population — completion measured at the "
            "latest modelled finish instead (disclosed).")
    if result.model_completion and result.asbuilt_completion:
        result.calibration_days = round(
            (result.model_completion
             - result.asbuilt_completion).total_seconds() / 86400.0, 1)
        result.decision_grade = (abs(result.calibration_days)
                                 <= config.calibration_tolerance_days)
        if not result.decision_grade:
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
    ES2, EF2, conv2 = _schedule(collapsed_nodes, rels, anchor)
    if not conv2:
        result.warnings.append(
            "QUANTUM SUPPRESSED: the collapsed run did not converge "
            "(positive cycle after extraction) — no delta is reported.")
        result.model_completion = None
        return result
    result.collapsed_completion = _completion(EF2)
    if result.model_completion and result.collapsed_completion:
        result.delta_days = round(
            (result.model_completion
             - result.collapsed_completion).total_seconds() / 86400.0, 1)

    # ---- controlling chains of BOTH runs (traceback) -------------------
    # Same walk on the model run and the collapsed run: the delta is
    # only attributable when the reader can see which chain governed
    # with the events in, and which chain the model collapsed onto.
    by_code = {t.task_code: t for t in started}
    preds_of: dict[str, list[tuple[str, str, float]]] = {}
    for p, s, lt, lag in rels:
        preds_of.setdefault(s, []).append((p, lt, lag))
    removed_set = set(result.removed_codes)

    def _controlling_chain(ES: dict, EF: dict,
                           durations: dict) -> list[CabActivity]:
        if not EF:
            return []
        chain, seen = [], set()
        cur = max(EF, key=lambda c: EF[c])
        while cur and cur not in seen and len(chain) < 200:
            seen.add(cur)
            t = by_code[cur]
            chain.append(CabActivity(
                cur, t.name, ES.get(cur), EF.get(cur),
                durations.get(cur, 0.0),
                removed=cur in removed_set))
            best, best_gap = None, timedelta(days=0.51)
            for p, lt, lag in preds_of.get(cur, []):
                bound = (ES[p] if lt in ("SS", "SF") else EF[p])
                gap = ES[cur] - bound
                if timedelta(days=-0.01) <= gap < best_gap:
                    best, best_gap = p, gap
            cur = best
        return list(reversed(chain))

    result.model_chain = _controlling_chain(ES1, EF1, nodes)
    result.critical_chain = _controlling_chain(ES2, EF2, collapsed_nodes)
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
