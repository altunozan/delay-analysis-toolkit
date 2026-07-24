"""Module 19 — Concurrent-Delay Screening.

The most-litigated issue in delay disputes. This module SCREENS each
analysis window for time-overlap between Employer-asserted and
Contractor-asserted delay events, and flags windows where a pacing
enquiry is warranted. It deliberately stops at screening:

* overlap in TIME is necessary but not sufficient for concurrency — the
  legal tests (true concurrency, dominant cause, Malmaison, SCL
  approaches, apportionment) are contractual analysis outside this tool;
* responsibility is AS ASSERTED on each event by the analyst, never
  concluded by the engine;
* the pacing flag is a prompt to enquire, not a finding — a pacing
  defence needs contemporaneous evidence of a deliberate decision.

Pure engine: windows result + event register in, structured screening
out. No LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .tia import DelayEvent, FragnetActivity
from .windows import WindowsResult

CONCURRENCY_CAVEATS = [
    "This is a TIME-OVERLAP screening of asserted delay events per "
    "analysis window. Overlap is necessary but not sufficient for "
    "concurrent delay: whether overlapping events each independently "
    "delayed completion, and how the contract allocates that situation "
    "(true concurrency, dominant cause, Malmaison, apportionment), is a "
    "contractual and legal analysis outside this tool.",
    "Responsibility is AS ASSERTED by the analyst on each register "
    "event ('Employer', 'Contractor', or otherwise) and is never "
    "concluded by the engine. Events whose asserted responsibility "
    "matches neither party are reported as unclassified, not ignored.",
    "Event windows are screened as [date raised, date raised + total "
    "fragnet duration]; fragnet working-day durations are treated as "
    "calendar days for the overlap arithmetic, which slightly widens "
    "events on non-continuous calendars. Where no fragnet exists the "
    "event is screened as a single day and flagged.",
    "The pacing flag marks windows where every Contractor-asserted "
    "overlap sits inside the Employer-asserted envelope — the classic "
    "shape of pacing. It is a prompt to enquire for contemporaneous "
    "evidence of a deliberate pacing decision, not a finding of pacing.",
]

_EMPLOYER_WORDS = ("employer", "client", "owner", "engineer", "principal")
_CONTRACTOR_WORDS = ("contractor", "subcontract", "builder", "vendor",
                     "supplier")


def classify_responsibility(asserted: str) -> str:
    """Normalise an asserted-responsibility string to a screening party."""
    low = (asserted or "").lower()
    if any(w in low for w in _EMPLOYER_WORDS):
        return "Employer"
    if any(w in low for w in _CONTRACTOR_WORDS):
        return "Contractor"
    return "Unclassified"


@dataclass
class EventSpan:
    event_id: str
    title: str
    asserted: str                  # verbatim analyst assertion
    party: str                     # Employer / Contractor / Unclassified
    start: datetime
    end: datetime
    duration_days: float
    single_day: bool = False       # no fragnet — screened as one day


@dataclass
class ConcurrencyWindow:
    index: int
    from_label: str
    to_label: str
    start: datetime | None
    end: datetime | None
    movement_days: float | None
    employer_days: float = 0.0     # union of employer spans in window
    contractor_days: float = 0.0
    unclassified_days: float = 0.0
    both_days: float = 0.0         # employer union ∩ contractor union
    employer_events: list[str] = field(default_factory=list)
    contractor_events: list[str] = field(default_factory=list)
    unclassified_events: list[str] = field(default_factory=list)
    concurrent_candidate: bool = False
    pacing_flag: bool = False


@dataclass
class ConcurrencyResult:
    windows: list[ConcurrencyWindow] = field(default_factory=list)
    events: list[EventSpan] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _merge(intervals: list[tuple[datetime, datetime]]
           ) -> list[tuple[datetime, datetime]]:
    out: list[tuple[datetime, datetime]] = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def _total_days(intervals: list[tuple[datetime, datetime]]) -> float:
    return round(sum((e - s).total_seconds() for s, e in intervals)
                 / 86400.0, 1)


def _intersect(a: list[tuple[datetime, datetime]],
               b: list[tuple[datetime, datetime]]
               ) -> list[tuple[datetime, datetime]]:
    out = []
    for s1, e1 in a:
        for s2, e2 in b:
            s, e = max(s1, s2), min(e1, e2)
            if s < e:
                out.append((s, e))
    return _merge(out)


def screen_concurrency(
    windows: WindowsResult,
    records: list[tuple[DelayEvent, list[FragnetActivity]]],
) -> ConcurrencyResult:
    """Screen each window for Employer/Contractor event overlap."""
    result = ConcurrencyResult()
    result.caveats.extend(CONCURRENCY_CAVEATS)

    # --- events -> screened spans ---------------------------------------
    no_date = 0
    for event, fragnet in records:
        if event.date_raised is None:
            no_date += 1
            continue
        dur = sum(max(f.duration_days, 0.0) for f in (fragnet or []))
        single = not fragnet or dur <= 0
        end = event.date_raised + timedelta(days=max(dur, 1.0))
        result.events.append(EventSpan(
            event_id=event.event_id,
            title=event.title,
            asserted=event.responsibility_asserted or "(not asserted)",
            party=classify_responsibility(event.responsibility_asserted),
            start=event.date_raised,
            end=end,
            duration_days=round(max(dur, 1.0), 1),
            single_day=single,
        ))
    if no_date:
        result.warnings.append(
            f"{no_date} register event(s) have no date and cannot be "
            "screened — date them to include them.")
    singles = sum(1 for e in result.events if e.single_day)
    if singles:
        result.warnings.append(
            f"{singles} event(s) have no fragnet and are screened as a "
            "single day — their true extent is understated until a "
            "fragnet is built.")
    unclass = [e for e in result.events if e.party == "Unclassified"]
    if unclass:
        result.warnings.append(
            f"{len(unclass)} event(s) have an asserted responsibility "
            "that maps to neither party ("
            + ", ".join(sorted({e.asserted for e in unclass})[:4])
            + ") — they appear as 'unclassified' and do not feed the "
            "concurrency flags.")

    # --- per-window screening -------------------------------------------
    for w in windows.windows:
        cw = ConcurrencyWindow(
            index=w.index, from_label=w.from_label, to_label=w.to_label,
            start=w.start, end=w.end, movement_days=w.movement_days)
        if w.start is None or w.end is None:
            result.windows.append(cw)
            continue
        clipped: dict[str, list[tuple[datetime, datetime]]] = {
            "Employer": [], "Contractor": [], "Unclassified": []}
        for ev in result.events:
            s, e = max(ev.start, w.start), min(ev.end, w.end)
            if s >= e:
                continue
            clipped[ev.party].append((s, e))
            {"Employer": cw.employer_events,
             "Contractor": cw.contractor_events,
             "Unclassified": cw.unclassified_events}[ev.party].append(
                ev.event_id)
        emp = _merge(clipped["Employer"])
        con = _merge(clipped["Contractor"])
        cw.employer_days = _total_days(emp)
        cw.contractor_days = _total_days(con)
        cw.unclassified_days = _total_days(_merge(clipped["Unclassified"]))
        both = _intersect(emp, con)
        cw.both_days = _total_days(both)
        moved = (cw.movement_days or 0.0) > 0
        cw.concurrent_candidate = cw.both_days > 0 and moved
        # pacing shape: every contractor overlap sits INSIDE the employer
        # envelope for this window
        if cw.concurrent_candidate and emp and con:
            env_s = min(s for s, _ in emp)
            env_e = max(e for _, e in emp)
            cw.pacing_flag = all(env_s <= s and e <= env_e
                                 for s, e in con)
        result.windows.append(cw)

    n_conc = sum(1 for w in result.windows if w.concurrent_candidate)
    if n_conc:
        result.warnings.append(
            f"{n_conc} window(s) show Employer- and Contractor-asserted "
            "events overlapping while completion moved — CONCURRENT-"
            "DELAY CANDIDATES. Entitlement in these windows turns on the "
            "contract's concurrency approach; do not net the movement "
            "off without that analysis.")
    n_pace = sum(1 for w in result.windows if w.pacing_flag)
    if n_pace:
        result.warnings.append(
            f"{n_pace} window(s) show the pacing shape (contractor "
            "overlap wholly inside the employer envelope) — enquire for "
            "contemporaneous evidence of a deliberate pacing decision "
            "before treating the contractor overlap as culpable delay.")
    return result
