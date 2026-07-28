"""JSON deck autosave — replaces the pickle autosave (Bandit B301).

A tampered pickle executes arbitrary code the moment it is loaded; a
tampered JSON file is just a bad deck and loads as nothing. Slides are
dataclasses from ``specs`` (nested dataclasses, datetimes, Literals),
round-tripped with an explicit type discriminator against a registry
of KNOWN spec classes — anything outside the registry is refused, so
the file cannot smuggle in types it was never meant to hold.
"""

from __future__ import annotations

import dataclasses
import json
import os
from datetime import datetime

import specs as _specs

FORMAT_VERSION = 1

# Every dataclass defined in specs.py — the ONLY types a deck may hold.
_REGISTRY = {
    name: obj for name, obj in vars(_specs).items()
    if dataclasses.is_dataclass(obj) and isinstance(obj, type)
}


def _enc(o):
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return {"__type__": type(o).__name__,
                "fields": {f.name: _enc(getattr(o, f.name))
                           for f in dataclasses.fields(o)}}
    if isinstance(o, datetime):
        return {"__dt__": o.isoformat()}
    if isinstance(o, tuple):
        return {"__tuple__": [_enc(x) for x in o]}
    if isinstance(o, list):
        return [_enc(x) for x in o]
    if isinstance(o, (str, int, float, bool)) or o is None:
        return o
    raise TypeError(f"deck slide holds an unserialisable "
                    f"{type(o).__name__}")


def _dec(o):
    if isinstance(o, dict) and "__dt__" in o:
        return datetime.fromisoformat(o["__dt__"])
    if isinstance(o, dict) and "__tuple__" in o:
        return tuple(_dec(x) for x in o["__tuple__"])
    if isinstance(o, dict) and "__type__" in o:
        cls = _REGISTRY.get(o["__type__"])
        if cls is None:
            raise ValueError(f"unknown slide type: {o['__type__']!r}")
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: _dec(v) for k, v in o.get("fields", {}).items()
                      if k in known})
    if isinstance(o, list):
        return [_dec(x) for x in o]
    if isinstance(o, (str, int, float, bool)) or o is None:
        return o
    raise ValueError(f"unexpected node in autosave: {type(o).__name__}")


def save_deck(path: str, deck: list) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"version": FORMAT_VERSION,
                   "slides": [_enc(s) for s in deck]}, fh)


def load_deck(path: str) -> list:
    """The saved deck, or [] — a missing/stale/tampered file is never
    an exception and NEVER code execution."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        if doc.get("version") != FORMAT_VERSION:
            return []
        return [_dec(s) for s in doc.get("slides", [])]
    except Exception:  # noqa: BLE001 - any defect means an empty deck
        return []
