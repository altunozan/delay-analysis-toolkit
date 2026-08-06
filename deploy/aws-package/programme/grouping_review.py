"""Deterministic critique of an umbrella grouping + the refinement loop.

The critic is arithmetic on the rows — never a model grading itself:
every defect is a named, reproducible observation with the activity
codes attached. The refinement loop sends the model its own previous
grouping WITH the critic's defect list and asks for a revision; each
round is re-scored and the BEST round is kept, not the last, because
model revisions do not improve monotonically.

An automatic loop is safe here and nowhere else on these pages:
grouping is presentation-only (programme/rollup.py measures on
critical-path members alone), so a better grouping can improve how the
path READS but can never move the measured delay.

Pure engine except for the injected ``call_model`` callable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .rollup import build_umbrella_prompt, parse_umbrella_grouping

# Labels that name nothing: a package called "General Works" tells the
# reader nothing about what was built.
_GENERIC_WORDS = {
    "work", "works", "misc", "miscellaneous", "general", "phase",
    "stage", "package", "packages", "group", "groups", "activity",
    "activities", "other", "others", "various", "items", "item",
    "scope", "part", "section", "remaining", "sundry",
}
_STOP_TOKENS = {"the", "and", "for", "with", "from", "into"}

# penalty weight and cap per defect kind
_PENALTY = {
    "uncovered":    (30.0, 30.0),   # weight is the full-fraction penalty
    "singleton":    (3.0, 12.0),
    "span":         (5.0, 15.0),
    "mixed-prefix": (4.0, 12.0),
    "generic-name": (4.0, 12.0),
    "orphan-name":  (2.0, 10.0),
}
SPAN_GAP_DAYS = 120.0


@dataclass
class GroupingDefect:
    kind: str                  # one of the _PENALTY keys
    detail: str                # one sentence, reproducible from the data
    package: str | None = None
    codes: list[str] = field(default_factory=list)


@dataclass
class GroupingCritique:
    score: float               # 0-100, deterministic
    defects: list[GroupingDefect] = field(default_factory=list)
    n_groups: int = 0
    covered_cp: int = 0
    total_cp: int = 0


def _tokens(name: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]{3,}", name.lower())
            if t not in _STOP_TOKENS}


def _prefix(code: str) -> str:
    head = re.split(r"[-_. ]", code, maxsplit=1)[0]
    m = re.match(r"[A-Za-z]+", head)
    return (m.group(0) if m else head).upper()


def critique_grouping(
    groups: dict[str, list[str]],
    rows: list[dict],
    path_codes: set[str],
) -> GroupingCritique:
    """Score a grouping 0-100 and name every defect found.

    ``rows`` are planned_vs_actual rows (the grouping pool); coverage is
    judged on critical-path WORK rows only — single-date rows
    (milestones) are points, not work, and are never expected inside a
    package.
    """
    by_code = {r["task_code"]: r for r in rows}
    owner: dict[str, str] = {}
    for name, codes in groups.items():
        for c in codes:
            owner.setdefault(c, name)

    defects: list[GroupingDefect] = []

    def _is_ms(r: dict) -> bool:
        s, f = r.get("actual_start"), r.get("actual_finish")
        return s is not None and f is not None and s == f

    # ---- coverage: CP work rows left outside every package ----------
    cp_work = [r for r in rows
               if r["task_code"] in path_codes and not _is_ms(r)]
    uncovered = [r["task_code"] for r in cp_work
                 if r["task_code"] not in owner]
    if uncovered:
        defects.append(GroupingDefect(
            kind="uncovered",
            detail=f"{len(uncovered)} of {len(cp_work)} critical-path "
                   "work activities sit in no package — group them or "
                   "state why they stand alone",
            codes=uncovered))

    for name, codes in groups.items():
        members = [by_code[c] for c in codes if c in by_code]

        # ---- singleton ----------------------------------------------
        if len(codes) == 1:
            defects.append(GroupingDefect(
                kind="singleton", package=name, codes=list(codes),
                detail=f"'{name}' holds a single activity — merge it "
                       "into a fitting package or leave it ungrouped"))

        # ---- generic label ------------------------------------------
        words = re.findall(r"[a-z]+", name.lower())
        if words and all(w in _GENERIC_WORDS for w in words):
            defects.append(GroupingDefect(
                kind="generic-name", package=name,
                detail=f"'{name}' names nothing — say what the work "
                       "actually was (trade / stage / location)"))

        # ---- span incoherence: one label, two campaigns -------------
        dated = sorted((m for m in members
                        if m.get("actual_start") and m.get("actual_finish")),
                       key=lambda m: m["actual_start"])
        worst_gap, gap_at = 0.0, None
        for a, b in zip(dated, dated[1:]):
            idle = (b["actual_start"] - a["actual_finish"]
                    ).total_seconds() / 86400.0
            if idle > worst_gap:
                worst_gap, gap_at = idle, (a["task_code"], b["task_code"])
        if worst_gap > SPAN_GAP_DAYS and gap_at:
            defects.append(GroupingDefect(
                kind="span", package=name, codes=list(gap_at),
                detail=f"'{name}' pauses {worst_gap:.0f} days between "
                       f"{gap_at[0]} and {gap_at[1]} — likely two "
                       "distinct campaigns wearing one label"))

        # ---- mixed activity-ID prefixes -----------------------------
        prefixes: dict[str, int] = {}
        for c in codes:
            prefixes[_prefix(c)] = prefixes.get(_prefix(c), 0) + 1
        if len(prefixes) >= 3 and max(prefixes.values()) < 0.6 * len(codes):
            defects.append(GroupingDefect(
                kind="mixed-prefix", package=name, codes=list(codes),
                detail=f"'{name}' mixes {len(prefixes)} activity-ID "
                       "families with no majority — check it is one "
                       "item of work, not a catch-all"))

        # ---- orphan member: shares no name token with siblings ------
        if len(members) >= 2:
            toks = {m["task_code"]: _tokens(m["name"]) for m in members}
            for m in members:
                others = set().union(*(toks[o["task_code"]]
                                       for o in members if o is not m))
                if toks[m["task_code"]] and not (toks[m["task_code"]]
                                                 & others):
                    defects.append(GroupingDefect(
                        kind="orphan-name", package=name,
                        codes=[m["task_code"]],
                        detail=f"{m['task_code']} '{m['name'][:40]}' "
                               f"shares no name token with the rest of "
                               f"'{name}'"))

    # ---- score -------------------------------------------------------
    penalty = 0.0
    for kind, (weight, cap) in _PENALTY.items():
        kd = [d for d in defects if d.kind == kind]
        if not kd:
            continue
        if kind == "uncovered":
            frac = (len(kd[0].codes) / len(cp_work)) if cp_work else 0.0
            penalty += min(weight * frac, cap)
        else:
            penalty += min(weight * len(kd), cap)
    return GroupingCritique(
        score=round(max(0.0, 100.0 - penalty), 1),
        defects=defects,
        n_groups=len(groups),
        covered_cp=len(cp_work) - len(uncovered),
        total_cp=len(cp_work))


def build_refine_prompt(
    rows: list[dict],
    path_codes: set[str],
    groups: dict[str, list[str]],
    critique: GroupingCritique,
    *,
    limit: int = 600,
) -> str:
    """Round N prompt: the activities, the previous grouping, and the
    critic's defect list — asking for a REVISED full grouping."""
    body = build_umbrella_prompt(rows, path_codes, limit=limit)
    prev = json.dumps(
        {"groups": [{"label": n, "codes": list(c)}
                    for n, c in groups.items()]})
    defect_lines = [
        f"- [{d.kind}] {d.detail}"
        + (f" (codes: {', '.join(d.codes[:8])})" if d.codes else "")
        for d in critique.defects] or ["- none"]
    return (
        body
        + f"\n\nYour PREVIOUS grouping (scored {critique.score}/100 by a "
          "deterministic reviewer):\n" + prev
        + "\n\nDefects the reviewer found:\n" + "\n".join(defect_lines)
        + "\n\nReturn a REVISED COMPLETE grouping in the same STRICT "
          "JSON (the full grouping, not a diff). Fix every defect you "
          "can WITHOUT forcing unlike work together — where a defect is "
          "better left standing (a genuine standalone activity, a "
          "deliberate split), leave it and say so in that group's "
          "rationale. Never invent a code.")


