"""Shared helpers: intake pool, cache wrappers, AI panels, status strip."""

from __future__ import annotations

import dataclasses
import os

import streamlit as st

import state as sk
from dcma import annotate_path_position, build_dcma_trace, run_all_checks
from dcma.checks import CheckStatus
from dcma.narrative import NarrativeError, PROVIDERS, stream_narrative
from programme import (
    analyse_windows, build_narrative_docx, build_repair_plan,
    compare_revisions, event_from_dict, extract_critical_path,
    extract_longest_path, oos_evolution, out_of_sequence_flags,
    sched_options_summary, track_milestone_shifts,
)


STATUS_COLORS = {
    CheckStatus.PASS: "#3F6B4F",
    CheckStatus.FAIL: "#9B3227",
    CheckStatus.NA: "#6e7781",
}


STATUS_BG = {
    CheckStatus.PASS: "#e6f4ea",
    CheckStatus.FAIL: "#fbe9e7",
    CheckStatus.NA: "#f0f1f3",
}


# Drawing Sheet inks — see ui_variants/ for the revert kit.
PLANNED_COLOR = "#14324A"    # drafting ink (as-planned)
RECORDED_COLOR = "#9B3227"   # revision red (as-recorded)
SLIP_COLOR = "#9B3227"       # later than planned
GAIN_COLOR = "#3F6B4F"       # on / ahead of programme


def get_parsed_files() -> list[tuple[str, object]]:
    """Parsed XER pool from the intake tab (cached in session state)."""
    return st.session_state.get(sk.XER_POOL, [])


def gantt_fullscreen_button(html: str, stub: str, key: str) -> None:
    """Standalone-HTML download for a chart — the guaranteed full-screen
    path (the in-chart ⛶ button depends on the iframe's permission)."""
    st.download_button(
        "⛶ Full-screen gantt (standalone HTML — opens browser-wide, "
        "fully interactive)",
        data=html.encode("utf-8"), file_name=f"{stub}.html",
        mime="text/html", key=key)


def stash_raw(name: str, raw: bytes) -> None:
    """Keep an original XER in session, zlib-compressed.

    XER is tab-separated text — ~8x smaller compressed, so a 20 MB
    upload pins ~2.5 MB instead of 20. The raw bytes are only ever
    needed on demand (OOS repair export, TIA impacted-XER export,
    custody register), never per-render.
    """
    import zlib
    st.session_state.setdefault(sk.XER_RAW, {})[name] = \
        zlib.compress(raw, 6)


def fetch_raw(name: str) -> bytes | None:
    """Original XER bytes back from the compressed session pool."""
    import zlib
    z = st.session_state.get(sk.XER_RAW, {}).get(name)
    if z is None:
        return None
    try:
        return zlib.decompress(z)
    except zlib.error:
        return z          # a pre-compression session copy


def _fkey(name: str) -> str:
    """Cache key for an uploaded file: its intake SHA-256 (name fallback)."""
    return st.session_state.get(sk.XER_HASHES, {}).get(name, name)


def _cfgkey(cfg) -> tuple:
    """Hashable identity for a config dataclass (sets sorted)."""
    out = []
    for f in dataclasses.fields(cfg):
        v = getattr(cfg, f.name)
        out.append((f.name,
                    tuple(sorted(v)) if isinstance(v, (set, frozenset))
                    else v))
    return tuple(out)


@st.cache_data(show_spinner=False, max_entries=24)
def cached_dcma(key: str, cfg_key: tuple, _data, _cfg):
    results = run_all_checks(_data, _cfg)
    trace = build_dcma_trace(_data, _cfg, results)
    annotate_path_position(results, trace)
    return results, trace


@st.cache_data(show_spinner=False, max_entries=16)
def cached_milestone_shifts(key: tuple, _revs):
    return track_milestone_shifts(_revs)


