"""RLPA / APvAB v2 pipeline tests (ported from the qa tree and extended).

Runs standalone (python3 test_rlpa.py) or under pytest. The synthetic
fixture is a small completed programme with a deliberate 9-working-day
unexplained interruption between cable installation and testing.
"""

from __future__ import annotations

import json
from datetime import datetime

from dcma.models import Calendar, Project, Relationship, Task
from dcma.xer_parser import XerData
from rlpa_apvab_v2 import (
    analyse,
    rerun_with_rejections,
    snapshot_from_xer_data,
    write_report_bundle,
)
from rlpa_apvab_v2.domain import (
    ActivityNode,
    EvidenceState,
    InterruptionClass,
    Layer,
    NodeKind,
)


def dt(day: int) -> datetime:
    return datetime(2026, 1, day, 8, 0)


def task(
    task_id: str,
    code: str,
    name: str,
    start: int,
    finish: int,
    *,
    milestone: bool = False,
) -> Task:
    return Task(
        task_id=task_id,
        task_code=code,
        name=name,
        task_type="TT_FinMile" if milestone else "TT_Task",
        status="TK_Complete",
        clndr_id="CAL-1",
        target_drtn_hr=0.0 if milestone else (finish - start) * 8.0,
        remain_drtn_hr=0.0,
        total_float_hr=0.0,
        free_float_hr=0.0,
        early_start=dt(start),
        early_finish=dt(finish),
        late_start=dt(start),
        late_finish=dt(finish),
        act_start=dt(start),
        act_finish=dt(finish),
        target_start=dt(start),
        target_finish=dt(finish),
        cstr_type="",
        cstr_date=None,
        cstr_type2="",
        cstr_date2=None,
    )


def build_snapshot(tasks: list[Task], rels: list[Relationship],
                   *, data_date: int = 18, content: bytes = b"synthetic-v1",
                   filename: str = "synthetic-as-built.xer",
                   sched_options: dict | None = None):
    raw_task = []
    for item in tasks:
        raw_task.append({
            "proj_id": "P1",
            "task_id": item.task_id,
            "task_code": item.task_code,
            "task_name": item.name,
            "task_type": item.task_type,
            "status_code": item.status,
            "clndr_id": "CAL-1",
            "wbs_id": "W1",
            "act_start_date": item.act_start.strftime("%Y-%m-%d %H:%M"),
            "act_end_date": item.act_finish.strftime("%Y-%m-%d %H:%M"),
            "target_start_date": item.target_start.strftime("%Y-%m-%d %H:%M"),
            "target_end_date": item.target_finish.strftime("%Y-%m-%d %H:%M"),
            "target_drtn_hr_cnt": str(item.target_drtn_hr),
            "remain_drtn_hr_cnt": "0",
            "total_float_hr_cnt": "0",
            "free_float_hr_cnt": "0",
            "critical_path_flag": "Y",
        })
    actv_types = [
        {"actv_code_type_id": "T-LOC", "actv_code_type": "Location"},
        {"actv_code_type_id": "T-DIS", "actv_code_type": "Discipline"},
        {"actv_code_type_id": "T-SYS", "actv_code_type": "System"},
        {"actv_code_type_id": "T-PAR", "actv_code_type": "Responsible Party"},
    ]
    actv_codes = [
        {"actv_code_id": "C-LOC", "actv_code_type_id": "T-LOC",
         "actv_code_name": "Zone A"},
        {"actv_code_id": "C-DIS", "actv_code_type_id": "T-DIS",
         "actv_code_name": "Electrical"},
        {"actv_code_id": "C-SYS", "actv_code_type_id": "T-SYS",
         "actv_code_name": "Power"},
        {"actv_code_id": "C-PAR", "actv_code_type_id": "T-PAR",
         "actv_code_name": "SC-01"},
    ]
    assignments = [
        {"task_id": item.task_id, "actv_code_type_id": type_id,
         "actv_code_id": code_id}
        for item in tasks
        for type_id, code_id in (
            ("T-LOC", "C-LOC"), ("T-DIS", "C-DIS"),
            ("T-SYS", "C-SYS"), ("T-PAR", "C-PAR"),
        )
    ]
    options = sched_options or {
        "sched_retained_logic": "Y",
        "sched_progress_override": "N",
        "sched_float_type": "FT_FF",
        "sched_calendar_on_relationship_lag": "rcal_Predecessor",
    }
    data = XerData(
        header=["ERMHDR", "Synthetic P6"],
        raw_tables={
            "PROJECT": [{
                "proj_id": "P1", "proj_short_name": "Synthetic RLPA",
                "last_recalc_date": dt(data_date).strftime("%Y-%m-%d %H:%M"),
            }],
            "TASK": raw_task,
            "TASKPRED": [
                {"pred_task_id": rel.pred_task_id, "task_id": rel.task_id,
                 "pred_type": rel.pred_type, "lag_hr_cnt": "0"}
                for rel in rels
            ],
            "CALENDAR": [{
                "clndr_id": "CAL-1", "clndr_name": "Seven Day",
                "day_hr_cnt": "8", "clndr_data": "",
            }],
            "PROJWBS": [{
                "wbs_id": "W1", "wbs_name": "Zone A Electrical",
                "parent_wbs_id": "", "proj_node_flag": "N",
            }],
            "ACTVTYPE": actv_types,
            "ACTVCODE": actv_codes,
            "TASKACTV": assignments,
            "SCHEDOPTIONS": [options],
        },
        projects=[Project(
            "P1", "Synthetic RLPA", dt(1), None, dt(data_date), dt(data_date)
        )],
        tasks=tasks,
        relationships=rels,
        calendars={"CAL-1": Calendar("CAL-1", "Seven Day", 8.0)},
        tasks_by_id={item.task_id: item for item in tasks},
    )
    return snapshot_from_xer_data(
        data,
        filename=filename,
        content=content,
        declared_programme_type="as-built",
    )