def refine_grouping(
    call_model,
    rows: list[dict],
    path_codes: set[str],
    valid_codes: set[str],
    *,
    max_rounds: int = 3,
    target_score: float = 95.0,
):
    """Propose → critique → refine, keeping the best-scoring round.

    ``call_model(prompt) -> str`` is the only non-deterministic part.
    Stops early when a round reaches ``target_score``, fails to improve
    on the best so far, or returns nothing parseable. Returns
    ``(best_proposal, best_critique, trajectory)`` where trajectory is
    one dict per round — the full audit trail of what each round
    changed and why it was or was not kept.
    """
    best, best_crit = None, None
    prev_map, prev_crit = None, None
    traj: list[dict] = []
    for rnd in range(1, max_rounds + 1):
        prompt = (build_umbrella_prompt(rows, path_codes)
                  if prev_map is None else
                  build_refine_prompt(rows, path_codes, prev_map,
                                      prev_crit))
        proposed, dropped = parse_umbrella_grouping(
            call_model(prompt), valid_codes)
        if not proposed:
            traj.append({"round": rnd, "score": None, "packages": 0,
                         "defects": None, "dropped": dropped,
                         "kept": False,
                         "top_defects": "nothing parseable returned"})
            break
        gmap: dict[str, list[str]] = {}
        for g in proposed:
            gmap.setdefault(g["label"], []).extend(g["codes"])
        crit = critique_grouping(gmap, rows, path_codes)
        improved = best_crit is None or crit.score > best_crit.score
        traj.append({"round": rnd, "score": crit.score,
                     "packages": len(gmap),
                     "defects": len(crit.defects), "dropped": dropped,
                     "kept": improved,
                     "top_defects": "; ".join(
                         d.detail for d in crit.defects[:3])})
        if improved:
            best, best_crit = proposed, crit
        if crit.score >= target_score:
            break
        if not improved:
            break               # a worse revision ends the loop
        prev_map, prev_crit = gmap, crit
    return best, best_crit, traj
