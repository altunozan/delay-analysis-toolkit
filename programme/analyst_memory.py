"""Sleek analyst memory for the toolkit's AI layer.

The models behind the API keys never learn between calls — so the app
remembers instead: analyst decisions (confirmed groupings, elections,
voice preferences, corrections) are stored as COMPACT precedent and fed
back into every AI prompt as a few lines. Hard caps keep it sleek: the
whole snippet can never exceed ~700 characters, so it costs a couple of
hundred tokens per call and zero analyst time.

Forensic rails unchanged: precedent lines are HINTS to the drafting
model — the verbatim-verification and analyst-confirmation gates on its
OUTPUT are untouched. Memory can shape a proposal, never bypass a gate.

Pure engine + tiny JSON store. Corrupt or missing files start fresh;
an unwritable filesystem (Streamlit Cloud) degrades to session-only.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

MEMORY_FILE = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), ".analyst_memory.json")

MAX_LESSONS = 20          # newest-first, deduped
MAX_LESSON_CHARS = 160
MAX_VOICE_BULLETS = 5
MAX_VOICE_CHARS = 120
MAX_PROJECTS = 25
SNIPPET_CAP = 700


def _fresh() -> dict:
    return {"version": 1, "voice": [], "lessons": [], "projects": {}}


def load(path: str = MEMORY_FILE) -> dict:
    """Load the memory; anything malformed starts fresh (never crashes)."""
    try:
        with open(path, encoding="utf-8") as fh:
            mem = json.load(fh)
        if not isinstance(mem, dict) or "version" not in mem:
            return _fresh()
        for key, kind in (("voice", list), ("lessons", list),
                          ("projects", dict)):
            if not isinstance(mem.get(key), kind):
                mem[key] = kind()
        return mem
    except (OSError, json.JSONDecodeError, ValueError):
        return _fresh()


def save(mem: dict, path: str = MEMORY_FILE) -> bool:
    """Persist; False when the filesystem refuses (Cloud) — callers keep
    the in-session copy and the memory lives for the session only."""
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(mem, fh, indent=1)
        return True
    except OSError:
        return False


def set_voice(mem: dict, bullets: list[str]) -> None:
    """Analyst's standing report voice — max 5 short bullets."""
    mem["voice"] = [b.strip()[:MAX_VOICE_CHARS]
                    for b in bullets if b.strip()][:MAX_VOICE_BULLETS]


def remember_lesson(mem: dict, scope: str, text: str) -> None:
    """One compact precedent line; deduped, newest first, capped."""
    text = " ".join((text or "").split())[:MAX_LESSON_CHARS]
    if not text:
        return
    entry = {"scope": scope, "text": text,
             "ts": datetime.now().strftime("%Y-%m-%d")}
    mem["lessons"] = ([entry]
                      + [l for l in mem["lessons"]
                         if not (l.get("scope") == scope
                                 and l.get("text") == text)]
                      )[:MAX_LESSONS]


def remember_project(mem: dict, proj_key: str, **fields) -> None:
    """Per-matter elections (contract milestone, date basis, …) keyed by
    the upload set's content hashes — reloading the same files restores
    them. Oldest matters are evicted beyond the cap."""
    if not proj_key:
        return
    proj = mem["projects"].setdefault(proj_key, {})
    for k, v in fields.items():
        if v not in (None, ""):
            proj[str(k)] = v if isinstance(v, (int, float, bool)) \
                else str(v)[:200]
    proj["ts"] = datetime.now().strftime("%Y-%m-%d")
    if len(mem["projects"]) > MAX_PROJECTS:
        oldest = sorted(mem["projects"],
                        key=lambda k: mem["projects"][k].get("ts", ""))
        for k in oldest[:len(mem["projects"]) - MAX_PROJECTS]:
            del mem["projects"][k]


def recall_project(mem: dict, proj_key: str) -> dict:
    return dict(mem["projects"].get(proj_key, {}))


def project_key(hashes: dict[str, str]) -> str:
    """Stable matter identity: first 12 chars of the sorted content
    hashes joined — filename-independent, order-independent."""
    return "+".join(h[:12] for h in sorted(hashes.values()))[:200]


def prompt_snippet(mem: dict, scope: str,
                   proj_key: str | None = None) -> str:
    """<analyst_precedent> block for one AI call, hard-capped.

    Included: the voice bullets, the newest lessons for this scope
    (plus 'all'), and this matter's remembered elections. Empty memory
    returns "" so prompts are unchanged until something is remembered.
    """
    lines: list[str] = []
    for b in mem.get("voice", [])[:MAX_VOICE_BULLETS]:
        lines.append(f"- voice: {b}")
    for l in mem.get("lessons", []):
        if l.get("scope") in (scope, "all"):
            lines.append(f"- {l['text']}")
        if len(lines) >= 9:
            break
    if proj_key:
        proj = mem.get("projects", {}).get(proj_key, {})
        elec = {k: v for k, v in proj.items() if k != "ts"}
        if elec:
            lines.append("- this matter: " + "; ".join(
                f"{k}={v}" for k, v in sorted(elec.items()))[:200])
    if not lines:
        return ""
    body = "\n".join(lines)
    if len(body) > SNIPPET_CAP:
        body = body[:SNIPPET_CAP].rsplit("\n", 1)[0]
    return ("\n<analyst_precedent>Standing analyst preferences and "
            "confirmed precedent from earlier work — follow unless the "
            "data contradicts them; they never override the evidence "
            "rules:\n" + body + "\n</analyst_precedent>")