def synthetic_snapshot():
    tasks = [
        task("1", "A-100", "Cable Installation Zone A", 1, 5),
        task("2", "A-200", "Electrical Testing Zone A", 15, 16),
        task("3", "A-300", "Commissioning Zone A", 17, 18),
        task("4", "PC-001", "Project Completion Zone A", 18, 18,
             milestone=True),
    ]
    rels = [
        Relationship("1", "2", "PR_FS", 0.0),
        Relationship("2", "3", "PR_FS", 0.0),
        Relationship("3", "4", "PR_FS", 0.0),
    ]
    return build_snapshot(tasks, rels)


def test_pipeline_builds_path_with_first_class_interruption():
    result = analyse([synthetic_snapshot()], anchor_task_code="PC-001")

    assert result.run.fitness.gate("F1").status.value == "pass"
    assert result.run.path is not None
    kinds = [element.element_type for element in result.run.path.elements]
    assert NodeKind.INTERRUPTION in kinds
    assert kinds[-1] is NodeKind.MILESTONE
    assert any(
        item.classification in {
            InterruptionClass.UNEXPLAINED,
            InterruptionClass.UNEXPLAINED_WITHIN_COVERAGE,
        }
        for item in result.interruption_interpretations
    )
    assert result.run.windows == ()  # one programme cannot evidence windows


def test_graph_is_deterministic_and_sealed():
    snapshot = synthetic_snapshot()
    first = analyse([snapshot], anchor_task_code="PC-001")
    second = analyse([snapshot], anchor_task_code="PC-001")

    assert first.graph.version == second.graph.version
    assert first.run.run_id == second.run.run_id
    try:
        first.graph.add_node(next(iter(snapshot.activity_nodes.values())))
        raise AssertionError("sealed graph accepted a mutation")
    except RuntimeError:
        pass


def test_numeric_candidate_ranking_never_reaches_output():
    result = analyse([synthetic_snapshot()], anchor_task_code="PC-001")
    serialised = json.dumps(result.graph.to_dict()).lower()

    assert '"score"' not in serialised
    assert "confidence_percent" not in serialised
    assert "probability" not in serialised
    assert all(item.layer is Layer.INTERPRETATION
               for item in result.candidate_interpretations)


