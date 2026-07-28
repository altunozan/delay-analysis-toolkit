"""Data Intake & Inventory (Module 0)."""

from __future__ import annotations

import hashlib
import os

import pandas as pd
import streamlit as st

import state as sk
from dcma import DCMAConfig, parse_xer
from programme import (
    ProjectStore, STORE_CAVEATS, build_custody_xlsx, build_inventory,
    build_inventory_prompt, build_inventory_xlsx,
)
from programme.narrative import DEFAULT_TEMPLATES
from views._shared import (ai_narrative_panel, fetch_raw,
                           get_parsed_files, stash_raw)


def intake_tab() -> None:
    st.caption(
        "Upload every programme revision once — all modules read from this "
        "pool. The inventory below is the report's data front-matter."
    )
    uploads = st.file_uploader(
        "Primavera P6 XER files (baseline + updates)",
        type=["xer"],
        accept_multiple_files=True,
        key="intake_uploads",
    )

    # sample/ lives at the repo root, one level above views/.
    sample_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "sample")
    sample_paths = sorted(
        os.path.join(sample_dir, f) for f in os.listdir(sample_dir)
        if f.lower().endswith(".xer")
    ) if os.path.isdir(sample_dir) else []
    use_samples = False
    if not uploads and sample_paths:
        use_samples = st.toggle(
            f"Use bundled sample programmes ({len(sample_paths)} files)",
            value=False,
            help="Loads the .xer files shipped in the sample/ folder.",
        )

    if not uploads and sample_paths and not use_samples:
        st.caption(
            "Minimum inputs — one XER: prospective TIA · two or more "
            "XERs: revision comparison, windows, as-built path, Explain "
            "This Delay. The latest data date is treated as the current "
            "accepted update. New here? Download a sample to try the "
            "toolkit:")
        dcols = st.columns(len(sample_paths[:2]))
        for _c, _p in zip(dcols, sample_paths[:2]):
            with open(_p, "rb") as _fh:
                _c.download_button(f"⬇️ {os.path.basename(_p)}",
                                   data=_fh.read(),
                                   file_name=os.path.basename(_p),
                                   key=f"smp_{os.path.basename(_p)}")
    if use_samples:
        sources = [(os.path.basename(p), p, os.path.getsize(p))
                   for p in sample_paths]
    else:
        sources = [(u.name, u, u.size) for u in uploads or []]

    _on_cloud = os.path.exists("/mount/src")
    _big = [(n, s) for n, _, s in sources if s > 15 * 1024 * 1024]
    if _on_cloud and _big:
        st.warning(
            "Large file(s): "
            + ", ".join(f"{n} ({s / 1048576:.0f} MB)" for n, s in _big)
            + ". This Cloud host has ~1 GB of memory; a programme this "
            "size can exhaust it mid-parse, which shows as the app "
            "reloading with nothing loaded. If that happens, run the "
            "toolkit locally — the parser itself has no size limit "
            "(uploads accepted to 400 MB).")

    signature = tuple(sorted((name, size) for name, _, size in sources))
    if signature != st.session_state.get(sk.XER_POOL_SIG):
        files = []
        hashes: dict[str, str] = {}
        with st.spinner("Parsing programmes…"):
            for name, src, _ in sources:
                try:
                    if isinstance(src, str):
                        with open(src, "rb") as fh:
                            raw = fh.read()
                    else:
                        raw = src.getvalue()
                    hashes[name] = hashlib.sha256(raw).hexdigest()
                    # compressed session copy (~8x smaller) — the raw
                    # bytes are only needed on demand, never per-render
                    stash_raw(name, raw)
                    data = parse_xer(raw, DCMAConfig())
                    del raw
                except Exception as exc:  # noqa: BLE001 - per-file errors
                    st.warning(f"Skipped '{name}': {exc}")
                    continue
                if not data.tasks:
                    st.warning(f"Skipped '{name}': no TASK table found.")
                    continue
                files.append((name, data))
        st.session_state[sk.XER_POOL] = files
        st.session_state[sk.XER_HASHES] = hashes
        st.session_state[sk.XER_POOL_SIG] = signature
        # New data invalidates cached narratives.
        for key in list(st.session_state):
            if key.startswith("nar_"):
                del st.session_state[key]

    files = get_parsed_files()
    if not files:
        st.info("Upload at least one .xer file to begin. Two or more enable "
                "the shift and variance modules.")
        return

    names = [n for n, _ in files]
    baseline_choice = st.selectbox(
        "Contract baseline",
        options=["(auto: earliest data date)"] + names,
        help="Which revision is the contract baseline? Auto picks the "
             "earliest data date.",
    )
    baseline_file = (None if baseline_choice.startswith("(auto")
                     else baseline_choice)

    inv = build_inventory(files, baseline_file=baseline_file)
    st.session_state[sk.INVENTORY] = inv

    # The completion obligation: ONE election, honoured by every module
    # (windows, as-built trace, milestone tracker, collapsed as-built,
    # impact bands). Without it, modules trace to the latest finisher —
    # and post-PC activities (demob, DLP, handover admin) silently
    # become the measured completion.
    _latest_data = files[-1][1] if files else None
    _ms_opts = ["(auto — latest finisher)"]
    _ms_map = {}
    if _latest_data is not None:
        for t in _latest_data.tasks:
            if t.is_milestone and not t.is_loe_or_wbs:
                lbl = f"{t.task_code} — {t.name[:60]}"
                _ms_opts.append(lbl)
                _ms_map[lbl] = t.task_code
    _cur_ms = st.session_state.get(sk.CONTRACT_MS)
    _cur_lbl = next((l for l, c in _ms_map.items() if c == _cur_ms),
                    _ms_opts[0])
    _pick = st.selectbox(
        "Contractual completion milestone (the completion obligation)",
        _ms_opts, index=_ms_opts.index(_cur_lbl),
        help="Every module traces and measures to this milestone. "
             "'Auto' means the latest finisher in each file — which is "
             "the wrong date whenever the programme carries post-"
             "completion activities. Recorded in the Basis of Analysis.")
    st.session_state[sk.CONTRACT_MS] = _ms_map.get(_pick)

    st.subheader("Data Inventory")
    inv_df = pd.DataFrame([
        {
            "File": r.file_name,
            "Project": r.project_short_name or "—",
            "Data date": r.data_date.strftime("%Y-%m-%d") if r.data_date else "—",
            "Role": ("Baseline" if r.is_baseline
                     else "Current" if r.is_current else "Update"),
            "Activities": r.activity_count,
            "Relationships": r.relationship_count,
            "Milestones": r.milestone_count,
            "Activity codes": "Yes" if r.has_activity_codes else "No",
        }
        for r in inv.revisions
    ])
    st.dataframe(inv_df, width="stretch", hide_index=True)

    for w in inv.warnings:
        st.info(w)
    if inv.missing:
        with st.expander("Missing inputs (become report caveats)"):
            for m in inv.missing:
                st.write("•", m)

    narrative = ai_narrative_panel(
        "nar_inventory",
        lambda tmpl: build_inventory_prompt(inv, tmpl),
        "data_inventory",
        DEFAULT_TEMPLATES[sk.INVENTORY],
    )
    st.download_button(
        "⬇️ Download inventory (Excel)",
        data=build_inventory_xlsx(inv, narrative),
        file_name="data_inventory.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    # ------------------------------------------------------------------ #
    # Project library — local chain-of-custody register
    # ------------------------------------------------------------------ #
    _on_cloud = os.path.exists("/mount/src")
    with st.expander("📚 Project library — local chain-of-custody register"):
        if _on_cloud:
            st.warning(
                "Cloud deployment: this host's filesystem is EPHEMERAL — "
                "anything registered here evaporates on the next "
                "redeploy, so a register kept here is NOT a chain-of-"
                "custody record you could put to a tribunal. Run the "
                "toolkit locally (or on a host with durable storage) "
                "for a register that actually persists; the SHA-256 "
                "hashes above remain valid either way.")
        st.caption(
            "An append-only local register: each file's SHA-256, size and "
            "registration time. Identical content is never duplicated, so "
            "the register can testify when this exact file first entered "
            "the analysis."
        )
        default_project = ""
        if inv.revisions:
            default_project = (inv.revisions[0].project_short_name
                               or inv.revisions[0].file_name)
        lib_project = st.text_input("Project name for the register",
                                    value=default_project,
                                    key="lib_project")
        if st.button("Register uploaded files in the library",
                     disabled=not lib_project.strip()):
            try:
                store = ProjectStore()
                added, dups = 0, 0
                by_name = {r.file_name: r for r in inv.revisions}
                for name, _data in files:
                    raw = fetch_raw(name)
                    if raw is None:
                        continue
                    r = by_name.get(name)
                    rec = store.register_file(
                        lib_project.strip(), name, raw,
                        data_date=(r.data_date.strftime("%Y-%m-%d")
                                   if r and r.data_date else None),
                        project_short_name=(r.project_short_name
                                            if r else None),
                        activity_count=(r.activity_count if r else None))
                    if rec.already_registered:
                        dups += 1
                    else:
                        added += 1
                st.success(f"Registered {added} file(s); {dups} already "
                           "in the register (matched by hash).")
            except Exception as exc:  # noqa: BLE001 - read-only FS etc.
                st.error(f"Library unavailable on this host: {exc}")
        try:
            store = ProjectStore()
            rows = store.custody_register(lib_project.strip() or None)
            if rows:
                lib_df = pd.DataFrame([{
                    "Registered (UTC)": r.added_utc,
                    "Project": r.project,
                    "File": r.file_name,
                    "Data date": r.data_date or "—",
                    "Activities": r.activity_count,
                    "Size (bytes)": r.size_bytes,
                    "SHA-256": r.sha256,
                } for r in rows])
                st.dataframe(lib_df, width="stretch", hide_index=True)
                st.download_button(
                    "⬇️ Download custody register (Excel)",
                    data=build_custody_xlsx(rows),
                    file_name="custody_register.xlsx",
                    mime="application/vnd.openxmlformats-officedocument."
                         "spreadsheetml.sheet",
                    key="lib_dl",
                )
        except Exception:  # noqa: BLE001 - no register yet / no write access
            pass
        for c in STORE_CAVEATS:
            st.caption(f"• {c}")
