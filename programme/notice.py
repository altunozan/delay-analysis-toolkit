"""Contractual notice screening + analyst clause map (form-agnostic).

The FIDIC/NEC/bespoke decision is deliberately sidestepped: the analyst
records the clause parameters (reference, notice period), optionally
assisted by AI extraction from pasted contract text under the same
verbatim-verified-quotation rail as the letters intake. The engine then
performs pure date arithmetic — notice given? within the period? — and
emits a STATUS, never a legal conclusion.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime

NOTICE_CAVEAT = (
    "Notice status is a screening date comparison against the analyst-"
    "entered clause parameters: it states whether a notice date falls "
    "within the recorded period, nothing more. Time-bar effect, "
    "condition-precedent character, and any relief are contractual/legal "
    "determinations outside this tool."
)

CLAUSE_SYSTEM_PROMPT = (
    "You extract contract clause mechanics. Return ONLY valid JSON. "
    "Every entry must quote a VERBATIM snippet from the supplied text; "
    "if the contract is silent on a topic, mark it silent rather than "
    "inventing a clause."
)


@dataclass
class NoticeAssessment:
    status: str            # compliant | late | no_notice | indeterminate
    margin_days: float | None = None    # + = spare, - = days late
    detail: str = ""


def _business_days_between(a: datetime, b: datetime) -> float:
    """Mon-Fri days from a to b (negative when b precedes a)."""
    if b < a:
        return -_business_days_between(b, a)
    from datetime import timedelta
    count, cur = 0, a
    while cur < b:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            count += 1
    return float(count)


def assess_notice(
    awareness_date: datetime | None,
    notice_date: datetime | None,
    period_days: float | None,
    basis: str = "calendar",        # "calendar" | "business" (Mon-Fri)
) -> NoticeAssessment:
    """Pure date arithmetic; indeterminate whenever an input is missing.

    ``basis`` states how the clause counts days; the chosen basis is
    printed in the detail so the screening is auditable. Business days
    are Mon-Fri — contract-specific holidays are not modelled.
    """
    label = "business day" if basis == "business" else "calendar day"
    if period_days is None or awareness_date is None:
        return NoticeAssessment(
            "indeterminate", None,
            "Awareness date and clause period are both required.")
    if notice_date is None:
        return NoticeAssessment(
            "no_notice", None,
            f"No notice date recorded against a {period_days:.0f} "
            f"{label} period.")
    if basis == "business":
        used = _business_days_between(awareness_date, notice_date)
    else:
        used = (notice_date - awareness_date).total_seconds() / 86400
    margin = round(period_days - used, 1)
    if margin >= 0:
        return NoticeAssessment(
            "compliant", margin,
            f"Notice given {used:.0f} {label}(s) after awareness — "
            f"{margin:.0f} {label}(s) inside the {period_days:.0f} "
            f"{label} period.")
    return NoticeAssessment(
        "late", margin,
        f"Notice given {used:.0f} {label}(s) after awareness — "
        f"{-margin:.0f} {label}(s) beyond the {period_days:.0f} "
        f"{label} period.")


def build_clause_extraction_prompt(contract_text: str) -> str:
    return (
        "<task>From this contract text, extract the mechanics for: EOT "
        "entitlement, notice requirements (periods in days and their "
        "trigger), delay definition, prescribed analysis method, float "
        "ownership, concurrency. One entry per topic found.</task>\n"
        "<contract>\n" + (contract_text or "")[:40_000] + "\n</contract>\n"
        '<output>Return ONLY JSON: {"clauses": [{"topic": "...", '
        '"clause_ref": "e.g. 20.1", "period_days": N or null, '
        '"requirement": "one-sentence summary", '
        '"snippet": "VERBATIM quotation, max 240 chars", '
        '"silent": false}]}. If a topic is not addressed, include it '
        'with "silent": true and no snippet.</output>'
    )


def parse_clause_extraction(text: str, contract_text: str) -> list[dict]:
    """Strict parse; non-silent entries need a verifiable verbatim quote."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    s, e = cleaned.find("{"), cleaned.rfind("}")
    if s == -1 or e <= s:
        return []
    try:
        obj = json.loads(cleaned[s:e + 1])
    except json.JSONDecodeError:
        return []
    items = obj.get("clauses") if isinstance(obj, dict) else None
    if not isinstance(items, list):
        return []
    norm = re.sub(r"\s+", " ", contract_text or "").lower()
    out = []
    for i in items:
        if not isinstance(i, dict) or not str(i.get("topic", "")).strip():
            continue
        silent = bool(i.get("silent"))
        snippet = str(i.get("snippet", "")).strip()[:300]
        if not silent:
            if not snippet or re.sub(r"\s+", " ", snippet).lower() not in norm:
                continue                       # unverifiable -> dropped
        try:
            period = (float(i["period_days"])
                      if i.get("period_days") is not None else None)
        except (TypeError, ValueError):
            period = None
        out.append({"topic": str(i["topic"])[:60],
                    "clause_ref": str(i.get("clause_ref", ""))[:30],
                    "period_days": period,
                    "requirement": str(i.get("requirement", ""))[:300],
                    "snippet": snippet, "silent": silent})
    return out[:12]