def test_report_bundle_physically_separates_layers(tmp_path=None):
    import tempfile
    from pathlib import Path
    base = Path(tempfile.mkdtemp()) if tmp_path is None else tmp_path
    result = analyse([synthetic_snapshot()], anchor_task_code="PC-001")
    index = write_report_bundle(result, base / "bundle")

    assert index.exists()
    assert (index.parent / "layer_1_evidence" / "activity_register.csv").exists()
    assert (index.parent / "layer_2_interpretation" /
            "candidate_and_exclusion_register.csv").exists()
    assert (index.parent / "layer_3_expert_conclusion" /
            "expert_decision_log_template.csv").exists()
    assert (index.parent / "MANIFEST.json").exists()


def test_layer_three_rejection_regenerates_path_not_evidence():
    result = analyse([synthetic_snapshot()], anchor_task_code="PC-001")
    assert result.run.path is not None
    anchor_activity = next(
        node for node in result.graph.nodes.values()
        if isinstance(node, ActivityNode) and node.task_code == "PC-001"
    )
    selected = max(
        (item for item in result.candidate_interpretations
         if item.successor_node_id == anchor_activity.node_id
         and item.admissible),
        key=lambda item: item.tier.rank,
    )

    revised = rerun_with_rejections(result, {selected.interpretation_id})

    assert revised.graph.version == result.graph.version
    assert revised.run.run_id != result.run.run_id
    assert revised.run.path is not None
    assert revised.run.path.elements != result.run.path.elements


def test_interval_union_gap_detection():
    """An overlapping chain must suppress the false gap behind it: the
    workfront is idle only when NO activity is in progress."""
    tasks = [
        task("1", "B-100", "Cable Installation Zone A", 1, 5),
        # Overlaps 1 and runs to day 10 — the workfront is busy to day 10.
        task("2", "B-150", "Containment Installation Zone A", 3, 10),
        task("3", "B-200", "Electrical Testing Zone A", 12, 13),
        task("4", "PC-001", "Completion Zone A", 13, 13, milestone=True),
    ]
    rels = [
        Relationship("1", "3", "PR_FS", 0.0),
        Relationship("2", "3", "PR_FS", 0.0),
        Relationship("3", "4", "PR_FS", 0.0),
    ]
    result = analyse([build_snapshot(tasks, rels, data_date=13)],
                     anchor_task_code="PC-001")
    interruption_nodes = [
        node for node in result.graph.nodes.values()
        if node.kind is NodeKind.INTERRUPTION
    ]
    # Exactly one true idle period: day 10 → day 12, bounded by the
    # LATEST finisher (B-150), not the earlier-starting B-100.
    assert interruption_nodes, "true idle period not detected"
    for node in interruption_nodes:
        assert node.period_start >= dt(10), (
            "false gap reported behind an overlapping activity"
        )


def test_e5_suppressed_across_scheduling_option_boundary():
    """R9: a retained-logic → progress-override change between updates
    invalidates cross-boundary movement inference; E5 must not be
    asserted as Present across it."""
    def snap(data_date, content, options):
        tasks = [
            task("1", "A-100", "Cable Installation Zone A", 1, 5),
            task("2", "A-200", "Electrical Testing Zone A", 15, 16),
            task("3", "A-300", "Commissioning Zone A", 17, 18),
            task("4", "PC-001", "Completion Zone A", 18, 18, milestone=True),
        ]
        rels = [
            Relationship("1", "2", "PR_FS", 0.0),
            Relationship("2", "3", "PR_FS", 0.0),
            Relationship("3", "4", "PR_FS", 0.0),
        ]
        return build_snapshot(
            tasks, rels, data_date=data_date, content=content,
            filename=f"update-{data_date}.xer", sched_options=options,
        )

    retained = {"sched_retained_logic": "Y", "sched_progress_override": "N"}
    override = {"sched_retained_logic": "N", "sched_progress_override": "Y"}
    result = analyse(
        [snap(10, b"u1", retained), snap(18, b"u2", override)],
        anchor_task_code="PC-001",
    )
    for bundle in result.graph.evidence_bundles.values():
        e5 = bundle.factor("E5")
        assert e5.state is not EvidenceState.PRESENT, (
            "E5 asserted Present across a scheduling-option boundary"
        )
        assert "scheduling-option boundary" in e5.observation


