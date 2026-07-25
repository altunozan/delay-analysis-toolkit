"""Umbrella activities — work-package roll-up for as-built presentation.

An as-built critical path at activity level is unreadable in a report:
twenty rows of trunking, sleeves and containment say less than one bar
labelled "Electrical First Fix". This module rolls analyst-confirmed
groups of activities into UMBRELLA rows that carry the same shape as
``planned_vs_actual`` output, so every downstream consumer — the
comparison table, the as-planned/as-built gantt, key dates, key-date
windows and the workbook — works on them unchanged.

THE MEASUREMENT RULE (analyst election, deliberate and load-bearing):

    An umbrella's measured dates derive ONLY from members that sit on
    the adopted as-built critical path.

Grouping is a presentation device, and a presentation device must never
move the number. If "Electrical First Fix" contains three activities on
the critical path plus one snagging item that was never critical and
finished three weeks later, spanning all four would silently inflate the
measured delay by three weeks. Non-critical members are carried inside
the group — visible, exportable, drillable — but they cannot move the
bar that is measured. Their full span is retained separately as
``full_actual_*`` for presentation only, so the report can still show
the whole work package next to the measured portion.

Grouping may be AI-PROPOSED (prompt + strict parser below) but is never
AI-applied: proposals name verbatim activity codes, codes absent from
the programme are dropped and counted, and the analyst confirms every
umbrella before it enters a measurement.

Pure engine + prompt/parse helpers. No API calls, no LLM in the maths.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime

ROLLUP_CAVEATS = [
    "Umbrella activities are a READ-ONLY presentation overlay: they "
    "group activities for reporting and change no dates, durations, "
    "logic or progress in any programme. Member activities remain "
    "individually reported and exported beneath their umbrella.",
    "An umbrella's MEASURED dates derive only from members on the "
    "adopted as-built critical path — grouping cannot move the measured "
    "delay. Members off the critical path are shown inside the group "
    "for context and their full span is reported separately, marked as "
    "presentation only.",
    "An umbrella's planned dates are the earliest planned start and "
    "latest planned finish of those same on-path members AS THEY APPEAR "
    "IN THE BASELINE. Members absent from the baseline (added scope) "
    "cannot contribute a planned date and are disclosed per umbrella.",
    "The activity whose recorded finish sets each umbrella's finish is "
    "named ('driving member') so the umbrella's variance can be traced "
    "to the activity that produced it.",
    "Where grouping was AI-assisted the model only PROPOSED groupings "
    "of verbatim activity codes; codes not present in the programme are "
    "dropped, and every umbrella is analyst-confirmed before use.",
]


@dataclass
class UmbrellaMember:
    task_code: str
    name: str
    on_path: bool                       # on the adopted as-built CP
    in_baseline: bool
    planned_start: datetime | None
    planned_finish: datetime | None
    actual_start: datetime | None
    actual_finish: datetime | None
    start_var_days: float | None
    finish_var_days: float | None


@dataclass
class Umbrella:
    key: str                            # synthetic row code
    name: str
    members: list[UmbrellaMember] = field(default_factory=list)
    # --- measured span: ON-PATH MEMBERS ONLY --------------------------
    planned_start: datetime | None = None
    planned_finish: datetime | None = None
    actual_start: datetime | None = None
    actual_finish: datetime | None = None
    start_var_days: float | None = None
    finish_var_days: float | None = None
    driving_member: str | None = None   # sets the measured actual finish
    planned_driver: str | None = None   # sets the measured planned finish
    # --- presentation span: ALL members (never measured) --------------
    full_actual_start: datetime | None = None
    full_actual_finish: datetime | None = None
    measured: bool = True               # False when no on-path member
    warnings: list[str] = field(default_factory=list)

    @property
    def member_count(self) -> int:
        return len(self.members)

    @property
    def on_path_count(self) -> int:
        return sum(1 for m in self.members if m.on_path)

    @property
    def presentation_only_days(self) -> float | None:
        """How much later the full group ran than the measured portion."""
        if self.full_actual_finish and self.actual_finish:
            return round((self.full_actual_finish
                          - self.actual_finish).total_seconds() / 86400, 1)
        return None


@dataclass
class RollupResult:
    umbrellas: list[Umbrella] = field(default_factory=list)
    ungrouped: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    def measurement_rows(self) -> list[dict]:
        """Umbrella + ungrouped rows in ``planned_vs_actual`` shape.

        Extra keys (``is_umbrella``, ``member_count``, ``driving_member``)
        are additive: consumers that ignore them behave exactly as they
        did on per-activity rows.
        """
        rows: list[dict] = []
        for u in self.umbrellas:
            if not u.measured:
                continue
            rows.append({
                "task_code": u.key,
                "name": u.name,
                "planned_start": u.planned_start,
                "planned_finish": u.planned_finish,
                "actual_start": u.actual_start,
                "actual_finish": u.actual_finish,
                "start_var_days": u.start_var_days,
                "finish_var_days": u.finish_var_days,
                "in_baseline": u.planned_finish is not None,
                "is_umbrella": True,
                "member_count": u.member_count,
                "on_path_count": u.on_path_count,
                "driving_member": u.driving_member,
            })
        for r in self.ungrouped:
            rows.append({**r, "is_umbrella": False, "member_count": 1,
                         "on_path_count": 1 if r.get("_on_path") else 0,
                         "driving_member": None})
        rows.sort(key=lambda r: (r["actual_start"] or datetime.max,
                                 r["task_code"]))
        return rows

    def member_rows(self) -> list[dict]:
        """Flat member listing for drill-down and export."""
        out = []
        for u in self.umbrellas:
            for m in u.members:
                out.append({
                    "umbrella": u.name,
                    "task_code": m.task_code,
                    "name": m.name,
                    "on_critical_path": "yes" if m.on_path else "no",
                    "planned_start": m.planned_start,
                    "planned_finish": m.planned_finish,
                    "actual_start": m.actual_start,
                    "actual_finish": m.actual_finish,
                    "start_var_days": m.start_var_days,
                    "finish_var_days": m.finish_var_days,
                    "drives_umbrella_finish":
                        "DRIVER" if m.task_code == u.driving_member else "",
                })
        return out


def _delta_days(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return round((b - a).total_seconds() / 86400.0, 1)


def _slug(name: str, index: int) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "-", name.strip()).strip("-").upper()
    return f"UMB-{index:02d}-{base[:24]}" if base else f"UMB-{index:02d}"


def build_rollup(
    rows: list[dict],
    groups: dict[str, list[str]],
    path_codes: set[str] | None = None,
) -> RollupResult:
    """Roll analyst-confirmed groups into umbrella rows.

    ``rows``       — from ``planned_vs_actual`` (per-activity).
    ``groups``     — {umbrella name: [task_code, ...]}, analyst-confirmed.
    ``path_codes`` — the adopted as-built critical path. Only members in
                     this set contribute MEASURED dates. ``None`` treats
                     every member as on-path (no critical-path adopted).
    """
    result = RollupResult()
    result.caveats.extend(ROLLUP_CAVEATS)
    by_code = {r["task_code"]: r for r in rows}
    on_path = path_codes if path_codes is not None else set(by_code)

    claimed: set[str] = set()
    duplicated: list[str] = []
    for index, (name, codes) in enumerate(groups.items(), start=1):
        seen: set[str] = set()
        u = Umbrella(key=_slug(name, index), name=name)
        for code in codes:
            if code in seen:
                continue
            seen.add(code)
            r = by_code.get(code)
            if r is None:
                u.warnings.append(
                    f"'{code}' is not in the comparison set and was "
                    "ignored.")
                continue
            if code in claimed:
                duplicated.append(code)
                continue
            claimed.add(code)
            u.members.append(UmbrellaMember(
                task_code=code, name=r["name"],
                on_path=code in on_path,
                in_baseline=bool(r.get("in_baseline")),
                planned_start=r["planned_start"],
                planned_finish=r["planned_finish"],
                actual_start=r["actual_start"],
                actual_finish=r["actual_finish"],
                start_var_days=r["start_var_days"],
                finish_var_days=r["finish_var_days"]))
        if not u.members:
            u.measured = False
            u.warnings.append("No members resolved — umbrella ignored.")
            result.umbrellas.append(u)
            continue

        # --- presentation span: every member -------------------------
        all_starts = [m.actual_start for m in u.members if m.actual_start]
        all_fins = [m.actual_finish for m in u.members if m.actual_finish]
        u.full_actual_start = min(all_starts) if all_starts else None
        u.full_actual_finish = max(all_fins) if all_fins else None

        # --- measured span: ON-PATH members only ---------------------
        crit = [m for m in u.members if m.on_path]
        if not crit:
            u.measured = False
            u.warnings.append(
                f"No member of '{u.name}' is on the adopted as-built "
                "critical path — the umbrella is presentation-only and "
                "does NOT enter the delay measurement.")
            result.umbrellas.append(u)
            continue

        a_starts = [(m.actual_start, m) for m in crit if m.actual_start]
        a_fins = [(m.actual_finish, m) for m in crit if m.actual_finish]
        p_starts = [m.planned_start for m in crit if m.planned_start]
        p_fins = [(m.planned_finish, m) for m in crit if m.planned_finish]
        if a_starts:
            u.actual_start = min(d for d, _ in a_starts)
        if a_fins:
            d, m = max(a_fins, key=lambda x: x[0])
            u.actual_finish, u.driving_member = d, m.task_code
        if p_starts:
            u.planned_start = min(p_starts)
        if p_fins:
            d, m = max(p_fins, key=lambda x: x[0])
            u.planned_finish, u.planned_driver = d, m.task_code
        u.start_var_days = _delta_days(u.planned_start, u.actual_start)
        u.finish_var_days = _delta_days(u.planned_finish, u.actual_finish)

        # --- disclosure ----------------------------------------------
        off = u.member_count - u.on_path_count
        if off:
            extra = u.presentation_only_days
            u.warnings.append(
                f"'{u.name}': {off} of {u.member_count} members are NOT "
                "on the adopted critical path and do not affect its "
                "measured dates."
                + (f" The full group ran {extra:+.0f} days beyond the "
                   "measured finish (presentation only)."
                   if extra and extra > 0 else ""))
        missing = [m.task_code for m in crit if not m.in_baseline]
        if missing:
            u.warnings.append(
                f"'{u.name}': {len(missing)} on-path member(s) are not in "
                "the baseline (added scope) and contribute no planned "
                "date: " + ", ".join(missing[:5])
                + (" …" if len(missing) > 5 else ""))
        result.umbrellas.append(u)

    # --- everything not grouped stays an individual row --------------
    for r in rows:
        if r["task_code"] not in claimed:
            result.ungrouped.append(
                {**r, "_on_path": r["task_code"] in on_path})

    if duplicated:
        result.warnings.append(
            f"{len(duplicated)} activity(ies) were listed in more than "
            "one umbrella and were kept only in the first: "
            + ", ".join(sorted(set(duplicated))[:6])
            + (" …" if len(set(duplicated)) > 6 else ""))
    unmeasured = [u.name for u in result.umbrellas if not u.measured]
    if unmeasured:
        result.warnings.append(
            f"{len(unmeasured)} umbrella(s) contain no critical-path "
            "member and are excluded from the measurement: "
            + ", ".join(unmeasured[:5])
            + (" …" if len(unmeasured) > 5 else ""))
    measured = [u for u in result.umbrellas if u.measured]
    if measured:
        result.warnings.append(
            f"{len(measured)} umbrella(s) rolled up from "
            f"{sum(u.member_count for u in measured)} activities "
            f"({sum(u.on_path_count for u in measured)} of them on the "
            "adopted critical path, which alone set the measured dates).")
    return result


def umbrella_links(links, groups: dict[str, list[str]]) -> list[dict]:
    """Lift activity-level path links to links BETWEEN work packages.

    ``links`` are TraceLink records from the as-built path. A link whose
    two ends sit in different umbrellas becomes an umbrella-to-umbrella
    link; links inside one umbrella are internal and reported as such
    (they are what makes the package one item of work). Each umbrella
    link keeps the underlying activity hand-offs so a reader can open it
    and see exactly which activities joined the two packages.
    """
    owner: dict[str, str] = {}
    for name, codes in groups.items():
        for c in codes:
            owner.setdefault(c, name)

    agg: dict[tuple[str, str], dict] = {}
    for lk in links:
        a = owner.get(lk.pred_code, lk.pred_code)
        b = owner.get(lk.succ_code, lk.succ_code)
        if a == b:
            continue                      # internal to one package
        key = (a, b)
        row = agg.setdefault(key, {
            "from": a, "to": b,
            "from_is_umbrella": lk.pred_code in owner,
            "to_is_umbrella": lk.succ_code in owner,
            "hand_offs": [], "logic_evidenced": 0, "sequence_only": 0,
            "min_gap_days": None})
        row["hand_offs"].append(
            f"{lk.pred_code}→{lk.succ_code} ({lk.gap_days:+.0f}d, "
            f"{'logic' if lk.had_logic else 'sequence only'})")
        if lk.had_logic:
            row["logic_evidenced"] += 1
        else:
            row["sequence_only"] += 1
        row["min_gap_days"] = (lk.gap_days if row["min_gap_days"] is None
                               else min(row["min_gap_days"], lk.gap_days))
    for row in agg.values():
        row["hand_off_count"] = len(row["hand_offs"])
        row["basis"] = ("logic" if row["sequence_only"] == 0
                        else "sequence only" if row["logic_evidenced"] == 0
                        else "mixed")
    return list(agg.values())


def internal_links(links, groups: dict[str, list[str]]) -> dict[str, int]:
    """How many path hand-offs sit INSIDE each umbrella."""
    owner: dict[str, str] = {}
    for name, codes in groups.items():
        for c in codes:
            owner.setdefault(c, name)
    counts: dict[str, int] = {}
    for lk in links:
        a, b = owner.get(lk.pred_code), owner.get(lk.succ_code)
        if a is not None and a == b:
            counts[a] = counts.get(a, 0) + 1
    return counts


# --------------------------------------------------------------------------- #
# AI-assisted grouping (proposal only; analyst confirms every umbrella)
# --------------------------------------------------------------------------- #

UMBRELLA_SYSTEM_PROMPT = (
    "You are assisting a forensic delay analyst preparing an as-planned "
    "versus as-built comparison. You will receive as-built activities "
    "(code, name, actual dates, and whether each sits on the as-built "
    "critical path). Group them into WORK PACKAGES that a reader would "
    "recognise as one item of work — e.g. 'Electrical First Fix' "
    "covering containment, trunking, sleeves and conduit; 'Blockwork to "
    "Level 3'; 'Curtain Wall Installation'. The purpose is READABILITY "
    "of the as-built critical path, not delay attribution. Rules: use "
    "ONLY the activity codes supplied, verbatim; never invent a code; "
    "group by the nature of the work and its location, not by date "
    "proximity; keep an activity ungrouped rather than forcing it into "
    "a poor fit; prefer 6-20 packages. Return STRICT JSON: "
    "{\"groups\": [{\"label\": str, \"codes\": [str], \"rationale\": "
    "str}]} and nothing else.")


def build_umbrella_prompt(rows: list[dict],
                          path_codes: set[str] | None = None,
                          *, limit: int = 600) -> str:
    """Prompt body: the activities available for grouping."""
    on_path = path_codes or set()
    lines = []
    for r in rows[:limit]:
        st, fi = r["actual_start"], r["actual_finish"]
        flag = "CP" if r["task_code"] in on_path else "--"
        s_txt = f"{st:%Y-%m-%d}" if st else "not started"
        f_txt = (f"{fi:%Y-%m-%d}" if fi
                 else "in progress" if st else "-")
        lines.append(f"{r['task_code']}\t{r['name']}\t{flag}\t"
                     f"{s_txt}\t{f_txt}")
    note = ("" if len(rows) <= limit
            else f"\n(NOTE: first {limit} of {len(rows)} shown)")
    return ("Activities (code<TAB>name<TAB>CP flag<TAB>actual start<TAB>"
            "actual finish), in as-built order:\n"
            + "\n".join(lines) + note)


def parse_umbrella_grouping(
    text: str, valid_codes: set[str]
) -> tuple[list[dict], int]:
    """Parse the model's JSON; drop any code not verbatim in the set."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return [], 0
    try:
        payload = json.loads(m.group(0))
    except json.JSONDecodeError:
        return [], 0
    groups, dropped = [], 0
    for g in payload.get("groups", []):
        raw = g.get("codes", []) or []
        codes = [c for c in raw if c in valid_codes]
        dropped += len(raw) - len(codes)
        if codes:
            groups.append({"label": str(g.get("label", "work package")),
                           "codes": codes,
                           "rationale": str(g.get("rationale", ""))})
    return groups, dropped
