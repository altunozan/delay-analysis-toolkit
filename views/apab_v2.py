"""As-Planned vs As-Built v2 — Retrospective Longest Path Analysis.

Nine-step programme-only engine (rlpa_apvab_v2): fitness gates, blocked
candidate generation with binary admissibility gates, E1–E7 evidence and
H1–H5 symmetric hypothesis testing, first-class interruption nodes with
N1–N7 negative evidence, backward path query from an actual-dated
milestone, APvAB window comparison and migration.

Three-layer doctrine on the page: evidence tables are Layer 1, tier and
classification tables are Layer 2, and the analyst's rejections here are
Layer 3 — a rejection re-runs the path query over the same sealed
evidence graph; it never edits the evidence. The AI panel is role R-B
(narrative prose over completed Layer-2 output) and nothing else.
"""

from __future__ import annotations

import hashlib
import json

import pandas as pd
import streamlit as st

from rlpa_apvab_v2 import analyse, html_report, snapshot_from_xer_data
from rlpa_apvab_v2.config import RLPAConfig, UNCALIBRATED_STATEMENT
from rlpa_apvab_v2.domain import (
    ActivityNode,
    InterruptionClass,
    InterruptionNode,
    MilestoneNode,
    NodeKind,
)
from rlpa_apvab_v2.graph import primitive
from views._shared import ai_narrative_panel, fetch_raw, get_parsed_files

_RESULT_KEY = "apab_v2_result"
_SIG_KEY = "apab_v2_sig"
_REJECT_KEY = "apab_v2_rejections"

_CAVEATS = [
    "Retrospective Longest Path Analysis, programme data only — no "
    "correspondence, site records or external documents are read, and "
    "none may be inferred.",
    "The as-built critical path is INFERRED from execution; the "
    "as-planned path is CALCULATED from baseline logic. They are never "
    "presented on a common confidence scale.",
    "Interruptions are first-class elements of the path; an unexplained "
    "interruption is a finding, not a failure of the trace.",
    "Tier assignments are rule-derived and uncalibrated; they express "
    "the pattern of evidence assembled, not a validated likelihood.",
    "This is not an Impacted As-Planned, Time Impact, Collapsed "
    "As-Built, concurrency, apportionment or entitlement analysis.",
]

_NARRATIVE_TEMPLATE = """\
## As-Planned vs As-Built v2 — Programme-Derived Findings (RLPA)

### 1. Method and Reliability
State the method (Retrospective Longest Path Analysis, programme data
only), the files analysed, the fitness-gate results and the reliability
rating. Reproduce the calibration statement verbatim.

### 2. Probable As-Built Controlling Chain
The chain in order, naming each element (activity, interruption or
milestone) with its tier. Never average or sum tiers; name the weakest
links and why they are weak.

### 3. Unexplained Interruptions (headline)
Each unexplained interruption: workfront, period, working days, what was
excluded, the coverage qualification, and the specific question the
records must answer.

### 4. As-Planned versus As-Built Position
Where the executed chain diverged from the planned chain, per window,
with the divergence classification (execution / scope / logic /
artefact). State the as-planned health warning.

### 5. Contested Interpretations and Open Questions
Contest-flagged links with both cases stated neutrally, and every
question referred to the analyst.
"""


def _prompt(result, template: str) -> str:
    sections = {
        "run": primitive(result.run),
        "interruptions": primitive(result.interruption_interpretations),
        "review_items": list(result.review_items),
    }
    return (
        "You are drafting the narrative section of a forensic delay "
        "report over COMPLETED deterministic analysis output. Rules that "
        "override everything below: use only the figures and findings "
        "supplied; never invent activities, dates or causes; never "
        "express a tier as a probability or percentage; never combine "
        "tiers arithmetically; keep evidence, interpretation and "
        "analyst-referred questions in separate sentences; do not infer "
        "responsibility, entitlement or compensability; reproduce every "
        "stated limitation. Write in measured expert-report English.\n\n"
        "TEMPLATE TO FOLLOW:\n" + template + "\n\nDATA (JSON):\n"
        + json.dumps(sections, default=str)[:60000]
    )


