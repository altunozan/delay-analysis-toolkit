"""Pure helpers for applying an analyst's path adjustment.

Kept out of the view so the labelling rules are pinned by tests: the
basis line discloses the adjustment exactly once however many times the
analyst re-applies, and the path keeps the gantt's ordering.
"""

from __future__ import annotations

_SUFFIX = " — analyst-adjusted in the path gantt (rationale on file)"


def adjusted_path(working: list[str],
                  names: dict[str, str]) -> list[tuple[str, str]]:
    """Working codes (gantt order, deduplicated) -> [(code, name)]."""
    return [(code, names.get(code, code))
            for code in dict.fromkeys(working)]


def adjusted_basis(basis: str) -> str:
    """Append the disclosure once — re-applying must not stack it."""
    core = basis.split(_SUFFIX)[0].strip() or "adopted path"
    return core + _SUFFIX