def test_n6_completion_correspondence_with_update_pair():
    """With an update pair covering the interruption and consistent
    scheduling options, N6 must actually be tested (not not-applicable)."""
    def snap(data_date, content):
        tasks = [
            task("1", "A-100", "Cable Installation Zone A", 1, 5),
            task("2", "A-200", "Electrical Testing Zone A", 15, 16),
            task("3", "A-300", "Commissioning Zone A", 17, 18),
            task("4", "PC-001", "Completion Zone A", 18, 18, milestone=True),
        ]
        rels = [
            Relationship("1", "2", "PR_FS", 0.0),
            Relationship("2", "3", "PR_FS", 0.0),
            Relationship("3", "4", "PR_FS", 0.0),
        ]
        return build_snapshot(tasks, rels, data_date=data_date,
                              content=content,
                              filename=f"update-{data_date}.xer")

    result = analyse([snap(2, b"u1"), snap(18, b"u2")],
                     anchor_task_code="PC-001")
    tested = [
        factor
        for bundle in result.graph.negative_bundles.values()
        for factor in bundle.factors if factor.reference == "N6"
    ]
    assert tested, "no negative evidence bundles produced"
    assert any(
        factor.state is not EvidenceState.NOT_APPLICABLE
        for factor in tested
    ), "N6 never tested despite a covering update pair"


def _rlpa_data():
    """Blockwork → first-fix with NO recorded link between them."""
    from dcma.models import Calendar, Project
    from dcma.xer_parser import XerData
    tasks = [
        task("1", "A-100", "Blockwork Zone A", 1, 5),
        task("2", "E-200", "First Fix Electrical Installation Zone A",
             8, 12),
        task("3", "E-300", "Electrical Testing Zone A", 13, 14),
        task("4", "PC-001", "Completion Zone A", 14, 14, milestone=True),
    ]
    rels = [
        Relationship("2", "3", "PR_FS", 0.0),
        Relationship("3", "4", "PR_FS", 0.0),
    ]
    return XerData(
        header=["ERMHDR"],
        raw_tables={
            "TASK": [], "TASKPRED": [],
            "CALENDAR": [{"clndr_id": "CAL-1", "clndr_name": "7d",
                          "day_hr_cnt": "8", "clndr_data": ""}],
        },
        projects=[Project("P1", "RLPA", dt(1), None, dt(14), dt(14))],
        tasks=tasks,
        relationships=rels,
        calendars={"CAL-1": Calendar("CAL-1", "7d", 8.0)},
        tasks_by_id={t.task_id: t for t in tasks},
    )


def test_screen_finds_unlinked_blockwork_pair():
    from programme.rlpa import screen_missing_links
    pairs = screen_missing_links(_rlpa_data())
    keys = {(p.pred_code, p.succ_code) for p in pairs}
    assert ("A-100", "E-200") in keys, keys
    # recorded links are never candidates
    assert ("E-200", "E-300") not in keys
    # backwards work order is never a candidate (testing -> blockwork)
    assert ("E-300", "A-100") not in keys


def test_parse_inference_is_verbatim_verified():
    from programme.rlpa import parse_inference, screen_missing_links
    pairs = screen_missing_links(_rlpa_data())
    text = ('noise {"links":[{"pred":"A-100","succ":"E-200",'
            '"reason":"zone must be closed"},{"pred":"GHOST-1",'
            '"succ":"E-200","reason":"invented"}]} noise')
    accepted, rejected = parse_inference(text, pairs)
    assert accepted == [("A-100", "E-200", "zone must be closed")]
    assert len(rejected) == 1 and "GHOST-1" in rejected[0]


def test_vote_aggregation_maps_to_words_not_numbers():
    from programme.rlpa import aggregate_votes
    link = ("A-100", "E-200", "r")
    other = ("A-100", "E-300", "r2")
    runs = [[link, other], [link], [link]]
    out = {(l.pred_code, l.succ_code): l for l in aggregate_votes(runs)}
    assert out[("A-100", "E-200")].confidence == "strong"
    assert out[("A-100", "E-300")].confidence == "poor"
    two = aggregate_votes([[link], [link], []])
    assert two[0].confidence == "medium"
    from dataclasses import asdict
    for l in aggregate_votes(runs):
        assert "%" not in json.dumps(asdict(l))