@st.cache_data(show_spinner=False, max_entries=24)
def cached_compare(key_old: str, key_new: str, label_old: str,
                   label_new: str, _old, _new):
    return compare_revisions(_old, _new, label_old, label_new)


@st.cache_data(show_spinner=False, max_entries=16)
def cached_windows(key: tuple, _ordered, end_code=None):
    return analyse_windows(_ordered, end_task_code=end_code)


@st.cache_data(show_spinner=False, max_entries=16)
def cached_oos_evolution(key: tuple, _ordered):
    return oos_evolution(_ordered)


@st.cache_data(show_spinner=False, max_entries=24)
def cached_oos_flags(key: str, _data):
    return out_of_sequence_flags(_data)


@st.cache_data(show_spinner=False, max_entries=24)
def cached_repair_plan(key: str, _data):
    return build_repair_plan(_data)


@st.cache_data(show_spinner=False, max_entries=24)
def cached_longest_path(key: str, label: str, end_code, near: float,
                        _data, branch_tol: float = 1.0):
    return extract_longest_path(_data, label, end_task_code=end_code,
                                near_critical_days=near,
                                branch_tolerance_hours=branch_tol)


@st.cache_data(show_spinner=False, max_entries=24)
def cached_float_path(key: str, label: str, tol: float, near: float, _data):
    return extract_critical_path(_data, label, float_tolerance_days=tol,
                                 near_critical_days=near)


def managed_ai_key() -> str:
    """The deployment's own NVIDIA key, if one is configured.

    Resolution: Streamlit secrets, then environment. It is NEVER written
    into the repository and NEVER rendered — callers only ever learn
    whether one exists, not what it is. Absent = the app simply asks the
    analyst for their own key, exactly as before.
    """
    try:
        v = st.secrets.get("NVIDIA_API_KEY", "")
    except Exception:                      # no secrets.toml present
        v = ""
    return (v or os.environ.get("NVIDIA_API_KEY", "")).strip()


def ai_credentials_panel(page: str) -> None:
    """THE one AI-credentials component.

    Default path: the managed NVIDIA key runs everything with no setup and
    is never displayed. The analyst may instead supply their own key for
    Anthropic / OpenAI / Gemini / NVIDIA, which takes precedence for the
    rest of the session. Widgets are page-local (widget-backed state dies
    when its page is not rendered); values are copied into the plain
    shared keys so the choice survives navigation.
    """
    managed = managed_ai_key()

    if managed and st.session_state.get(sk.AI_MANAGED, True):
        # ---- managed default: no key input rendered at all ----------
        st.session_state[sk.AI_PROVIDER] = "nvidia"
        st.session_state[sk.AI_KEY] = managed
        st.session_state[sk.AI_MANAGED] = True
        pinfo = PROVIDERS["nvidia"]
        c1, c2 = st.columns([1, 1])
        c1.success("AI enabled — managed NVIDIA endpoint. No key needed.")
        st.session_state[sk.AI_MODEL] = model_selector(
            c2, pinfo, f"aic_model_{page}_nvidia")
        st.caption(
            "Narratives run on a managed NVIDIA endpoint provided with "
            "this deployment; the credential is held server-side and is "
            "not shown or exported. Prompts carry the figures and "
            "activity names of the programmes you load — if the matter "
            "forbids third-party processing, switch to your own key or "
            "a self-hosted endpoint below.")
        if st.button("Use my own API key instead", key=f"aic_sw_{page}"):
            st.session_state[sk.AI_MANAGED] = False
            st.rerun()
        return

    # ---- analyst-supplied credentials ------------------------------
    if managed:
        st.caption("Using your own key. The managed NVIDIA endpoint "
                   "remains available.")
    a1, a2 = st.columns(2)
    pkey = f"aic_prov_{page}"
    if pkey not in st.session_state:
        st.session_state[pkey] = st.session_state.get(
            sk.AI_PROVIDER, next(iter(PROVIDERS)))
    prov = a1.selectbox("AI provider", options=list(PROVIDERS.keys()),
                        format_func=lambda p: PROVIDERS[p]["label"],
                        key=pkey)
    st.session_state[sk.AI_PROVIDER] = prov
    st.session_state[sk.AI_MANAGED] = False
    pinfo = PROVIDERS[prov]
    st.session_state[sk.AI_MODEL] = model_selector(
        a2, pinfo, f"aic_model_{page}_{prov}")
    env = os.environ.get(pinfo["env_var"], "")
    if prov == "gemini" and not env:
        env = os.environ.get("GOOGLE_API_KEY", "")
    wkey = f"aic_key_{page}"
    if wkey not in st.session_state:
        st.session_state[wkey] = st.session_state.get(sk.AI_KEY) or env
    st.text_input(f"{pinfo['label']} API key", type="password", key=wkey,
                  help="Held in this session only; never stored.")
    st.session_state[sk.AI_KEY] = st.session_state[wkey]
    if not st.session_state.get(sk.AI_KEY):
        st.caption("You can proceed without a key — AI assistance will "
                   "be disabled.")
    if managed and st.button("Back to the managed endpoint",
                             key=f"aic_bk_{page}"):
        st.session_state[sk.AI_MANAGED] = True
        st.session_state.pop(wkey, None)
        st.rerun()


