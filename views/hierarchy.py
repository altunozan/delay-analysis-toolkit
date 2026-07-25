"""Hierarchy Rebuild."""

from __future__ import annotations

import streamlit as st

import state as sk
from programme import (
    available_dimensions, build_gantt_html, build_hierarchy,
    build_hierarchy_xlsx, config_from_json, config_to_json,
    propose_sequence_mapping, sequence_dimension_mappings, tree_to_dict,
)
from views._shared import get_parsed_files


def hierarchy_tab() -> None:
    st.caption(
        "Reorganise the programme under a hierarchy of your own choosing — "
        "any ordered mix of WBS levels and activity codes — and browse it "
        "as a collapsible gantt. A read-only overlay: no dates, logic, or "
        "codes are changed."
    )
    files = get_parsed_files()
    inv = st.session_state.get(sk.INVENTORY)
    if not files or inv is None:
        st.info("Upload programmes in the **Data Intake** tab first.")
        return

    names = [r.file_name for r in inv.revisions]
    chosen = st.selectbox("Programme", names, index=len(names) - 1,
                          key="hier_prog")
    data = dict(files)[chosen]

    dims = available_dimensions(data)
    label_to_id = {d.label: d.dim_id for d in dims}

    # Module 13 sequence coding as extra dimensions — uses the session
    # mapping (incl. AI-review / analyst edits) when one exists, else a
    # fresh deterministic proposal.
    seq_prop = st.session_state.get(f"seq_rows_{chosen}")
    seq_confirmed = st.session_state.get(f"seq_rows_{chosen}_confirmed",
                                         False)
    if seq_prop is None:
        seq_prop = propose_sequence_mapping(data, chosen)
    extra_maps = sequence_dimension_mappings(data, seq_prop.rows)
    seq_state = ("analyst-confirmed" if seq_confirmed
                 else "incl. AI review" if any(
                     r.front_evidence == "AI review"
                     or r.stage_evidence == "AI review"
                     for r in seq_prop.rows)
                 else "auto-proposed")
    label_to_id[f"Sequence: Work front ({seq_state})"] = "seq:front"
    label_to_id[f"Sequence: Stage ({seq_state})"] = "seq:stage"

    if not label_to_id:
        st.warning("No WBS levels or activity codes found in this file.")
        return

    structure = st.radio(
        "Structure", ["Reconstructed hierarchy", "Original WBS"],
        horizontal=True, key="hier_structure",
        help="Original WBS shows the file's own arrangement; Reconstructed "
             "uses the levels you pick below, in the order you pick them.")

    # Apply a loaded config BEFORE the multiselect widget is instantiated.
    pending = st.session_state.pop("hier_pending_cfg", None)
    if pending:
        valid = [lbl for lbl in pending if lbl in label_to_id]
        st.session_state["hier_dims"] = valid

    if structure == "Reconstructed hierarchy":
        # Sanitise any stored selection against this file's dimensions and
        # seed a sensible default — never pass default= alongside the key.
        stored = [lbl for lbl in st.session_state.get("hier_dims", [])
                  if lbl in label_to_id]
        st.session_state["hier_dims"] = (
            stored or list(label_to_id.keys())[:2])
        sel_labels = st.multiselect(
            "Hierarchy levels (top → bottom, in the order you click them)",
            options=list(label_to_id.keys()),
            max_selections=5, key="hier_dims")
        if not sel_labels:
            st.info("Pick at least one hierarchy level.")
            return
        dim_ids = [label_to_id[lbl] for lbl in sel_labels]
        dim_labels = list(sel_labels)
    else:
        depth = min(len([d for d in dims if d.dim_id.startswith("wbs:")]), 6)
        dim_ids = [f"wbs:{i}" for i in range(1, depth + 1)]
        dim_labels = [f"WBS Level {i}" for i in range(1, depth + 1)]
        st.caption("Showing the file's own WBS, level by level.")

    h = build_hierarchy(data, dim_ids, chosen, dim_labels=dim_labels,
                        extra_mappings=extra_maps)

    # --- validation --------------------------------------------------------
    v1, v2, v3, v4 = st.columns(4)
    v1.metric("Source activities", h.source_activities)
    v2.metric("Placed in hierarchy", h.placed_activities)
    v3.metric("Duplicated", h.duplicate_ids)
    v4.metric("Validation", "✅ complete" if h.is_complete else "❌ FAILED")
    for w in h.warnings:
        (st.error if "FAILED" in w else st.warning)(w)

    with st.expander("Structure preview (top two levels)"):
        lines = []
        for c in list(h.root.children.values())[:40]:
            span = (f"{c.start:%Y-%m-%d} → {c.finish:%Y-%m-%d}"
                    if c.start and c.finish else "no dates")
            lines.append(f"**{c.name}** — {c.activity_count} activities, "
                         f"{span}")
            for g in list(c.children.values())[:8]:
                lines.append(f"&nbsp;&nbsp;&nbsp;└─ {g.name} "
                             f"({g.activity_count})")
            if len(c.children) > 8:
                lines.append(f"&nbsp;&nbsp;&nbsp;└─ … "
                             f"+{len(c.children) - 8} more groups")
        st.markdown("\n\n".join(lines) if lines else "No groups.")

    # --- save / reuse the configuration ------------------------------------
    if structure == "Reconstructed hierarchy":
        with st.expander("Save / reuse this hierarchy configuration"):
            cfg_name = st.text_input("Configuration name",
                                     "My hierarchy view", key="hier_cfgname")
            c1, c2 = st.columns(2)
            c1.download_button(
                "⬇️ Save configuration (JSON)",
                data=config_to_json(cfg_name, dim_ids, dim_labels),
                file_name="hierarchy_config.json", mime="application/json")
            up = c2.file_uploader("Load configuration", type=["json"],
                                  key="hier_cfgup")
            if up is not None:
                parsed = config_from_json(up.getvalue().decode("utf-8"))
                if parsed is None:
                    st.error("Not a valid hierarchy configuration file.")
                else:
                    name, ids, labels = parsed
                    if st.button(f"Apply '{name}'", key="hier_apply"):
                        st.session_state["hier_pending_cfg"] = labels
                        st.rerun()

    # --- the collapsible gantt ----------------------------------------------
    dd = (f"{data.project.data_date:%Y-%m-%d}"
          if data.project and data.project.data_date else None)
    st.iframe(
        build_gantt_html(tree_to_dict(h.root), data_date=dd,
                         title=" › ".join(
                             lbl.split(" (")[0] for lbl in dim_labels)),
        height=720)
    st.caption(
        "Click any group to expand/collapse · search auto-expands matching "
        "branches · summary brackets span earliest start → latest finish of "
        "everything beneath · ◆ milestones · dashed red line = data date."
    )
    st.download_button(
        "⬇️ Export rebuilt hierarchy (Excel, collapsible outline)",
        data=build_hierarchy_xlsx(h),
        file_name="hierarchy_rebuild.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="Sheet 1 mirrors this view with Excel's own +/- row groups; "
             "Sheet 2 is a flat table for pivoting.")