def test_derived_path_walks_through_inferred_link():
    from programme.rlpa import aggregate_votes, derive_paths
    data = _rlpa_data()
    links = aggregate_votes([[("A-100", "E-200", "zone closed")]] * 3)
    res = derive_paths(data, links, end_task_code="PC-001")
    assert 1 <= len(res.options) <= 3
    label, note, trace = res.options[0]
    codes = [a.task_code for a in trace.activities]
    assert "A-100" in codes and "E-200" in codes, codes
    inferred = [lk for lk in trace.links if lk.kind == "inferred"]
    assert any(lk.pred_code == "A-100" and lk.succ_code == "E-200"
               for lk in inferred)
    # confidence words only; no percentage anywhere in the caveats
    assert all("%" not in c for c in res.caveats)


def test_poor_links_stay_out_unless_they_extend_the_chain():
    from programme.rlpa import aggregate_votes, derive_paths
    data = _rlpa_data()
    # poor vote only (1 of 3)
    links = aggregate_votes([[("A-100", "E-200", "r")], [], []])
    assert links[0].confidence == "poor"
    res = derive_paths(data, links, end_task_code="PC-001")
    main_codes = [a.task_code for a in res.options[0][2].activities]
    assert "A-100" not in main_codes          # adopted excludes poor
    extended = [o for o in res.options if o[0].startswith("Extended")]
    assert extended, "poor link that extends the chain must appear as " \
                     "the disclosed extended option"
    assert "A-100" in [a.task_code
                       for a in extended[0][2].activities]


def _coded_data(code_type="Area / Location", value_both="Zone 7"):
    """Two activities whose NAMES share nothing, related only through
    an activity code — plus enough structure for the screen."""
    from dcma.models import Calendar, Project
    from dcma.xer_parser import XerData
    tasks = [
        task("1", "STR-01", "Masonry works north wing", 1, 5),
        task("2", "ELE-01", "Cabling and containment", 8, 12),
        task("3", "PC-001", "Completion", 12, 12, milestone=True),
    ]
    rels = [Relationship("2", "3", "PR_FS", 0.0)]
    return XerData(
        header=["ERMHDR"],
        raw_tables={
            "TASK": [{"task_id": t.task_id, "task_code": t.task_code,
                      "wbs_id": ""} for t in tasks],
            "TASKPRED": [],
            "CALENDAR": [{"clndr_id": "CAL-1", "clndr_name": "7d",
                          "day_hr_cnt": "8", "clndr_data": ""}],
            "ACTVTYPE": [{"actv_code_type_id": "T1",
                          "actv_code_type": code_type}],
            "ACTVCODE": [{"actv_code_id": "C1",
                          "actv_code_type_id": "T1",
                          "actv_code_name": value_both}],
            "TASKACTV": [{"task_id": "1", "actv_code_id": "C1"},
                         {"task_id": "2", "actv_code_id": "C1"}],
        },
        projects=[Project("P1", "RLPA", dt(1), None, dt(12), dt(12))],
        tasks=tasks,
        relationships=rels,
        calendars={"CAL-1": Calendar("CAL-1", "7d", 8.0)},
        tasks_by_id={t.task_id: t for t in tasks},
    )


def test_screen_reads_activity_codes_not_just_names():
    """Masonry -> cabling share no words; a shared Area/Location code
    must carry the pair into the candidate list."""
    from programme.rlpa import screen_missing_links
    pairs = screen_missing_links(_coded_data())
    keys = {(p.pred_code, p.succ_code) for p in pairs}
    assert ("STR-01", "ELE-01") in keys, keys
    kept = next(p for p in pairs
                if (p.pred_code, p.succ_code) == ("STR-01", "ELE-01"))
    assert "location" in kept.shared_context


def test_responsibility_codes_are_never_relevance():
    """A shared Responsibility code is a resource signal, not logic —
    it must NOT screen the pair in."""
    from programme.rlpa import screen_missing_links
    pairs = screen_missing_links(
        _coded_data(code_type="Responsibility (asserted)",
                    value_both="SC-04"))
    keys = {(p.pred_code, p.succ_code) for p in pairs}
    assert ("STR-01", "ELE-01") not in keys, keys