def resolve_ai_credentials() -> tuple[str, str, str]:
    """(provider, model, key) resolved EXACTLY as the narrative panels
    resolve them: the managed endpoint straight from secrets while
    AI_MANAGED is on, else the analyst's own registered credentials.

    Every AI feature must call this rather than reading sk.AI_KEY
    directly — the session copy only exists once a credentials panel has
    rendered, which is why 'narratives work but propose does not' was a
    real bug class.
    """
    managed = managed_ai_key()
    if managed and st.session_state.get(sk.AI_MANAGED, True):
        nv = PROVIDERS["nvidia"]
        model = st.session_state.get(sk.AI_MODEL)
        if model not in nv.get("models", [nv["default_model"]]):
            model = nv["default_model"]   # never a cross-provider model
        return ("nvidia", model, managed)
    return (st.session_state.get(sk.AI_PROVIDER, "nvidia"),
            st.session_state.get(sk.AI_MODEL, ""),
            st.session_state.get(sk.AI_KEY, ""))


def basis_panel(module: str, data, engine_lines: list[str]) -> None:
    """Scheduling-basis disclosure: what OUR engine did (method, tolerance,
    terminal, statusing rule) plus the settings the FILE's own forecast was
    calculated under (P6 SCHEDOPTIONS). Recorded in session state so the
    Report Assembler prints every module's basis in the Basis of Analysis —
    the first thing an opposing expert attacks."""
    file_lines = sched_options_summary(data) if data is not None else []
    st.session_state.setdefault(sk.ANALYSIS_BASIS, {})[module] = (
        engine_lines + [f"P6 scheduling options (file): {ln}"
                        for ln in file_lines])
    with st.expander("Scheduling basis (disclosed in the report)"):
        st.markdown("**This module's settings**")
        for ln in engine_lines:
            st.write("•", ln)
        if file_lines:
            st.markdown("**The file's own P6 scheduling options "
                        "(SCHEDOPTIONS as submitted)**")
            for ln in file_lines:
                st.write("•", ln)


def status_strip() -> None:
    """One-line persistent state banner: what is loaded, on every page."""
    inv = st.session_state.get(sk.INVENTORY)
    files = get_parsed_files()
    if not files or inv is None:
        st.caption("📁 No programmes loaded — start at "
                   "**Data Intake & Inventory**.")
        return
    bits = []
    for r in inv.revisions:
        tag = (" **(baseline)**" if r.is_baseline
               else " **(current)**" if r.is_current else "")
        dd = f" @ {r.data_date:%Y-%m-%d}" if r.data_date else ""
        bits.append(f"`{r.file_name}`{dd}{tag}")
    st.caption("📁 " + " · ".join(bits))


