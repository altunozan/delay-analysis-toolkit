"""Local project library & chain-of-custody register (SQLite, stdlib).

A small append-only store that survives Streamlit sessions:

* **Custody register** — every programme file registered is recorded with
  its SHA-256, size, data date and UTC registration time. Re-registering
  identical content is detected by hash and returns the original record,
  so the register can testify "this exact file, first seen on this date".
* **Analysis records** — JSON payloads (e.g. TIA audit records, saved
  event registers) keyed by project and kind.

Deliberately NOT a live connector to any P6/EPPM database: the forensic
unit of account is the as-submitted file with a hash, and this store
protects exactly that. Append-only by design — there is no delete API,
because a custody register that can forget is not a custody register.

Deployment note: on Streamlit Cloud the container filesystem is
EPHEMERAL — the library persists across reruns and sessions but not
across app restarts/redeploys. Its full value is realised locally and in
the portable/USB edition. This is surfaced via ``STORE_CAVEATS``.

Pure stdlib (sqlite3, hashlib, json); no new dependencies.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

DEFAULT_DB_PATH = os.path.join(
    os.path.expanduser("~"), ".delay_toolkit", "library.db")

STORE_CAVEATS = [
    "The library is append-only: files and analysis records can be "
    "added but not deleted or altered, so the register can serve as a "
    "chain-of-custody record.",
    "On Streamlit Cloud the filesystem is ephemeral — the library "
    "persists across sessions but NOT across app restarts or redeploys. "
    "For a durable register, run the toolkit locally or from the "
    "portable edition.",
    "Registration records when a file entered THIS library, not when it "
    "was created or exchanged between the parties.",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id                 INTEGER PRIMARY KEY,
    project            TEXT NOT NULL,
    file_name          TEXT NOT NULL,
    sha256             TEXT NOT NULL,
    size_bytes         INTEGER NOT NULL,
    data_date          TEXT,
    project_short_name TEXT,
    activity_count     INTEGER,
    added_utc          TEXT NOT NULL,
    UNIQUE (project, sha256)
);
CREATE TABLE IF NOT EXISTS analysis_records (
    id          INTEGER PRIMARY KEY,
    project     TEXT NOT NULL,
    kind        TEXT NOT NULL,
    label       TEXT NOT NULL,
    payload     TEXT NOT NULL,
    created_utc TEXT NOT NULL
);
"""


@dataclass
class FileRecord:
    id: int
    project: str
    file_name: str
    sha256: str
    size_bytes: int
    data_date: str | None
    project_short_name: str | None
    activity_count: int | None
    added_utc: str
    already_registered: bool = False   # True when dedup matched by hash


@dataclass
class AnalysisRecord:
    id: int
    project: str
    kind: str
    label: str
    payload: dict = field(default_factory=dict)
    created_utc: str = ""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class ProjectStore:
    """Append-only SQLite project library."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        parent = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(parent, exist_ok=True)
        with self._connect() as con:
            con.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    # ------------------------------------------------------------------ #
    # Files / custody register
    # ------------------------------------------------------------------ #

    def register_file(
        self,
        project: str,
        file_name: str,
        content: bytes,
        *,
        data_date: str | None = None,
        project_short_name: str | None = None,
        activity_count: int | None = None,
    ) -> FileRecord:
        """Register a file; identical content (by hash) is not duplicated."""
        sha = hashlib.sha256(content).hexdigest()
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM files WHERE project = ? AND sha256 = ?",
                (project, sha)).fetchone()
            if row is not None:
                rec = self._file_from_row(row)
                rec.already_registered = True
                return rec
            cur = con.execute(
                "INSERT INTO files (project, file_name, sha256, size_bytes,"
                " data_date, project_short_name, activity_count, added_utc)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (project, file_name, sha, len(content), data_date,
                 project_short_name, activity_count, _utc_now()))
            row = con.execute("SELECT * FROM files WHERE id = ?",
                              (cur.lastrowid,)).fetchone()
        return self._file_from_row(row)

    def custody_register(self, project: str | None = None) -> list[FileRecord]:
        """All registered files, oldest first (the register itself)."""
        q = "SELECT * FROM files"
        args: tuple = ()
        if project:
            q += " WHERE project = ?"
            args = (project,)
        q += " ORDER BY added_utc, id"
        with self._connect() as con:
            rows = con.execute(q, args).fetchall()
        return [self._file_from_row(r) for r in rows]

    def projects(self) -> list[str]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT DISTINCT project FROM files"
                " UNION SELECT DISTINCT project FROM analysis_records"
                " ORDER BY 1").fetchall()
        return [r[0] for r in rows]

    @staticmethod
    def _file_from_row(row: sqlite3.Row) -> FileRecord:
        return FileRecord(
            id=row["id"], project=row["project"],
            file_name=row["file_name"], sha256=row["sha256"],
            size_bytes=row["size_bytes"], data_date=row["data_date"],
            project_short_name=row["project_short_name"],
            activity_count=row["activity_count"],
            added_utc=row["added_utc"])

    # ------------------------------------------------------------------ #
    # Analysis records
    # ------------------------------------------------------------------ #

    def save_record(self, project: str, kind: str, label: str,
                    payload: dict) -> int:
        with self._connect() as con:
            cur = con.execute(
                "INSERT INTO analysis_records"
                " (project, kind, label, payload, created_utc)"
                " VALUES (?, ?, ?, ?, ?)",
                (project, kind, label,
                 json.dumps(payload, default=str), _utc_now()))
            return int(cur.lastrowid)

    def list_records(self, project: str | None = None,
                     kind: str | None = None) -> list[AnalysisRecord]:
        q = "SELECT * FROM analysis_records WHERE 1=1"
        args: list = []
        if project:
            q += " AND project = ?"
            args.append(project)
        if kind:
            q += " AND kind = ?"
            args.append(kind)
        q += " ORDER BY created_utc DESC, id DESC"
        with self._connect() as con:
            rows = con.execute(q, args).fetchall()
        out = []
        for r in rows:
            try:
                payload = json.loads(r["payload"])
            except (json.JSONDecodeError, TypeError):
                payload = {"_raw": r["payload"]}
            out.append(AnalysisRecord(
                id=r["id"], project=r["project"], kind=r["kind"],
                label=r["label"], payload=payload,
                created_utc=r["created_utc"]))
        return out