def test_per_successor_cap_keeps_tightest_handoffs():
    """With more candidates than the cap, the predecessors that
    finished CLOSEST to the successor's start must survive."""
    from dcma.models import Calendar, Project
    from dcma.xer_parser import XerData
    from programme.rlpa import screen_missing_links
    tasks = [task(str(i), f"Z-{i:03d}", f"Zone works stage {i}",
                  i, i + 1) for i in range(1, 8)]
    tasks.append(task("9", "Z-900", "Zone final inspection", 10, 11))
    data = XerData(
        header=["ERMHDR"],
        raw_tables={"TASK": [], "TASKPRED": [],
                    "CALENDAR": [{"clndr_id": "CAL-1",
                                  "clndr_name": "7d",
                                  "day_hr_cnt": "8", "clndr_data": ""}]},
        projects=[Project("P1", "RLPA", dt(1), None, dt(11), dt(11))],
        tasks=tasks,
        relationships=[],
        calendars={"CAL-1": Calendar("CAL-1", "7d", 8.0)},
        tasks_by_id={t.task_id: t for t in tasks},
    )
    pairs = screen_missing_links(data, max_per_successor=3)
    preds = [p.pred_code for p in pairs if p.succ_code == "Z-900"]
    assert len(preds) == 3
    # the three LATEST finishers (Z-005..Z-007), not the earliest
    assert set(preds) == {"Z-005", "Z-006", "Z-007"}, preds


def test_classification_pass_is_verbatim_verified():
    from programme.rlpa import (needs_classification,
                                parse_classification,
                                screen_missing_links)
    data = _rlpa_data()          # no codes at all -> needs the pass
    assert needs_classification(data)
    text = ('{"acts":[{"id":"A-100","location":"Zone A",'
            '"discipline":"Civil"},'
            '{"id":"E-200","location":"Zone A",'
            '"discipline":"Electrical"},'
            '{"id":"GHOST-9","location":"Nowhere","discipline":"X"}]}')
    ctx = parse_classification(text, data)
    assert "GHOST-9" not in ctx and ctx["A-100"]["location"] == "Zone A"
    coded = _coded_data()
    assert not needs_classification(coded) is None  # callable sanity
    # the recovered context feeds the screen exactly like file coding
    pairs = screen_missing_links(data, extra_context=ctx)
    kept = next(p for p in pairs
                if (p.pred_code, p.succ_code) == ("A-100", "E-200"))
    assert "location" in kept.shared_context


# --------------------------------------------------------------------- #
# Path Studio — detached analyst workspace                              #
# --------------------------------------------------------------------- #

def _studio_pair():
    """Baseline (early plan) + as-built (slipped actuals) sharing codes.

    The as-built also carries an LOE row and one activity absent from
    the baseline (scope growth), so both eligibility and missing-planned
    behaviour are pinned on one fixture.
    """
    import dataclasses

    from dcma.models import Calendar, Project
    from dcma.xer_parser import XerData

    def _xer(tasks, rels, name):
        return XerData(
            header=["ERMHDR"],
            raw_tables={
                "TASK": [], "TASKPRED": [],
                "CALENDAR": [{"clndr_id": "CAL-1", "clndr_name": "7d",
                              "day_hr_cnt": "8", "clndr_data": ""}],
            },
            projects=[Project("P1", name, dt(1), None, dt(20), dt(20))],
            tasks=tasks,
            relationships=rels,
            calendars={"CAL-1": Calendar("CAL-1", "7d", 8.0)},
            tasks_by_id={t.task_id: t for t in tasks},
        )

    base = _xer([
        task("1", "A-100", "Blockwork Zone A", 1, 4),
        task("2", "E-200", "First Fix Electrical Zone A", 5, 8),
        task("4", "PC-001", "Completion Zone A", 9, 9, milestone=True),
    ], [Relationship("1", "2", "PR_FS", 0.0),
        Relationship("2", "4", "PR_FS", 0.0)], "BASE")
    built = _xer([
        task("1", "A-100", "Blockwork Zone A", 3, 7),
        task("2", "E-200", "First Fix Electrical Zone A", 9, 13),
        task("3", "X-900", "Scope growth: rework", 14, 15),
        dataclasses.replace(
            task("9", "LOE-01", "Site management", 1, 15),
            task_type="TT_LOE"),
        task("4", "PC-001", "Completion Zone A", 16, 16,
             milestone=True),
    ], [Relationship("1", "2", "PR_FS", 0.0),
        Relationship("2", "4", "PR_FS", 0.0)], "BUILT")
    return base, built


