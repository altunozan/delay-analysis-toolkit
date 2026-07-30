# Harbour Point District Cooling Plant DCP-03 — demonstration programmes

A fictional but fully coherent EPC project built to exercise the whole
As-Planned vs As-Built method end to end. Both files are generated from one
network by [`build_programmes.py`](build_programmes.py), so the pair is
internally consistent: the baseline's critical path genuinely carries zero
total float, and every as-built date is the arithmetic product of the
recorded durations and the delay events listed below.

| | Baseline Programme Rev 0 | As-Built Programme Rev 12 |
|---|---|---|
| Data date | 08 Jan 2024 (contract start) | **12 Dec 2025 (completion)** |
| Status | all not started | all 61 activities complete |
| Completion | 11 Sep 2025 | 12 Dec 2025 |
| Activities | 60 | 61 |
| Relationships | 76 | 77 |

**Overall outcome: 92 calendar days late.**

## The delay story — incremental, phase by phase

Five key-date milestones close the five phases. Slippage accrues steadily,
so every window contributes and none dominates:

| Window | Key date | Planned | As-built | Accrued | Cumulative |
|---|---|---|---|---|---|
| ① Engineering | E-1080 Design Freeze | 27 May 24 | 11 Jun 24 | **+15 d** | +15 d |
| ② Procurement | P-2060 Chillers Delivered | 31 Dec 24 | 03 Feb 25 | **+19 d** | +34 d |
| ③ Construction | C-3070 Mechanical Completion | 21 Apr 25 | 11 Jun 25 | **+17 d** | +51 d |
| ④ Commissioning & snagging | T-4070 Systems Accepted | 12 Aug 25 | 22 Oct 25 | **+20 d** | +71 d |
| ⑤ Handover | H-5040 Substantial Completion | 11 Sep 25 | 12 Dec 25 | **+21 d** | +92 d |

### What caused each window

Every delayed activity carries its event reference in the **Delay Event
Reference** user-defined field, and an asserted responsibility in the
**Responsibility (asserted)** activity code — so the tool can attribute
without anyone having to remember the story.

**① Engineering (+15 d)** — the Employer's concept-design review over-ran
by 8 working days (DE-01, E-1030), and the resulting capacity change added
2 days to mechanical detailed design and 4 to electrical (DE-02). The
electrical IFC issue then slipped a further 3 days (DE-03, E-1075), which
is what actually set the Design Freeze date.

**② Procurement (+19 d)** — the chiller vendor lost 14 days to a compressor
supply shortage in manufacture (DE-04, P-2030) and a further 5 days to port
congestion on the delivery voyage (DE-05, P-2050). Long-lead procurement
inherits the engineering slip in full: nothing recovered it.

**③ Construction (+17 d)** — pipework installation under-performed by 9
days (DE-09, C-3030) and the Employer instructed additional pipework for
the revised chiller layout under VO-07 (DE-10, C-3035 — an activity that
exists only in the as-built programme). Two mitigations partly offset it:
the Contractor resequenced electrical containment and **recovered 4 days**
(DE-11, C-3100), and insulation was started 3 days before pipework
connections finished (out-of-sequence working).

**④ Commissioning & snagging (+20 d)** — the vendor's commissioning
engineer mobilised 7 days late (DE-12, T-4020), and the volume of snags
required 9 extra days of rectification plus an unplanned **second
rectification pass** (DE-13, T-4050 / T-4055). Pre-commissioning was
started 2 days early against static testing to claw time back.

**⑤ Handover (+21 d)** — the authority inspection failed at the first
attempt and the re-visit cost 10 days (DE-14, H-5020), with a further 5
days compiling the taking-over documentation (DE-15, H-5030).

### Concurrency, deliberately included

While the mechanical chain was driving completion, the electrical chain was
slipping in parallel: late electrical/builders-work information (DE-03,
E-1090 +12 d) and late switchgear delivery (DE-06, P-2100 +10 d) pushed
switchgear installation, cabling and BMS wiring out by 15 working days.
That chain absorbs its own float rather than driving the outcome — a clean
concurrency-screening exercise with a genuine answer rather than a trap.

## What each feature will show

- **As-built critical path (step ①)** — both candidate methods agree:
  34 activities from Notice to Proceed to Substantial Completion. The
  programme's own longest path and the actual recorded sequence produce
  the same chain with **zero unlogged hand-offs**, so the election is
  well-founded rather than a guess.
- **Umbrella work packages** — the 34 path activities group cleanly into
  the five phases (8 / 7 / 7 / 9 / 3 activities). Each umbrella reports a
  named driving member and the variance escalates +15 → +34 → +51 → +71 →
  +92 days, package by package. This is the view to show first.
- **Key-date windows (step ③)** — reproduces the table above from the
  files alone, with no resequencing artefacts flagged.
- **Revision comparison** — 2 added activities (C-3035, T-4055), 1 deleted
  (P-2150, the standby chiller descoped by VO-03), 1 revised original
  duration (E-1040, 30 → 32 d) and 2 relationship changes.
- **Out-of-sequence** — exactly 2 genuine records (C-3040 → C-3050,
  T-4000 → T-4010); no noise.
- **Milestone shift tracker** — all 6 milestones matched across both
  files, no fuzzy matches needing confirmation.
- **DCMA 14-point** — a deliberately realistic health profile: logic
  passes at 5.2% open ends (3: the start milestone, the completion
  milestone and the descoped package), and High Float / High Duration /
  Resources findings come from genuine long-lead procurement rather than
  sloppiness. The AI narrative has real material to work with, and the
  balance rule has real strengths to report.
- **S-curve** — planned vs recorded with a ~73-day time offset.
- **Float erosion** — 32 critical activities in the baseline, all float
  consumed by completion.
- **Hierarchy rebuild / variance dimensions** — 3 WBS levels plus four
  global activity code types (Project Phase, Discipline, Area / Location,
  Responsibility) and three activity UDFs, all assigned on every activity.
- **Resources** — 6 labour resources across 45 monthly histogram buckets.

## Using them

Upload **both** files on the intake page (baseline first), flag Rev 0 as
the contract baseline, then work through As-Planned vs As-Built ① → ④.
For the umbrella step, ask the AI to propose work packages: with these
activity names it will land on the five phase packages, and you confirm.

Calendars are Gulf-realistic — 5-day office, 6-day site, 7-day
manufacture/shipping — with Eid and National Day holidays, so working-day
arithmetic is exercised rather than assumed.

## Regenerating

```bash
python3 build_programmes.py
```

The delay quanta live in the `ab=dict(...)` entries of the `ACTS` table:
`dd` duration delta, `sd` waiting time, `ov` out-of-sequence overlap, `od`
revised original duration, `new` / `gone` for added and descoped scope.
Change a number and the whole pair re-solves consistently.

> Fictional data for demonstration and testing. Not a real project, and
> not a record of any real party's performance.
