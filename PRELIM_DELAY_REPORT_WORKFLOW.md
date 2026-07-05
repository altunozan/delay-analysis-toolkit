# Preliminary Delay Analysis Report — Automation Workflow

## Design principle (taken from `dcma/`)

The existing `dcma/` package already establishes the right pattern:

```
parser (raw file -> typed data)
   -> pure check/engine functions (typed data + config -> structured CheckResult)
      -> narrative.py (structured results + locked system prompt -> LLM prose)
```

The LLM never computes; it only narrates numbers it is handed, under a system
prompt that explicitly forbids extrapolation (`narrative.py:49-56`). Every
module below reuses this exact separation. `CheckResult` is the template for
every module's output object: a typed result with `metric_value`,
`affected_ids`, `detail_rows`, and (new) provenance fields — not prose.

Two module classes, treated differently:

| Class | Examples | LLM role | Report status |
|---|---|---|---|
| **Deterministic** | DCMA-14, milestone shifts, manpower curves, as-planned vs as-recorded | Narrates a finished table/chart, cannot alter it | Auto-final |
| **Interpretive** | Event register, notice compliance, methodology, EOT strategy | Drafts candidates; analyst promotes/edits | Analyst-must-review before use |

---

## Module specs

### 0. Intake & Data Inventory
- **Input:** all uploaded XERs, correspondence set, contract, labour records.
- **Engine:** reuse `dcma/xer_parser.parse_xer` per file → collect `Project.data_date`, `Project.short_name`, file name, row counts. Diff filenames/data dates to build a revision timeline.
- **Output:** `DataInventory` — list of `{file, data_date, baseline_flag, row_counts}` + a `missing[]` list (e.g. "no correspondence set provided", "no resourced baseline").
- **LLM:** none. Pure listing.
- **Feeds:** everything (data dates → module 3; missing[] → module 8 caveats).

### 1. Programme Examination — DCMA-14 (existing, reuse as-is)
- **Engine:** `dcma.run_all_checks(xer_data, config)` — no changes needed.
- **Narrative:** `dcma.narrative` — reframe the prompt's framing line to state explicitly: *"This is a schedule reliability/health check, not a delay-causation analysis; its purpose is to establish whether the programme is a trustworthy analytical instrument for the findings in later sections."* Add this one sentence to `SYSTEM_PROMPT` in `narrative.py`.
- **Output:** table (existing `report_xlsx.py`) + narrative.
- **Feeds:** module 8 (any FAIL becomes a caveat), gates confidence in modules 3/4/6.

### 2. Delay Event Register + Notice Compliance
- **Input:** correspondence set (letters, RFIs, notices), contract clause map (module 5).
- **Engine (new):** LLM extraction pass, but constrained like a `CheckResult` —every candidate event must carry:
  ```
  EventCandidate(event_id, date_raised, description, source_doc, source_snippet,
                 party_alleged, affected_activities[], notice_ref)
  ```
  No candidate without a `source_doc` + `source_snippet` is emitted. This is a register, not a chronology — analyst promotes/edits/rejects each row.
- **Notice compliance sub-engine (deterministic once dates are confirmed):** a small state machine per confirmed event, driven off contract clause data from module 5:
  `notice_given? / within_period? (triggering_date, notice_date, period_days from clause map) / correct_form? / particulars_submitted?`
  → status ∈ `{compliant, late, no_notice, indeterminate}`. **The engine emits the status; the LLM/analyst never asserts a time-bar legal conclusion** — only "late per clause X.X" as a factual date comparison.
- **Output:** event register table + compliance matrix. Both analyst-gated.
- **Feeds:** module 3 (link events to slippage), module 6 (method viability), module 9 (caveats: events with `indeterminate` status).

### 3. Milestone Shift Tracker
- **Engine (new, python, deterministic):**
  - Parse each XER revision with existing `xer_parser`.
  - Match milestones across revisions: primary key `task_code`, fallback fuzzy `name` match (e.g. `difflib.SequenceMatcher`) surfaced to the user as a confirm-mapping step — never auto-resolved silently.
  - For each confirmed milestone, build a series of `(data_date, forecast_or_actual_date)` across revisions.
  - Prompt user to pick which milestones to chart (per your original idea).
- **Output:** graph — x-axis = data date (revision timeline), y-axis = forecast/actual date per milestone (the standard "slippage banana" view) + narrative describing only the plotted deltas.
- **LLM:** narrates the shift magnitudes/direction only, cites which revision each shift appears between.
- **Feeds:** module 2 (analyst links shift to event), module 9.

