"""Forensic validation of a proposed RLPA path before adoption."""

from __future__ import annotations

from datetime import datetime

from .models import PathDraft, StudioDataset, ValidationIssue


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def validate_draft(dataset: StudioDataset, draft: PathDraft) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    codes = list(draft.path_codes)
    known = {activity.code: activity for activity in dataset.activities}
    if len(codes) < 2:
        issues.append(ValidationIssue(
            "error", "path_too_short",
            "A critical path needs at least two activities, including its anchor milestone.",
            tuple(codes)))
    duplicates = tuple(code for code in dict.fromkeys(codes)
                       if codes.count(code) > 1)
    if duplicates:
        issues.append(ValidationIssue(
            "error", "duplicate_activity",
            "An activity can appear only once in the adopted path.", duplicates))
    unknown = tuple(code for code in codes if code not in known)
    if unknown:
        issues.append(ValidationIssue(
            "error", "unknown_activity",
            "The draft contains activities not present in this programme revision.",
            unknown))
    ineligible = tuple(code for code in codes
                       if code in known and not known[code].path_eligible)
    if ineligible:
        issues.append(ValidationIssue(
            "error", "ineligible_path_activity",
            "Level of Effort or other non-driving activities may be shown for context but cannot be adopted onto the driving path.",
            ineligible))
    if dataset.milestone_code not in codes:
        issues.append(ValidationIssue(
            "error", "missing_anchor",
            f"The elected milestone {dataset.milestone_code} is not on the path.",
            (dataset.milestone_code,)))
    elif codes and codes[-1] != dataset.milestone_code:
        issues.append(ValidationIssue(
            "warning", "anchor_not_last",
            f"The elected milestone {dataset.milestone_code} is not the final path activity.",
            (dataset.milestone_code,)))
    if not draft.basis.strip():
        issues.append(ValidationIssue(
            "error", "missing_basis",
            "State whether the path is recorded logic, actual sequence, inferred, or analyst-adjusted."))

    edges = {(rel.predecessor, rel.successor): rel
             for rel in dataset.relationships}
    for predecessor, successor in zip(codes, codes[1:]):
        if predecessor not in known or successor not in known:
            continue
        relation = edges.get((predecessor, successor))
        if relation is None:
            issues.append(ValidationIssue(
                "warning", "unlinked_handoff",
                f"{predecessor} → {successor} has no direct recorded or inferred relationship; document the sequence evidence.",
                (predecessor, successor)))
        elif relation.source != "recorded":
            issues.append(ValidationIssue(
                "warning", "non_recorded_logic",
                f"{predecessor} → {successor} relies on {relation.source} logic and needs explicit analyst support.",
                (predecessor, successor)))
        pred_finish = _date(known[predecessor].finish)
        succ_start = _date(known[successor].start)
        if pred_finish and succ_start and succ_start < pred_finish:
            issues.append(ValidationIssue(
                "info", "overlapping_handoff",
                f"{successor} starts before {predecessor} finishes; verify SS/FF logic or out-of-sequence execution.",
                (predecessor, successor)))
    return issues