@st.cache_data(ttl=3600, show_spinner=False)
def _live_models(base_url: str, key_fp: str, _key: str) -> list[str]:
    """Live model catalogue from an OpenAI-protocol endpoint.

    Model retirements (qwen3-next-80b, 410, 2026-07-27) must drop off
    the dropdown by themselves — a static list rots. Cached an hour;
    keyed on a key fingerprint, never the key itself."""
    import requests
    r = requests.get(f"{base_url}/models",
                     headers={"Authorization": f"Bearer {_key}"},
                     timeout=8)
    r.raise_for_status()
    return [m.get("id", "") for m in r.json().get("data", [])
            if m.get("id")]


def refresh_models(pinfo: dict, api_key: str | None) -> dict:
    """pinfo with its model list refreshed from the endpoint's live
    catalogue when one is reachable: known-good models first (dead ones
    dropped), the rest of the catalogue after. Falls back to the static
    list untouched on any failure."""
    if not (api_key and pinfo.get("base_url")):
        return pinfo
    try:
        import hashlib
        live = _live_models(pinfo["base_url"],
                            hashlib.sha256(api_key.encode()).hexdigest()[:16],
                            api_key)
    except Exception:
        return pinfo
    if not live:
        return pinfo
    preferred = [m for m in pinfo.get("models", []) if m in live]
    rest = sorted(m for m in live if m not in preferred)
    out = dict(pinfo)
    out["models"] = (preferred + rest) if preferred else rest
    if preferred:
        out["default_model"] = preferred[0]
    return out


def model_selector(container, pinfo: dict, state_key: str) -> str:
    """Model dropdown per provider, with a Custom escape hatch."""
    options = list(pinfo.get("models", [pinfo["default_model"]]))
    options.append("Custom…")
    # a stored selection that has since been retired must not pin the
    # dropdown to a dead model
    _mk = f"{state_key}_modelsel"
    if st.session_state.get(_mk) not in options:
        st.session_state.pop(_mk, None)
    sel = container.selectbox(
        "Model", options, key=f"{state_key}_modelsel",
        help="Common models for this provider; pick Custom… to type any "
             "model ID available to your key.")
    if sel == "Custom…":
        return container.text_input(
            "Custom model ID", value=pinfo["default_model"],
            key=f"{state_key}_modelcustom")
    return sel


