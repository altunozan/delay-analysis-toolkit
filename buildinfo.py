"""Build identity for every export — which code produced this document.

The audit's reproducibility concern (F-04), answered where it matters:
a report handed over months ago must be traceable to the exact revision
that produced it, and a document generated from uncommitted code must
say so instead of pretending to be clean. The commit is read once per
process (git is absent on some hosts — that degrades to "unversioned",
never an exception); the generation time is per-document.
"""

from __future__ import annotations

import datetime as _dt
import functools
import os
import subprocess

TOOLKIT = "Delay Analysis Toolkit"


@functools.lru_cache(maxsize=1)
def _commit() -> str:
    """Short commit id, with an honest '+local-changes' marker."""
    root = os.path.dirname(os.path.abspath(__file__))
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short=10", "HEAD"],
            cwd=root, capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        if not sha:
            return "unversioned"
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=root, capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        return sha + ("+local-changes" if dirty else "")
    except Exception:  # noqa: BLE001 - no git binary / not a checkout
        return "unversioned"


def build_stamp() -> str:
    """One footer line: tool, code revision, generation moment (UTC)."""
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"{TOOLKIT} — build {_commit()} — generated {now}"
