"""Impacted-programme XER export (Module 15 output).

Injects the analyst-confirmed fragnet into a COPY of the original .xer
text as native TASK / TASKPRED rows, so the impacted programme can be
imported into Primavera P6 and rescheduled (F9) for native verification
of the impact. The source file itself is never modified.

Injection is text-level against the file's own %F field order, with new
unique numeric ids continuing the file's own sequences. Fragnet
activities are TK_NotStart TT_Task rows carrying this engine's computed
early/target dates for visibility — P6 recomputes them on scheduling.
"""

from __future__ import annotations

import re
from datetime import datetime

from dcma.xer_parser import XerData

from .tia import FragnetActivity, TIAResult

EXPORT_CAVEAT = (
    "The impacted .xer is the source programme plus the confirmed "
    "fragnet as new not-started activities and relationships. After "
    "import into Primavera P6, reschedule (F9) at the data date — P6's "
    "own CPM then produces the authoritative impacted dates; this "
    "engine's dates are carried for visibility only."
)


def _fmt(d: datetime | None) -> str:
    return d.strftime("%Y-%m-%d %H:%M") if d else ""


def _max_id(rows: list[dict], field: str) -> int:
    best = 0
    for r in rows:
        try:
            best = max(best, int(r.get(field, "0") or 0))
        except ValueError:
            continue
    return best


