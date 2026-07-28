"""The cross-page session-state contract.

Streamlit session state is stringly-typed; under st.navigation only ONE
page renders per rerun, so widget-backed keys DIE when their widget is
not rendered (a bug class this app has already been bitten by). Every
key that more than one page reads or writes is therefore declared here,
once, as a named constant — a typo becomes an AttributeError at import
time instead of a silent None at runtime.

Rules:
* Cross-page data lives under these constants, in PLAIN (non-widget)
  keys, so it survives page switches.
* Page-local widget keys stay literal in their page and MUST NOT be
  read anywhere else.
* Never pass a `default=` alongside a session-state `key=` on a widget
  (Streamlit warns and the default silently loses).
"""

# --- intake: the shared uploaded-programme pool -------------------------
XER_POOL = "xer_pool"            # list[(file_name, XerData)]
XER_POOL_SIG = "xer_pool_sig"    # upload signature for cache invalidation
XER_RAW = "xer_raw"              # dict[file_name, bytes] original files
XER_HASHES = "xer_hashes"        # dict[file_name, sha256] chain of custody
INVENTORY = "inventory"          # ProgrammeInventory (roles + data dates)

# --- shared AI credentials (registered once, used by all modules) -------
AI_KEY = "tia_key"               # historical names kept for session
AI_PROVIDER = "tia_provider"     # continuity; treat as the ONE canonical
AI_MODEL = "tia_model"
AI_MANAGED = "ai_managed"  # True = using the deployment's own
#                            NVIDIA key (never displayed)           # credential set for the whole app

# --- shared analysis records --------------------------------------------
EVENT_REGISTER = "tia_register"  # dict[event_id, event_to_dict(...)] —
#                                  written by TIA and Impacted As-Planned,
#                                  read by the concurrency sub-module
ANALYSIS_BASIS = "analysis_basis"  # dict[module, list[str]] — scheduling
#                                    basis lines for the report appendix
CONTRACT_MS = "contract_completion_ms"  # analyst-flagged contractual
#                                         completion milestone code

# --- As-Planned vs As-Built stepped method ------------------------------
# Multi-milestone: each elected milestone carries its own adopted path,
# basis election and measurement (Ozan 2026-07-27 spec).
APAB_MS = "apab_ms"                  # [milestone codes] elected in step ①
APAB_PATHS = "apab_paths"            # dict[ms, [(code, name)]] adopted CP
APAB_PATH_BASIS = "apab_path_basis"  # dict[ms, basis label] (disclosed)
APAB_KEYDATES = "apab_keydates"      # dict[code, why-key note]
APAB_DATE_BASIS = "apab_date_basis"  # "late" (default) | "early"

# --- Umbrella activities (work-package roll-up) -------------------------
# ONE grouping, defined once and reused wherever an as-built activity
# list is presented. Analyst-confirmed; AI may only propose it.
UMBRELLAS = "umbrella_groups"        # dict[umbrella name, [task_code]]
UMBRELLA_PROPOSED = "umbrella_proposed"   # last AI proposal (unconfirmed)
UMBRELLA_ON = "umbrella_on"          # bool — measure on umbrella rows
UMBRELLA_ROUNDS = "umbrella_rounds"  # AI refinement trajectory (audit)

# --- Impacted As-Planned / Collapsed As-Built ---------------------------
IAP_EVENTS = "iap_events"        # on-page event rows (standalone capture)
IAP_RES = "iap_res"              # last run result dict
IAP_LABEL = "iap_label"          # baseline label of that run
CAB_GROUPS = "cab_groups"        # proposed candidate groups
CAB_EXTRACT = "cab_extract"      # analyst-confirmed extraction codes
CAB_RES = "cab_res"              # last CollapseResult

# --- access gate ---------------------------------------------------------
AUTH_OK = "auth_ok"              # password gate passed this session


def explain_confirmed_key(target: str) -> str:
    """Analyst-confirmed drivers for one explain target milestone."""
    return f"explain_confirmed_{target}"


def narrative_key(module: str, ident: str = "") -> str:
    """AI-narrative session key for a module (+ optional identifier)."""
    return f"nar_{module}" + (f"_{ident}" if ident else "")