def test_studio_planned_bars_come_from_the_baseline():
    """The adapter defect fixed on port: planned dates must be the
    BASELINE's (per the elected basis), never the as-built's own
    targets, and scope growth carries no planned bar at all."""
    from path_studio import dataset_from_xer
    base, built = _studio_pair()
    ds = dataset_from_xer(
        built, path_codes=["A-100", "E-200", "PC-001"],
        basis="recorded logic", milestone_code="PC-001",
        baseline=base, date_basis="target")
    by = {a.code: a for a in ds.activities}
    assert by["A-100"].planned_start == dt(1).isoformat()
    assert by["A-100"].planned_finish == dt(4).isoformat()
    assert by["A-100"].start == dt(3).isoformat()        # as-built actual
    assert by["X-900"].planned_start is None             # not in baseline
    assert by["X-900"].start == dt(14).isoformat()
    # without a baseline the planned side stays EMPTY — never silently
    # compared against the as-built's own targets
    ds_nb = dataset_from_xer(
        built, path_codes=["A-100"], basis="x", milestone_code="PC-001")
    assert all(a.planned_start is None for a in ds_nb.activities)


def test_studio_adapter_eligibility_and_inferred_links():
    from types import SimpleNamespace

    from path_studio import dataset_from_xer
    base, built = _studio_pair()
    inferred = [
        SimpleNamespace(pred_code="A-100", succ_code="E-200",
                        confidence="strong", reasons=("dup of recorded",)),
        SimpleNamespace(pred_code="E-200", succ_code="X-900",
                        confidence="medium", reasons=("gap 1d",)),
    ]
    ds = dataset_from_xer(
        built, path_codes=["A-100", "E-200", "PC-001"], basis="b",
        milestone_code="PC-001", baseline=base,
        inferred_links=inferred)
    by = {a.code: a for a in ds.activities}
    assert not by["LOE-01"].path_eligible
    assert "Level of Effort" in by["LOE-01"].eligibility_reason
    assert by["A-100"].path_eligible
    pairs = [(r.predecessor, r.successor, r.source)
             for r in ds.relationships]
    # a recorded link is never duplicated as inferred
    assert ("A-100", "E-200", "recorded") in pairs
    assert ("A-100", "E-200", "inferred") not in pairs
    assert ("E-200", "X-900", "inferred") in pairs
    inf = next(r for r in ds.relationships
               if r.source == "inferred")
    assert "medium" in inf.evidence


def test_studio_validation_gates():
    from path_studio import PathDraft, dataset_from_xer, validate_draft
    base, built = _studio_pair()
    ds = dataset_from_xer(built, path_codes=["A-100", "E-200", "PC-001"],
                          basis="recorded logic",
                          milestone_code="PC-001", baseline=base)

    def codes_of(draft):
        return {i.code: i.severity for i in validate_draft(ds, draft)}

    # LOE on path + missing anchor + missing basis are all blocking
    bad = codes_of(PathDraft(ds.analysis_id,
                             ("A-100", "LOE-01"), "  "))
    assert bad.get("ineligible_path_activity") == "error"
    assert bad.get("missing_anchor") == "error"
    assert bad.get("missing_basis") == "error"
    dup = codes_of(PathDraft(ds.analysis_id,
                             ("A-100", "A-100", "PC-001"), "b"))
    assert dup.get("duplicate_activity") == "error"
    # a hop with no recorded/inferred relationship is a warning, not a
    # block — the analyst documents the sequence evidence instead
    hop = codes_of(PathDraft(ds.analysis_id,
                             ("A-100", "X-900", "PC-001"), "b"))
    assert hop.get("unlinked_handoff") == "warning"
    ok = validate_draft(ds, PathDraft(
        ds.analysis_id, ("A-100", "E-200", "PC-001"), "recorded"))
    assert not [i for i in ok if i.severity == "error"]