def ai_provider_block(state_key: str) -> tuple[str, str | None, str]:
    """THE provider/model/key selection block, extracted verbatim from
    ai_narrative_panel and rendered by every AI feature (narratives,
    umbrella propose, CAB grouping). One code path — 'the key works in
    one section but not another' is structurally impossible.

    Returns (provider, model, api_key)."""
    _managed = managed_ai_key()
    _use_managed = (st.session_state.get(sk.AI_MANAGED, bool(_managed))
                    and bool(_managed))
    if _use_managed:
        # Managed default: the credential is never rendered. Only the
        # model is offered — and the own-key switch is RIGHT HERE, in
        # every panel, not routed through one page. The switch is one
        # app-wide state: flipping it anywhere flips it everywhere.
        pcol1, pcol2 = st.columns([1, 1])
        pcol1.caption("Managed NVIDIA endpoint — no key required.")
        provider = "nvidia"
        pinfo = refresh_models(PROVIDERS[provider], _managed)
        model = model_selector(pcol2, pinfo, f"{state_key}_nvidia")
        api_key = _managed
        if st.button("Use my own API key instead",
                     key=f"{state_key}_own"):
            st.session_state[sk.AI_MANAGED] = False
            st.rerun()
    else:
        pcol1, pcol2 = st.columns(2)
        _pk = f"{state_key}_provider"
        if _pk not in st.session_state and st.session_state.get(
                sk.AI_PROVIDER):
            st.session_state[_pk] = st.session_state[sk.AI_PROVIDER]
        provider = pcol1.selectbox(
            "AI provider",
            options=list(PROVIDERS.keys()),
            format_func=lambda p: PROVIDERS[p]["label"],
            key=_pk,
        )
        pinfo = PROVIDERS[provider]
        env_key = os.environ.get(pinfo["env_var"], "")
        if provider == "gemini" and not env_key:
            env_key = os.environ.get("GOOGLE_API_KEY", "")
        # refresh the model list from whatever key is already known
        # (typed on a previous rerun, session, or environment)
        _key_cand = (st.session_state.get(f"{state_key}_key")
                     or st.session_state.get(sk.AI_KEY) or env_key)
        pinfo = refresh_models(pinfo, _key_cand)
        model = model_selector(pcol2, pinfo, f"{state_key}_{provider}")
        api_key = st.text_input(
            f"{pinfo['label']} API key",
            type="password",
            value=st.session_state.get(sk.AI_KEY) or env_key,
            help=f"Get a key at {pinfo['key_hint']}. Used only for "
                 "this request; never stored.",
            key=f"{state_key}_key",
        )
        if _managed and st.button("Back to the managed NVIDIA "
                                  "endpoint", key=f"{state_key}_bk"):
            st.session_state[sk.AI_MANAGED] = True
            st.rerun()
    return provider, model, api_key


def ai_narrative_panel(
    state_key: str,
    prompt_builder,
    file_stub: str,
    default_template: str,
    chart_png_builder=None,
) -> str | None:
    """Provider/model/key picker + streaming narrative, shared by all modules.

    ``prompt_builder`` is called with the (possibly analyst-edited) report
    template at generation time. The objectivity rules are baked into the
    prompt separately and cannot be edited here — only the section structure.
    Returns the generated narrative (persisted in session state) or None.
    """
    with st.expander("🤖 AI Narrative Report", expanded=False):
        template = st.text_area(
            "Report section template (editable)",
            value=default_template,
            height=220,
            key=f"{state_key}_tmpl",
            help="Defines the headings and what each section should cover. "
                 "The objectivity rules (only supplied figures, no blame, "
                 "reproduce all caveats) are fixed and applied regardless.",
        )
        provider, model, api_key = ai_provider_block(state_key)

        if st.button("Generate narrative", type="primary",
                     disabled=not api_key, key=f"{state_key}_go"):
            prompt = prompt_builder(template or default_template)
            try:
                with st.spinner("Drafting narrative from the results..."):
                    text = st.write_stream(
                        stream_narrative(provider, api_key, prompt, model or None)
                    )
                st.session_state[state_key] = text
            except NarrativeError as exc:
                st.error(exc.message)
        elif state_key in st.session_state:
            st.markdown(st.session_state[state_key])

        narrative = st.session_state.get(state_key)
        if narrative:
            _figs = None
            if chart_png_builder is not None:
                try:
                    _figs = chart_png_builder()
                except Exception:
                    _figs = None       # a figure must never block the text
            st.download_button(
                "⬇️ Download narrative (Word)",
                data=build_narrative_docx(
                    file_stub.replace("_", " ").title() + " — Narrative",
                    narrative, images=_figs),
                file_name=f"{file_stub}_narrative.docx",
                mime="application/vnd.openxmlformats-officedocument."
                     "wordprocessingml.document",
                key=f"{state_key}_dl",
            )
    return st.session_state.get(state_key)


def _register_records(*, require_fragnet: bool = False) -> list:
    """(DelayEvent, fragnet) pairs from the shared TIA event register."""
    recs = []
    for rec in st.session_state.get(sk.EVENT_REGISTER, {}).values():
        parsed = event_from_dict(rec)
        if parsed and (parsed[1] or not require_fragnet):
            recs.append(parsed)
    return recs
