"""Append-only three-layer persistence for the isolated module."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .domain import AnalysisRun, ExpertDecision, Layer
from .graph import EvidenceGraph, primitive


_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS graph_versions (
    graph_version TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    created_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id TEXT PRIMARY KEY,
    graph_version TEXT NOT NULL,
    ruleset_version TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_utc TEXT NOT NULL,
    FOREIGN KEY (graph_version) REFERENCES graph_versions(graph_version)
);
CREATE TABLE IF NOT EXISTS expert_decisions (
    decision_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    element_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_utc TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES analysis_runs(run_id)
);
"""


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class LayerStore:
    """No update/delete API: evidence, runs and decisions are append-only."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def save_graph(self, graph: EvidenceGraph) -> str:
        if not graph.sealed:
            raise ValueError("Only sealed evidence graphs may be persisted")
        payload = json.dumps(graph.to_dict(), sort_keys=True)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT payload_sha256 FROM graph_versions "
                "WHERE graph_version = ?", (graph.version,)
            ).fetchone()
            if existing and existing[0] != digest:
                raise ValueError("Stored graph version has different content")
            connection.execute(
                "INSERT OR IGNORE INTO graph_versions VALUES (?, ?, ?, ?)",
                (graph.version, payload, digest, _utc()),
            )
        return graph.version

    def save_run(self, run: AnalysisRun) -> str:
        payload = json.dumps(primitive(run), sort_keys=True)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO analysis_runs VALUES (?, ?, ?, ?, ?)",
                (run.run_id, run.graph_version, run.ruleset_version,
                 payload, _utc()),
            )
        return run.run_id

    def record_decision(
        self, run_id: str, decision: ExpertDecision
    ) -> str:
        if decision.layer is not Layer.CONCLUSION:
            raise ValueError("Only Layer 3 expert decisions belong here")
        payload = json.dumps(primitive(decision), sort_keys=True)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO expert_decisions VALUES (?, ?, ?, ?, ?)",
                (decision.decision_id, run_id, decision.element_id,
                 payload, _utc()),
            )
        return decision.decision_id

    def rejected_element_ids(self, run_id: str) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM expert_decisions WHERE run_id = ?",
                (run_id,),
            ).fetchall()
        rejected = set()
        for row in rows:
            payload: dict[str, Any] = json.loads(row[0])
            if payload.get("decision", "").lower() == "rejected":
                rejected.add(payload["element_id"])
        return rejected