def _node_row(graph, element):
    node = graph.nodes[element.node_id]
    if isinstance(node, InterruptionNode):
        return {
            "Order": element.order, "Type": "Interruption", "ID": "—",
            "Name / workfront": node.workfront,
            "Start": node.period_start, "Finish": node.period_end,
            "Working days": round(node.working_days, 1),
            "Tier": element.tier.value, "Basis": element.basis,
            "Cap": element.governing_cap or "",
        }
    if isinstance(node, MilestoneNode):
        return {
            "Order": element.order, "Type": "Milestone",
            "ID": node.task_code, "Name / workfront": node.name,
            "Start": node.actual_date, "Finish": node.actual_date,
            "Working days": 0.0, "Tier": element.tier.value,
            "Basis": element.basis, "Cap": element.governing_cap or "",
        }
    return {
        "Order": element.order, "Type": "Activity", "ID": node.task_code,
        "Name / workfront": node.original_name,
        "Start": node.actual_start, "Finish": node.actual_finish,
        "Working days": (round(node.actual_duration_working_days, 1)
                         if node.actual_duration_working_days is not None
                         else None),
        "Tier": element.tier.value, "Basis": element.basis,
        "Cap": element.governing_cap or "",
    }


def _code(graph, node_id: str) -> str:
    node = graph.nodes.get(node_id)
    return getattr(node, "task_code", None) or getattr(
        node, "workfront", node_id)