def build_impacted_xer(
    raw_text: str,
    data: XerData,
    fragnet: list[FragnetActivity],
    result: TIAResult,
) -> str:
    """Return the impacted .xer text (source + injected fragnet)."""
    task_rows = data.raw_tables.get("TASK", [])
    pred_rows = data.raw_tables.get("TASKPRED", [])
    if not task_rows:
        raise ValueError("Source file carries no TASK table.")

    # anchor rows for structural fields (project / wbs / calendar)
    by_code = {r.get("task_code", "").strip(): r for r in task_rows}
    anchor = None
    for f in fragnet:
        for l in f.successors + f.predecessors:
            if l.other_id in by_code:
                anchor = by_code[l.other_id]
                break
        if anchor:
            break
    anchor = anchor or task_rows[0]

    next_task = _max_id(task_rows, "task_id") + 1
    next_pred = _max_id(pred_rows, "task_pred_id") + 1
    new_task_id = {f.act_id: str(next_task + i)
                   for i, f in enumerate(fragnet)}
    code_to_id = {r.get("task_code", "").strip():
                  r.get("task_id", "").strip() for r in task_rows}

    def task_fields(text: str, table: str) -> list[str]:
        m = re.search(rf"^%T\t{table}\s*\n%F\t(.+)$", text, re.M)
        if not m:
            raise ValueError(f"{table} field row not found in the file.")
        return [f.strip() for f in m.group(1).split("\t")]

    tfields = task_fields(raw_text, "TASK")
    pfields = task_fields(raw_text, "TASKPRED")

    # dedicated WBS node so the fragnet imports as its own visible band,
    # a sibling of the tie-in activity's work package
    wbs_rows = data.raw_tables.get("PROJWBS", [])
    wbs_lines: list[str] = []
    frag_wbs_id = anchor.get("wbs_id", "")
    if wbs_rows:
        base = next((r for r in wbs_rows
                     if r.get("wbs_id", "").strip()
                     == anchor.get("wbs_id", "").strip()), None)
        try:
            wfields = task_fields(raw_text, "PROJWBS")
        except ValueError:
            wfields = None
        if base is not None and wfields is not None:
            frag_wbs_id = str(_max_id(wbs_rows, "wbs_id") + 1)
            label = (f"TIA Fragnet — {result.event.event_id}"
                     if result.event and result.event.event_id
                     else "TIA Fragnet")
            vals = dict(base)
            vals.update({
                "wbs_id": frag_wbs_id,
                "wbs_short_name": "TIA"[:20],
                "wbs_name": label[:100],
                "seq_num": str(_max_id(wbs_rows, "seq_num") + 10),
                "proj_node_flag": "N",
            })
            wbs_lines.append("%R\t" + "\t".join(vals.get(fl, "")
                                                for fl in wfields))

    dates = getattr(result, "fragnet_dates", {}) or {}
    hpd = 8.0
    cal = data.calendars.get(anchor.get("clndr_id", "").strip())
    if cal is not None and cal.day_hr_cnt > 0:
        hpd = cal.day_hr_cnt

    task_lines = []
    for f in fragnet:
        es, ef = dates.get(f.act_id, (None, None))
        vals = {
            "task_id": new_task_id[f.act_id],
            "proj_id": anchor.get("proj_id", ""),
            "wbs_id": frag_wbs_id,
            "clndr_id": f.calendar_id or anchor.get("clndr_id", ""),
            "task_code": f.act_id,
            "task_name": (f.name or f.act_id)[:100],
            "task_type": "TT_Task",
            "status_code": "TK_NotStart",
            "duration_type": anchor.get("duration_type", "DT_FixedDrtn"),
            "complete_pct_type": anchor.get("complete_pct_type", "CP_Drtn"),
            "target_drtn_hr_cnt": f"{f.duration_days * hpd:g}",
            "remain_drtn_hr_cnt": f"{f.duration_days * hpd:g}",
            "phys_complete_pct": "0",
            "early_start_date": _fmt(es),
            "early_end_date": _fmt(ef),
            "target_start_date": _fmt(es),
            "target_end_date": _fmt(ef),
        }
        task_lines.append("%R\t" + "\t".join(vals.get(fl, "")
                                             for fl in tfields))

    def resolve(other_id: str) -> str:
        return new_task_id.get(other_id) or code_to_id.get(other_id, "")

    pred_lines = []
    seen_links: set[tuple] = set()
    for f in fragnet:
        for l in f.predecessors:
            pid = resolve(l.other_id)
            if not pid:
                continue
            sig = (pid, new_task_id[f.act_id], l.link_type)
            if sig in seen_links:
                continue
            seen_links.add(sig)
            vals = {"task_pred_id": str(next_pred),
                    "task_id": new_task_id[f.act_id],
                    "pred_task_id": pid,
                    "proj_id": anchor.get("proj_id", ""),
                    "pred_proj_id": anchor.get("proj_id", ""),
                    "pred_type": f"PR_{l.link_type}",
                    "lag_hr_cnt": f"{l.lag_days * hpd:g}"}
            pred_lines.append("%R\t" + "\t".join(vals.get(fl, "")
                                                 for fl in pfields))
            next_pred += 1
        for l in f.successors:
            sid = resolve(l.other_id)
            if not sid:
                continue
            sig = (new_task_id[f.act_id], sid, l.link_type)
            if sig in seen_links:
                continue
            seen_links.add(sig)
            vals = {"task_pred_id": str(next_pred),
                    "task_id": sid,
                    "pred_task_id": new_task_id[f.act_id],
                    "proj_id": anchor.get("proj_id", ""),
                    "pred_proj_id": anchor.get("proj_id", ""),
                    "pred_type": f"PR_{l.link_type}",
                    "lag_hr_cnt": f"{l.lag_days * hpd:g}"}
            pred_lines.append("%R\t" + "\t".join(vals.get(fl, "")
                                                 for fl in pfields))
            next_pred += 1

    def inject(text: str, table: str, lines: list[str]) -> str:
        if not lines:
            return text
        # exact-name anchor: "%T\tTASK" must not match TASKPRED/TASKRSRC
        m = re.search(rf"^%T\t{table}\s*$", text, re.M)
        if m is None:
            raise ValueError(f"{table} table not found in the file.")
        nxt = text.find("\n%T\t", m.start())
        insert_at = nxt if nxt != -1 else text.rfind("\n%E")
        if insert_at == -1:
            insert_at = len(text)
        return (text[:insert_at] + "\n" + "\n".join(lines)
                + text[insert_at:])

    out = inject(raw_text, "PROJWBS", wbs_lines)
    out = inject(out, "TASK", task_lines)
    out = inject(out, "TASKPRED", pred_lines)
    return out
