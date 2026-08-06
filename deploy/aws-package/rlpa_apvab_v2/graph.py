"""Evidence graph with an explicit immutability boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any, cast

from .domain import (
    ActivityNode,
    BoundingEdge,
    CandidateInterpretation,
    EvidenceBundle,
    GenealogyEdge,
    InterruptionInterpretation,
    InterruptionNode,
    MilestoneNode,
    NegativeEvidenceBundle,
    SequenceEdge,
)


def primitive(value: Any) -> Any:
    """Return a deterministic JSON-safe representation."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {
            key: primitive(item)
            for key, item in asdict(cast(Any, value)).items()
        }
    if isinstance(value, dict):
        return {str(key): primitive(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [primitive(item) for item in value]
    return value


class EvidenceGraph:
    """In-memory graph whose Layer 1/2 contents become immutable on seal."""

    def __init__(self) -> None:
        self.nodes: dict[str, ActivityNode | MilestoneNode | InterruptionNode] = {}
        self.edges: dict[str, SequenceEdge | BoundingEdge | GenealogyEdge] = {}
        self.evidence_bundles: dict[str, EvidenceBundle] = {}
        self.negative_bundles: dict[str, NegativeEvidenceBundle] = {}
        self.interpretations: dict[str, CandidateInterpretation] = {}
        self.interruption_interpretations: dict[
            str, InterruptionInterpretation
        ] = {}
        self._sealed = False
        self._version: str | None = None

    def _assert_open(self) -> None:
        if self._sealed:
            raise RuntimeError(
                "The evidence graph is sealed; Layer 1 and Layer 2 cannot "
                "be mutated. Create a new ruleset run instead."
            )

    @staticmethod
    def _insert(target: dict[str, Any], key: str, value: Any) -> None:
        if key in target:
            if primitive(target[key]) != primitive(value):
                raise ValueError(f"Graph identity collision for '{key}'")
            return
        target[key] = value

    def add_node(
        self, node: ActivityNode | MilestoneNode | InterruptionNode
    ) -> None:
        self._assert_open()
        self._insert(self.nodes, node.node_id, node)

    def add_edge(
        self, edge: SequenceEdge | BoundingEdge | GenealogyEdge
    ) -> None:
        self._assert_open()
        self._insert(self.edges, edge.edge_id, edge)

    def add_evidence_bundle(self, bundle: EvidenceBundle) -> None:
        self._assert_open()
        self._insert(self.evidence_bundles, bundle.bundle_id, bundle)

    def add_negative_bundle(self, bundle: NegativeEvidenceBundle) -> None:
        self._assert_open()
        self._insert(self.negative_bundles, bundle.bundle_id, bundle)

    def add_interpretation(self, item: CandidateInterpretation) -> None:
        self._assert_open()
        self._insert(self.interpretations, item.interpretation_id, item)

    def add_interruption_interpretation(
        self, item: InterruptionInterpretation
    ) -> None:
        self._assert_open()
        self._insert(
            self.interruption_interpretations, item.interpretation_id, item
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": primitive(self.nodes),
            "edges": primitive(self.edges),
            "evidence_bundles": primitive(self.evidence_bundles),
            "negative_evidence_bundles": primitive(self.negative_bundles),
            "candidate_interpretations": primitive(self.interpretations),
            "interruption_interpretations": primitive(
                self.interruption_interpretations
            ),
        }

    def seal(self) -> str:
        payload = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        self._version = hashlib.sha256(payload).hexdigest()
        self._sealed = True
        return self._version

    @property
    def version(self) -> str:
        if self._version is None:
            raise RuntimeError("Seal the graph before requesting its version")
        return self._version

    @property
    def sealed(self) -> bool:
        return self._sealed