def test_studio_renderer_dual_mode():
    """One template serves both the live component (sentinel intact,
    Streamlit protocol present) and the standalone export (payload
    embedded, '<' escaped against script breakout)."""
    from pathlib import Path as _P

    from path_studio import PathDraft, build_path_studio_html, \
        dataset_from_xer, validate_draft
    from path_studio.renderer import _SENTINEL, _TEMPLATE_PATH
    import dataclasses as _dc
    base, built = _studio_pair()
    ds = dataset_from_xer(built, path_codes=["A-100", "E-200", "PC-001"],
                          basis="recorded logic",
                          milestone_code="PC-001", baseline=base)
    ds = _dc.replace(ds, title="Harbour </script><b> injection")
    draft = PathDraft(ds.analysis_id, ds.candidate_path_codes, "b")
    html = build_path_studio_html(ds, draft, validate_draft(ds, draft))
    assert _SENTINEL not in html
    assert "</script><b> injection" not in html          # escaped
    assert "\\u003c/script>" in html
    assert "A-100" in html
    static = _P(_TEMPLATE_PATH).read_text(encoding="utf-8")
    # exactly ONE literal sentinel: the full-screen handler assembles
    # its copy in pieces, or the payload replace would corrupt the JS
    assert static.count(_SENTINEL) == 1
    assert "streamlit:componentReady" in static
    assert "streamlit:setComponentValue" in static
    assert "streamlit:render" in static
    # every outbound protocol message carries the isStreamlitMessage
    # flag the host filters on — a missing flag is an unbootable gantt
    import re as _re
    for m in _re.findall(r"postMessage\((\{[^)]*?)\}\s*,\s*\"\*\"",
                         static):
        assert "isStreamlitMessage" in m, m
    assert 'id="fullscreen"' in static          # ⛶ opens a new tab


def test_studio_apply_labelling():
    """Applying an adjustment keeps the gantt's ordering, dedups, and
    discloses the adjustment exactly once however often re-applied."""
    from path_studio import adjusted_basis, adjusted_path
    out = adjusted_path(["E-200", "A-100", "E-200", "PC-001"],
                        {"A-100": "Blockwork", "E-200": "First Fix"})
    assert out == [("E-200", "First Fix"), ("A-100", "Blockwork"),
                   ("PC-001", "PC-001")]
    once = adjusted_basis("as-built longest path (recorded logic)")
    assert once.startswith("as-built longest path (recorded logic)")
    assert "analyst-adjusted in the path gantt" in once
    assert adjusted_basis(once) == once          # never stacks
    assert adjusted_basis("").startswith("adopted path")
    assert "%" not in once


ALL_TESTS = [
    test_pipeline_builds_path_with_first_class_interruption,
    test_graph_is_deterministic_and_sealed,
    test_numeric_candidate_ranking_never_reaches_output,
    test_report_bundle_physically_separates_layers,
    test_layer_three_rejection_regenerates_path_not_evidence,
    test_interval_union_gap_detection,
    test_e5_suppressed_across_scheduling_option_boundary,
    test_n6_completion_correspondence_with_update_pair,
    test_screen_finds_unlinked_blockwork_pair,
    test_parse_inference_is_verbatim_verified,
    test_vote_aggregation_maps_to_words_not_numbers,
    test_derived_path_walks_through_inferred_link,
    test_poor_links_stay_out_unless_they_extend_the_chain,
    test_screen_reads_activity_codes_not_just_names,
    test_responsibility_codes_are_never_relevance,
    test_per_successor_cap_keeps_tightest_handoffs,
    test_classification_pass_is_verbatim_verified,
    test_studio_planned_bars_come_from_the_baseline,
    test_studio_adapter_eligibility_and_inferred_links,
    test_studio_validation_gates,
    test_studio_renderer_dual_mode,
    test_studio_apply_labelling,
]


if __name__ == "__main__":
    passed = 0
    for fn in ALL_TESTS:
        fn()
        print(f"PASS  {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(ALL_TESTS)} RLPA v2 tests passed")
