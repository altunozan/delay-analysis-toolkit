"""Layer-separated JSON, CSV and HTML report bundle."""

from __future__ import annotations

import csv
import hashlib
import html
import json
from pathlib import Path
from typing import Any, Iterable

from .domain import ActivityNode, InterruptionNode, Layer, MilestoneNode
from .engine import PipelineResult
from .graph import primitive


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(primitive(value), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _row(value: Any) -> dict[str, Any]:
    result = primitive(value)
    if not isinstance(result, dict):
        return {"value": result}
    return {
        key: json.dumps(item, ensure_ascii=False)
        if isinstance(item, (dict, list)) else item
        for key, item in result.items()
    }


def _write_csv(path: Path, values: Iterable[Any], headers=()) -> None:
    rows = [_row(value) for value in values]
    fieldnames = list(headers)
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    if not fieldnames:
        fieldnames = ["no_records"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _node_label(node: Any) -> str:
    if isinstance(node, ActivityNode):
        return f"{node.task_code} — {node.original_name}"
    if isinstance(node, MilestoneNode):
        return f"{node.task_code} — {node.name}"
    if isinstance(node, InterruptionNode):
        return (
            f"Interruption — {node.workfront}, "
            f"{node.working_days:.2f} working days"
        )
    return getattr(node, "node_id", "unknown")


def html_report(result: PipelineResult) -> str:
    run = result.run
    fitness_rows = "".join(
        "<tr>" + "".join(
            f"<td>{html.escape(str(value))}</td>" for value in (
                gate.gate, gate.status.value, gate.measured,
                gate.threshold, gate.consequence,
            )
        ) + "</tr>" for gate in run.fitness.gates
    )
    path_rows = ""
    if run.path:
        for element in run.path.elements:
            node = result.graph.nodes[element.node_id]
            # Evidence and interpretation are visibly separate blocks.
            path_rows += (
                "<section class='path-element'>"
                f"<h3>{element.order}. {html.escape(_node_label(node))}</h3>"
                "<div class='evidence'><strong>Layer 1 — Evidence</strong>"
                f"<pre>{html.escape(json.dumps(primitive(node), indent=2))}</pre>"
                "</div>"
                "<div class='interpretation'>"
                "<strong>Layer 2 — Interpretation</strong>"
                f"<p>Tier: {html.escape(element.tier.value)}. "
                f"Basis: {html.escape(element.basis)}. "
                f"Cap: {html.escape(element.governing_cap or 'none')}.</p>"
                "</div></section>"
            )
    interruption_rows = "".join(
        f"<tr><td>{html.escape(item.interruption_node_id)}</td>"
        f"<td>{html.escape(item.classification.value)}</td>"
        f"<td>{html.escape(item.tier.value)}</td>"
        f"<td>{html.escape(item.coverage_qualification)}</td>"
        f"<td>{html.escape(item.discriminating_question)}</td></tr>"
        for item in result.interruption_interpretations
    )
    warnings = "".join(
        f"<li>{html.escape(item)}</li>" for item in run.warnings
    ) or "<li>None recorded.</li>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>RLPA / APvAB v2 — {html.escape(run.run_id)}</title>
<style>
body{{font:15px/1.45 system-ui,sans-serif;max-width:1180px;margin:2rem auto;padding:0 1rem;color:#18202a}}
h1,h2{{color:#123b5d}} table{{border-collapse:collapse;width:100%;margin:1rem 0}}
th,td{{border:1px solid #ccd4dc;padding:.45rem;vertical-align:top;text-align:left}}
.notice{{background:#fff4cf;border-left:5px solid #b38300;padding:1rem}}
.evidence{{background:#edf6ff;padding:.8rem;margin:.5rem 0}} .interpretation{{background:#f5efff;padding:.8rem}}
pre{{white-space:pre-wrap;max-height:22rem;overflow:auto}} .path-element{{border-bottom:2px solid #dde3e8;padding:.7rem 0}}
</style></head><body>
<h1>Programme-Derived RLPA / APvAB v2</h1>
<p><strong>Method:</strong> Retrospective Longest Path Analysis, programme data only.</p>
<p><strong>Run:</strong> {html.escape(run.run_id)} &nbsp; <strong>Graph:</strong> {html.escape(run.graph_version)}</p>
<p><strong>Reliability:</strong> {html.escape(run.fitness.reliability)} &nbsp; <strong>Operating mode:</strong> {html.escape(run.model_access.operating_mode.value)}</p>
<div class="notice"><strong>Calibration status.</strong> {html.escape(run.calibration_statement)}</div>
<h2>Fitness gates — Layer 1</h2>
<table><thead><tr><th>Gate</th><th>Status</th><th>Measured</th><th>Threshold</th><th>Consequence</th></tr></thead><tbody>{fitness_rows}</tbody></table>
<h2>Probable controlling chain</h2>
{path_rows or '<p>Suppressed or indeterminate under the fitness gates.</p>'}
<h2>Interruption interpretations — Layer 2</h2>
<table><thead><tr><th>Element</th><th>Classification</th><th>Tier</th><th>Coverage</th><th>Question</th></tr></thead><tbody>{interruption_rows}</tbody></table>
<h2>Limitations and warnings</h2><ul>{warnings}</ul>
<div class="notice"><strong>Limitation.</strong> This is an initial programme-only assessment. It does not establish factual cause, access, resources, contractual responsibility, entitlement, compensability or concurrency. It is not an expert opinion.</div>
</body></html>"""


def report_sections(result: PipelineResult) -> list[dict[str, str]]:
    """Neutral adapter shape consumable by the toolkit's report assembler."""
    run = result.run
    path_text = "Suppressed or indeterminate."
    if run.path:
        path_text = " → ".join(
            _node_label(result.graph.nodes[item.node_id])
            for item in run.path.elements
        )
    return [
        {
            "title": "RLPA / APvAB v2 — Programme-Derived Conclusion",
            "body": (
                f"Method: Retrospective Longest Path Analysis, programme "
                f"data only. Reliability: {run.fitness.reliability}. "
                f"Graph/query: {run.graph_version} / "
                f"{run.path.query_definition if run.path else 'suppressed'}."
            ),
            "layer": Layer.INTERPRETATION.value,
        },
        {
            "title": "Probable as-built controlling chain",
            "body": path_text,
            "layer": Layer.INTERPRETATION.value,
        },
        {
            "title": "Calibration and limitation",
            "body": (
                run.calibration_statement + " This is not a concurrency, "
                "entitlement or compensability assessment."
            ),
            "layer": Layer.INTERPRETATION.value,
        },
    ]


def write_report_bundle(
    result: PipelineResult, output_directory: str | Path
) -> Path:
    """Write a reproducible bundle; returns the HTML entry point."""
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    layer1 = output / "layer_1_evidence"
    layer2 = output / "layer_2_interpretation"
    layer3 = output / "layer_3_expert_conclusion"
    for directory in (layer1, layer2, layer3):
        directory.mkdir(exist_ok=True)

    _write_json(output / "analysis_run.json", result.run)
    _write_json(output / "evidence_graph.json", result.graph.to_dict())
    _write_json(output / "report_sections.json", report_sections(result))
    _write_json(output / "audit.json", {
        "run": result.run,
        "graph_version": result.graph.version,
        "path_query": result.run.path.query_definition
        if result.run.path else None,
        "provisional_gap_count": result.provisional_gap_count,
        "review_items": result.review_items,
        "determinism_statement": (
            "Identical inputs, ruleset, configuration and Layer 3 overlay "
            "produce identical Layer 1, Layer 2 and graph version."
        ),
    })

    activities = [node for node in result.graph.nodes.values()
                  if isinstance(node, ActivityNode)]
    milestones = [node for node in result.graph.nodes.values()
                  if isinstance(node, MilestoneNode)]
    interruptions = [node for node in result.graph.nodes.values()
                     if isinstance(node, InterruptionNode)]
    _write_csv(layer1 / "activity_register.csv", activities)
    _write_csv(layer1 / "milestone_register.csv", milestones)
    _write_csv(layer1 / "interruption_evidence.csv", interruptions)
    _write_csv(
        layer1 / "relationship_evidence_bundles.csv",
        result.graph.evidence_bundles.values(),
    )
    _write_csv(
        layer1 / "negative_evidence_bundles.csv",
        result.graph.negative_bundles.values(),
    )
    _write_csv(
        layer2 / "candidate_and_exclusion_register.csv",
        result.candidate_interpretations,
    )
    _write_csv(
        layer2 / "interruption_interpretations.csv",
        result.interruption_interpretations,
    )
    _write_csv(
        layer2 / "as_built_path_interpretation.csv",
        result.run.path.elements if result.run.path else (),
    )
    _write_csv(layer2 / "window_comparison.csv", result.run.windows)
    _write_csv(layer2 / "migration_register.csv", result.run.migrations)
    _write_csv(layer2 / "expert_review_register.csv", result.review_items)
    _write_csv(
        layer3 / "expert_decision_log_template.csv", (),
        headers=(
            "element", "engine_interpretation", "expert_decision",
            "reason", "analyst", "timestamp", "downstream_regeneration",
        ),
    )
    index = output / "index.html"
    index.write_text(html_report(result), encoding="utf-8")

    manifest: dict[str, dict[str, Any]] = {}
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path.name == "MANIFEST.json":
            continue
        content = path.read_bytes()
        manifest[str(path.relative_to(output))] = {
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
    _write_json(output / "MANIFEST.json", manifest)
    return index