### 4. Preliminary As-Planned vs As-Recorded (nice-to-have, sequenced last of the technical modules)
- **Naming fix:** do not call the second series "as-built" — label **"as-recorded"** or **"per updated programme"** unless progress has been independently verified. State this limitation in the narrative every time the module runs.
- **Engine (new, deterministic):** user selects activity code field(s) (area/work type/etc. — read from XER `ACTVCODE`/`TASKACTV` tables already captured in `xer_parser`'s `raw_tables`). Group activities by selected code combination; take min(start) / max(finish) per group, separately for baseline and current/as-recorded. Compute delta per group.
- **Output:** Gantt-style bar comparison (planned band vs recorded band per group) + narrative limited to describing deltas — explicitly labelled "preliminary, indicative, screening-level; not a cause-linked forensic as-planned-vs-as-built."
- **Feeds:** module 9 caveats (always emits a fixed caveat sentence).

### 5. Contract Mechanism Extraction
- **Input:** contract text.
- **Engine:** LLM extraction constrained to clause-mapping only — output `ClauseMap`: `{topic: EOT_entitlement/notice/delay_definition/method_mandated/float_ownership/concurrency, clause_ref, verbatim_snippet, silent: bool}`. Every row must cite a clause reference or set `silent=True`. No free-form commentary field.
- **Output:** clause map table.
- **Feeds:** module 2 (notice period lengths), module 6.

### 6. Method-Viability Assessment (replaces "pick a methodology")
- **Engine:** deterministic scoring against data actually present:
  - Count of XER revisions with clean DCMA results (module 1) → feasibility of windows/observational methods.
  - Baseline DCMA pass/fail → feasibility of TIA (Time Impact Analysis).
  - Single vs multiple confirmed events (module 2) → feasibility of as-planned-vs-as-built / collapsed as-built.
  - `ClauseMap.method_mandated` (module 5) → if the contract mandates a method, that overrides the menu entirely.
- **Output:** a reasoned menu — "Method X: viable/weakened/not viable — because [data fact]" — modeled on recognised frameworks (SCL Protocol, AACE 29R-03 taxonomy: TIA, windows/contemporaneous, as-planned-vs-as-built, collapsed as-built). **Analyst chooses; tool never auto-selects.**

### 7. EOT Strategy / Roadmap — internal document, NOT in the client report
- Rename to **"Internal Case Development Note (Draft / Privileged)"**.
- Content: confirmed events, notice status, method chosen, evidence gaps, next actions.
- Kept in a separate file/output stream from the forensic report; never merged into the client-facing deliverable.

### 8. Manpower Records
- **Input:** daily reports / labour returns / timesheets (not XER — flag if only XER resource loading is available, since that's planned, not actual).
- **Engine:** aggregate by trade/date → planned (from resourced baseline, if available) vs actual overlay chart.
- **Output:** graph, narrative describing divergence only, with a standing caveat on record quality/completeness sourced from module 0's inventory.

### 9. Caveats & Limitations Aggregator
- **Engine:** every module above emits a `caveats: list[str]` field (already implied per-module). This step just concatenates them into one section, deduplicated, ordered by module. No LLM needed — pure aggregation, which is exactly why it's trustworthy as a section.

---

## Sequencing (dependency-ordered)

```
0. Intake & Data Inventory
        │
        ▼
1. DCMA-14 Programme Examination  ──────► gates trust in 3, 4, 6
        │
        ▼
2. Delay Event Register + Notice Compliance ◄── needs 5 (clause map) for compliance matrix
        │
        ▼
3. Milestone Shift Tracker  ──────► quantifies effect events in 2 will be linked to
        │
        ▼
5. Contract Mechanism Extraction (can run parallel to 1-3)
        │
        ▼
6. Method-Viability Assessment  ◄── consumes 1 + 2 + 5
        │
        ▼
4. As-Planned vs As-Recorded (optional)
        │
        ▼
8. Manpower Curve (optional)
        │
        ▼
9. Caveats Aggregation  ◄── pulls from every module
        │
        ▼
7. Internal Strategy Note (privileged, separate artifact)
        │
        ▼
   Report Assembly — deterministic sections auto-drafted,
   interpretive sections analyst-owned, caveats compiled, strategy note excluded
```

## Open design decisions (need your input before build)

1. **Contract form to build first** — FIDIC (which edition), NEC4, or bespoke? Notice-compliance state machine and clause-map extraction (modules 2 & 5) are only reliable if tuned to one form's clause numbering initially; a generic-first approach will underperform on all forms.
2. **LLM provider pattern** — reuse `narrative.py`'s multi-provider registry (Anthropic/OpenAI/Gemini) for the new interpretive modules too, or standardize on one provider for the extraction-heavy modules (2, 5) where prompt tuning matters more than provider choice?