def apab_v2_tab() -> None:
    st.header("As-Planned vs As-Built v2 — Retrospective Longest Path")
    st.caption(
        "Programme-only reconstruction of the probable as-built critical "
        "path — actual work AND actual interruption — compared against "
        "the planned path across windows. Assembled evidence with a "
        "provisional reading, for adoption, adjustment or rejection."
    )

    files = get_parsed_files()
    if not files:
        st.info("Upload XER files on the **Data Intake** page first. "
                "Supply the baseline plus updates/as-built for the full "
                "nine steps; a single as-built still yields the "
                "interruption register and path.")
        return

    names = [n for n, _ in files]
    chosen = st.multiselect(
        "Programmes to analyse (the engine orders them by data date; "
        "earliest becomes the baseline, latest the as-built)",
        names, default=names, key="apab_v2_files")
    if not chosen:
        st.warning("Select at least one programme.")
        return

    final_name = chosen[-1]
    final_data = dict(files)[final_name]
    milestone_options = ["(automatic — highest-ranked actual-dated "
                         "completion milestone)"]
    milestone_codes: list[str | None] = [None]
    for t in final_data.tasks:
        if t.is_milestone and (t.act_finish or t.act_start):
            milestone_options.append(f"{t.task_code} — {t.name}")
            milestone_codes.append(t.task_code)
    anchor_pick = st.selectbox(
        "Trace anchor (completion milestone with an actual date)",
        range(len(milestone_options)),
        format_func=lambda i: milestone_options[i],
        key="apab_v2_anchor",
        help="Do not assume the latest milestone is the contractual one — "
             "elect it explicitly where the programme does not say.")
    anchor_code = milestone_codes[anchor_pick]

    rejections: set[str] = set(st.session_state.get(_REJECT_KEY, []))
    sig = hashlib.sha256(json.dumps(
        [chosen, anchor_code, sorted(rejections)]
    ).encode()).hexdigest()

    if st.button("Run RLPA assessment", type="primary", key="apab_v2_go") \
            or (st.session_state.get(_SIG_KEY) == sig
                and _RESULT_KEY in st.session_state):
        if st.session_state.get(_SIG_KEY) != sig:
            snapshots = []
            with st.spinner("Running the nine-step assessment…"):
                for name in chosen:
                    data = dict(files)[name]
                    raw = fetch_raw(name) or name.encode("utf-8")
                    snapshots.append(snapshot_from_xer_data(
                        data, filename=name, content=raw))
                result = analyse(
                    snapshots, anchor_task_code=anchor_code,
                    rejected_element_ids=rejections,
                )
            st.session_state[_RESULT_KEY] = result
            st.session_state[_SIG_KEY] = sig
        result = st.session_state[_RESULT_KEY]
    else:
        st.stop()
        return

    run = result.run
    st.warning("**Calibration status.** " + UNCALIBRATED_STATEMENT)

    # ---- Step 1: fitness (Layer 1) ----
    st.subheader("Fitness gates — Layer 1")
    left, right = st.columns([3, 1])
    with left:
        st.dataframe(pd.DataFrame([{
            "Gate": g.gate, "Status": g.status.value,
            "Measured": g.measured, "Threshold": g.threshold,
            "Consequence on failure": g.consequence,
        } for g in run.fitness.gates]), width="stretch", hide_index=True)
    with right:
        st.metric("Reliability", run.fitness.reliability)
        st.caption("Graph version: `" + run.graph_version[:16] + "…`")

    # ---- Step 5: unexplained interruption register (headline) ----
    st.subheader("Unexplained interruption register — headline output")
    rows = []
    for item in result.interruption_interpretations:
        node = result.graph.nodes[item.interruption_node_id]
        bundle = result.graph.negative_bundles.get(
            node.negative_evidence_bundle_id)
        pattern = " ".join(
            f"{f.reference}:{f.state.value[:4]}" for f in bundle.factors
        ) if bundle else ""
        rows.append({
            "Class": item.classification.value,
            "Workfront": node.workfront,
            "From": node.period_start, "To": node.period_end,
            "Working days": round(node.working_days, 1),
            "Bounded by": (_code(result.graph,
                                 node.bounding_predecessor_node_id)
                           + " → "
                           + _code(result.graph,
                                   node.bounding_successor_node_id)),
            "Candidates tested": len(node.candidate_population),
            "N1–N7": pattern,
            "Coverage": item.coverage_qualification,
            "Completion correspondence": item.completion_correspondence,
            "Discriminating question": item.discriminating_question,
            "Priority": item.review_priority.value,
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        st.caption("**Evidence** (workfront, period, exclusions) is Layer 1; "
                   "**classification and tier** are Layer 2; the "
                   "**discriminating question** is referred to the analyst.")
    else:
        st.info("No reportable interruptions at the configured threshold.")

    # ---- Step 6: derived path (Layer 2) ----
    st.subheader("Probable as-built controlling chain — Layer 2")
    if run.path:
        st.dataframe(pd.DataFrame([
            _node_row(result.graph, e) for e in run.path.elements
        ]), width="stretch", hide_index=True)
        tiers = [e.tier.value for e in run.path.elements]
        profile = {t: tiers.count(t) for t in dict.fromkeys(tiers)}
        st.caption(
            f"Chain of {len(tiers)} elements — "
            + ", ".join(f"{v}× {k}" for k, v in profile.items())
            + f". Weakest link: {run.path.weakest_tier.value}. "
            "Weakest-link characterisation only; tiers are never averaged. "
            f"Query: {run.path.query_definition}")
    else:
        st.error("Path derivation suppressed by the fitness gates "
                 "(see consequences above).")

    # ---- Step 4: contested register ----
    contested = [c for c in result.candidate_interpretations
                 if c.admissible and c.contest_flag]
    with st.expander(f"Contested relationship register "
                     f"({len(contested)} link(s)) — Layer 2"):
        for c in contested[:80]:
            succ = _code(result.graph, c.successor_node_id)
            pred = _code(result.graph, c.predecessor_node_id)
            st.markdown(
                f"**{succ} ← {pred}** — {c.tier.value}, margin "
                f"{c.uniqueness_margin}. {c.alternative_comparison}")
            bundle = (result.graph.evidence_bundles.get(c.evidence_bundle_id)
                      if c.evidence_bundle_id else None)
            if bundle:
                st.caption("Evidence: " + "; ".join(
                    f"{f.reference} {f.state.value}: {f.observation}"
                    for f in bundle.factors))
            st.caption("Hypotheses: " + "; ".join(
                f"{h.reference} {'VIABLE' if h.viable else 'excluded'}"
                for h in c.hypotheses)
                + ((" — caps: " + "; ".join(c.caps_applied))
                   if c.caps_applied else ""))
            st.caption("For the analyst: " + c.discriminating_question)

    # ---- Steps 7–8: windows and migration ----
    if run.windows:
        st.subheader("APvAB window comparison — Layer 2")
        st.dataframe(pd.DataFrame([{
            "Window": w.window_id, "From": w.start, "To": w.end,
            "As-built path within window":
                " → ".join(w.probable_as_built_path) or "—",
            "Movement (wd)": w.completion_movement_working_days,
            "Displaced from planned":
                ", ".join(w.displaced_from_planned[:12]),
            "Entered as-built": ", ".join(w.entered_as_built[:12]),
            "Divergence": w.divergence.value, "Tier": w.tier.value,
            "Suppressed": w.suppression_reason or "",
        } for w in run.windows]), width="stretch", hide_index=True)
    if run.migrations:
        st.dataframe(pd.DataFrame([{
            "Window": m.window_id, "From": m.previous_controlling_path,
            "To": m.new_controlling_path, "Point": m.migration_point,
            "Artefact/Execution": m.artefact_or_execution,
            "Explanation": m.explanation,
        } for m in run.migrations]), width="stretch", hide_index=True)

    # ---- Layer 3: expert adoption gate ----
    st.subheader("Expert adoption — Layer 3")
    st.caption(
        "Rejecting an interpretation re-runs the path query over the "
        "same sealed evidence graph — the engine's original reading "
        "remains disclosable beside yours.")
    rejectable = {
        f"{_code(result.graph, c.successor_node_id)} ← "
        f"{_code(result.graph, c.predecessor_node_id)} ({c.tier.value})":
        c.interpretation_id
        for c in result.candidate_interpretations if c.admissible
    }
    picked = st.multiselect(
        "Interpretations to reject", list(rejectable),
        default=[k for k, v in rejectable.items() if v in rejections],
        key="apab_v2_reject_pick")
    if st.button("Apply rejections and re-run the path query",
                 key="apab_v2_reject_go"):
        st.session_state[_REJECT_KEY] = sorted(
            rejectable[k] for k in picked)
        st.session_state.pop(_SIG_KEY, None)
        st.rerun()

    # ---- warnings + downloads ----
    if run.warnings:
        with st.expander(f"Limitations and warnings ({len(run.warnings)})"):
            for w in dict.fromkeys(run.warnings):
                st.write("•", w)
    with st.expander("Standing caveats (always apply)"):
        for c in _CAVEATS:
            st.write("•", c)

    d1, d2, d3 = st.columns(3)
    d1.download_button(
        "⬇️ Full HTML report (layer-separated)",
        data=html_report(result).encode("utf-8"),
        file_name="rlpa_apvab_v2_report.html", mime="text/html",
        key="apab_v2_dl_html")
    d2.download_button(
        "⬇️ Evidence graph (JSON)",
        data=json.dumps(result.graph.to_dict(), indent=1,
                        sort_keys=True).encode("utf-8"),
        file_name="rlpa_evidence_graph.json", mime="application/json",
        key="apab_v2_dl_graph")
    d3.download_button(
        "⬇️ Analysis run + audit (JSON)",
        data=json.dumps(primitive(run), indent=1,
                        sort_keys=True).encode("utf-8"),
        file_name="rlpa_analysis_run.json", mime="application/json",
        key="apab_v2_dl_run")

    ai_narrative_panel(
        "nar_apab_v2",
        lambda tmpl: _prompt(result, tmpl),
        "apab_v2",
        _NARRATIVE_TEMPLATE,
    )
