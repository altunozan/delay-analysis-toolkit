"""Module 20 — Impacted As-Planned (baseline + event fragnets).

Distinct from the update-based prospective TIA: the analyst-confirmed
event fragnets are inserted into the ORIGINAL BASELINE (no progress) in
date order, and the movement of the modelled completion is measured
after each insertion. Recognised but WEAK method — the caveats say so
loudly; it is offered because contracts sometimes prescribe it and
because records are sometimes too poor for anything better.

Pure engine: baseline XerData + register records in, structured result
out (delegates the CPM to the calendar-exact cumulative-TIA engine).
"""

from __future__ import annotations

from dcma.xer_parser import XerData

from .tia import DelayEvent, FragnetActivity, run_cumulative_tia

IAP_CAVEATS = [
    "Impacted As-Planned inserts the delay-event fragnets into the "
    "ORIGINAL BASELINE and measures the movement of the modelled "
    "completion. It is a THEORETICAL method: it ignores actual "
    "progress, contractor performance, re-sequencing and concurrent "
    "delay, and it assumes the baseline logic was achievable as "
    "planned. The SCL Protocol and AACE RP 29R-03 both regard it as "
    "among the weakest methods — use it where the contract prescribes "
    "it or the records cannot support windows / TIA, and say so.",
    "The delta is method-consistent: the same calendar-exact engine "
    "schedules the baseline pre- and post-insertion, so the movement "
    "is attributable to the inserted fragnets, not to engine "
    "differences. The engine's calibration against P6 is disclosed by "
    "the TIA module.",
    "Fragnet tie-ins must exist in the baseline. Events whose tie-in "
    "activities are missing from the baseline (e.g. built against a "
    "later revision's activities) are SKIPPED and disclosed — insert "
    "them via the update-based TIA instead.",
    "Events are inserted in date order; each event's increment depends "
    "on the events already inserted. A different insertion order can "
    "give different per-event increments (the total is order-stable).",
]


def run_impacted_asplanned(
    baseline: XerData,
    label: str,
    records: list[tuple[DelayEvent, list[FragnetActivity]]],
) -> dict:
    """Impacted as-planned on the baseline; skips non-tying events."""
    codes = {t.task_code for t in baseline.tasks}
    usable: list[tuple[DelayEvent, list[FragnetActivity]]] = []
    skipped: list[str] = []
    for event, fragnet in records:
        tie_ins = {l.other_id for f in (fragnet or [])
                   for l in (f.predecessors + f.successors)
                   if l.other_id and not any(
                       l.other_id == g.act_id for g in fragnet)}
        missing = sorted(t for t in tie_ins if t not in codes)
        if not fragnet:
            skipped.append(f"{event.event_id} (no fragnet)")
        elif missing:
            skipped.append(f"{event.event_id} (tie-ins not in baseline: "
                           + ", ".join(missing[:4])
                           + (" …" if len(missing) > 4 else "") + ")")
        else:
            usable.append((event, fragnet))

    result = run_cumulative_tia(baseline, label, usable)
    result["method"] = "Impacted As-Planned"
    result["skipped_events"] = skipped
    result["events_used"] = len(usable)
    result["caveats"] = list(IAP_CAVEATS)
    warnings = list(result.get("warnings", []))
    if skipped:
        warnings.append(
            f"{len(skipped)} register event(s) could not be inserted "
            "into the baseline and are EXCLUDED from this impacted "
            "as-planned position: " + "; ".join(skipped[:5])
            + (" …" if len(skipped) > 5 else ""))
    result["warnings"] = warnings
    return result
