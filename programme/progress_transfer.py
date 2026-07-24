"""Module 17 — Progress Transfer.

Statuses one programme's network (the *network donor* — typically the
baseline or an earlier trusted update) with another programme's recorded
progress (the *progress donor* — typically a later update), then runs the
same calendar-exact simplified CPM used by the TIA engine on BOTH:

    transferred run : donor network + recipient's actuals
    reference run   : progress donor's own network + its own actuals

Because the progress is held identical between the two runs, the
difference in forecast completion is attributable to the NETWORK
differences between the files — which is exactly the quantity a
re-sequencing or covert programme edit tries to hide.

The effect is DECOMPOSED so that scope change is never conflated with
re-sequencing:

* **logic/duration effect** (the headline ``network_effect_days``) —
  computed on the INTERSECTION network: only activities present in both
  files, so added/deleted scope cannot contaminate the figure;
* **scope effect** (``scope_effect_days``) — the further movement that
  appears when the network donor's unmatched activities (work the other
  file no longer carries, modelled unstarted at full duration) are
  included.

Statusing choices (all disclosed as standing caveats):
  * retained logic — remaining work respects both the data date and its
    incomplete predecessors;
  * remaining durations for matched in-progress activities are taken
    from the progress donor (the recorded assessment of remaining work);
  * activities completed in the progress donor are removed from the
    remaining network, releasing their successors at the data date —
    the same simplification the TIA engine uses, so the two runs are
    method-consistent;
  * network-donor activities with no match in the progress donor are
    modelled as unstarted at full duration.

The output is an analytical comparison. It is NOT a schedule submission
and no impacted programme file is produced.

Pure engine: two XerData in, structured result out. No LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from dcma.config import DCMAConfig
from dcma.xer_parser import XerData

from .comparison_impact import OOS_CAVEATS, out_of_sequence_flags
from .tia import (
    _START_FLOOR_CSTR,
    _REL_TO_SHORT,
    _build_network,
    _calendar_masks,
    _forward_pass,
    _parse_xer_date,
)

STANDING_CAVEATS = [
    "Statusing method: retained logic — remaining work respects both the "
    "data date and its incomplete predecessors.",
    "Remaining durations for matched in-progress activities are taken "
    "from the progress donor file (the recorded assessment of remaining "
    "work); unmatched activities keep the network donor's full duration, "
    "unstarted.",
    "Activities completed in the progress donor are removed from the "
    "remaining network and their successors are released at the data "
    "date — the same simplification as the TIA engine, so both runs are "
    "method-consistent and the DELTA is the reliable figure.",
    "Both forecasts come from the same simplified calendar-exact CPM, "
    "not from P6. Judge the difference between the runs, not the "
    "absolute dates; the calibration figure discloses the approximation "
    "error against P6's own forecast.",
    "The logic/duration effect is measured on the intersection network "
    "(activities present in BOTH files) so that scope additions or "
    "deletions cannot masquerade as re-sequencing; movement caused by "
    "unmatched network-donor activities is reported separately as the "
    "scope effect.",
    "The transferred programme is an analytical construction for "
    "comparison only — it is not a schedule submission and is not "
    "exported.",
]


@dataclass
class TransferMilestone:
    code: str
    name: str
    transferred: datetime | None      # donor network + recipient progress
    reference: datetime | None        # progress donor's own run

    @property
    def delta_days(self) -> float | None:
        if self.transferred and self.reference:
            return round((self.transferred
                          - self.reference).total_seconds() / 86400, 1)
        return None


@dataclass
class ProgressTransferResult:
    network_label: str
    progress_label: str
    data_date: datetime | None = None

    applied_starts: int = 0           # in-progress actuals transferred
    applied_finishes: int = 0         # completed activities transferred
    not_in_progress_file: int = 0     # network acts with no progress match
    unmatched_progress: list[str] = field(default_factory=list)
    oos_flags: list = field(default_factory=list)
    #   ^ out-of-sequence records in the PROGRESS DONOR: actuals that
    #     contradict its own logic. Retained-logic statusing re-imposes
    #     the planned logic these records contradict, so they qualify
    #     the transferred forecast and are disclosed explicitly.
    #   ^ actualised activities in the progress donor absent from the
    #     network donor — their progress cannot be transferred

    completion_transferred: datetime | None = None
    #   ^ full transferred run (intersection + unmatched scope)
    completion_logic_only: datetime | None = None
    #   ^ intersection-only transferred run (activities in BOTH files)
    completion_reference: datetime | None = None
    network_effect_days: float | None = None
    #   ^ HEADLINE: logic_only − reference — forecast movement from
    #     logic/duration/constraint differences alone, scope excluded
    scope_effect_days: float | None = None
    #   ^ transferred − logic_only — further movement from network-donor
    #     activities the progress file no longer carries

    calibration_days: float | None = None
    #   ^ reference run vs the progress donor's own P6 scheduled finish

    milestones: list[TransferMilestone] = field(default_factory=list)
    driving_chain: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


def _network_with_progress(
    net: XerData,
    prog: XerData,
    config: DCMAConfig,
    dd: datetime,
) -> tuple[dict, dict, dict, dict, list[str]]:
    """Build the transferred CPM network.

    Nodes/logic/durations/calendars come from ``net``; actual progress
    comes from ``prog``. Mirrors ``tia._build_network`` so the transferred
    and reference runs share one method.
    """
    masks = _calendar_masks(net)
    warnings: list[str] = []
    prog_by_code = {t.task_code: t for t in prog.tasks
                    if not t.is_loe_or_wbs}

    stats = {"starts": 0, "finishes": 0, "unmatched": 0}
    nodes: dict[str, tuple] = {}
    started: dict[str, datetime] = {}
    code_of: dict[str, str] = {}
    for t in net.tasks:
        if t.is_loe_or_wbs:
            continue
        code = t.task_code
        p = prog_by_code.get(code)
        if p is not None and p.act_finish is not None:
            stats["finishes"] += 1          # complete: leaves the network
            continue
        hpd_net = net.hours_per_day(t, config)
        if p is not None and p.act_start is not None:
            hpd_p = prog.hours_per_day(p, config)
            rem = p.remaining_duration_days(hpd_p)
            if rem is None:
                rem = p.original_duration_days(hpd_p) or 0.0
            nodes[code] = (max(rem, 0.0), masks.get(t.clndr_id))
            started[code] = dd
            stats["starts"] += 1
        else:
            if p is None:
                stats["unmatched"] += 1
            dur = t.original_duration_days(hpd_net) or 0.0
            nodes[code] = (max(dur, 0.0), masks.get(t.clndr_id))
        code_of[t.task_id] = code

    # Start constraints from the NETWORK donor as early-start floors —
    # identical treatment to tia._build_network.
    floored = 0
    for row in net.raw_tables.get("TASK", []):
        code = (row.get("task_code") or "").strip()
        if code not in nodes or code in started:
            continue
        for tkey, dkey in (("cstr_type", "cstr_date"),
                           ("cstr_type2", "cstr_date2")):
            ctype = (row.get(tkey) or "").strip()
            if ctype in _START_FLOOR_CSTR:
                cdate = _parse_xer_date(row.get(dkey) or "")
                if cdate is not None:
                    started[code] = max(started.get(code, cdate), cdate)
                    floored += 1
    if floored:
        warnings.append(
            f"{floored} start constraint(s) from the network donor "
            "applied as early-start floors.")

    preds: dict[str, list] = {n: [] for n in nodes}
    for rel in net.relationships:
        s = code_of.get(rel.task_id)
        p = code_of.get(rel.pred_task_id)
        if s is None or p is None or s not in nodes or p not in nodes:
            continue
        pred_task = next((t for t in net.tasks
                          if t.task_id == rel.pred_task_id), None)
        if pred_task is None:
            continue
        hpd = net.hours_per_day(pred_task, config)
        lag = (rel.lag_hr / hpd) if rel.lag_hr else 0.0
        preds[s].append((p, _REL_TO_SHORT.get(rel.pred_type, "FS"), lag))

    stats_msg: list[str] = []
    if stats["unmatched"]:
        stats_msg.append(
            f"{stats['unmatched']} network activities have no counterpart "
            "in the progress file and are modelled as unstarted at full "
            "duration.")
    warnings.extend(stats_msg)
    return nodes, preds, started, stats, warnings


def run_progress_transfer(
    network: XerData,
    progress: XerData,
    network_label: str,
    progress_label: str,
    *,
    config: DCMAConfig | None = None,
    top_milestones: int = 20,
) -> ProgressTransferResult:
    """Status the donor network with the recipient's progress and compare."""
    config = config or DCMAConfig()
    result = ProgressTransferResult(network_label=network_label,
                                    progress_label=progress_label)
    result.caveats.extend(STANDING_CAVEATS)

    dd = progress.project.data_date if progress.project else None
    if dd is None:
        result.warnings.append(
            "The progress donor has no data date — cannot status the "
            "network or run the forward pass.")
        return result
    result.data_date = dd

    # --- transferred run: donor network + recipient progress -------------
    nodes_t, preds_t, started_t, stats, wn = _network_with_progress(
        network, progress, config, dd)
    result.warnings.extend(wn)
    result.applied_starts = stats["starts"]
    result.applied_finishes = stats["finishes"]
    result.not_in_progress_file = stats["unmatched"]

    net_codes = {t.task_code for t in network.tasks if not t.is_loe_or_wbs}
    result.unmatched_progress = sorted(
        t.task_code for t in progress.tasks
        if not t.is_loe_or_wbs and t.task_code not in net_codes
        and (t.act_start or t.act_finish))
    # --- out-of-sequence disclosure (progress donor) ---------------------
    result.oos_flags = out_of_sequence_flags(progress)
    if result.oos_flags:
        n_conc = sum(1 for f in result.oos_flags
                     if f.rec_link_type not in ("", "review"))
        result.warnings.append(
            f"{len(result.oos_flags)} out-of-sequence progress record(s) "
            f"in '{progress_label}' — retained-logic statusing re-imposes "
            "planned logic that these recorded actuals contradict, so "
            "where out-of-sequence work is heavy the transferred forecast "
            "overstates the planned network's constraint. "
            f"{n_conc} of the flags carry a concrete as-built relation "
            "fit; see the out-of-sequence table.")
        result.caveats.extend(
            c for c in OOS_CAVEATS if c not in result.caveats)

    if result.unmatched_progress:
        sample = ", ".join(result.unmatched_progress[:8])
        result.warnings.append(
            f"{len(result.unmatched_progress)} actualised activities in "
            f"'{progress_label}' do not exist in '{network_label}' and "
            f"their progress cannot be transferred (e.g. {sample}"
            + (" …" if len(result.unmatched_progress) > 8 else "") + ").")

    if not nodes_t:
        result.warnings.append(
            "Nothing remains to schedule — every network activity is "
            "complete in the progress file.")
        return result

    ES_t, EF_t, w_t, drv_t = _forward_pass(
        dict(nodes_t), {k: list(v) for k, v in preds_t.items()},
        dd, started_t)

    # --- intersection-only run: logic/duration effect, scope excluded ----
    prog_codes = {t.task_code for t in progress.tasks
                  if not t.is_loe_or_wbs}
    keep = {c for c in nodes_t if c in prog_codes}
    nodes_i = {c: nodes_t[c] for c in keep}
    preds_i = {c: [(p, lt, lg) for (p, lt, lg) in preds_t.get(c, [])
                   if p in keep]
               for c in keep}
    started_i = {c: d for c, d in started_t.items() if c in keep}
    ES_i, EF_i, w_i, drv_i = _forward_pass(
        dict(nodes_i), {k: list(v) for k, v in preds_i.items()},
        dd, started_i)

    # --- reference run: the progress donor scheduled by the same method --
    inc_r, nodes_r, preds_r, started_r, _masks_r, w_r = _build_network(
        progress, config, dd)
    ES_r, EF_r, w_r2, drv_r = _forward_pass(
        dict(nodes_r), {k: list(v) for k, v in preds_r.items()},
        dd, started_r)
    result.warnings.extend(sorted(set(w_t + w_i + w_r + w_r2)))

    if EF_t:
        result.completion_transferred = max(EF_t.values())
    if EF_i:
        result.completion_logic_only = max(EF_i.values())
    if EF_r:
        result.completion_reference = max(EF_r.values())
    if result.completion_logic_only and result.completion_reference:
        result.network_effect_days = round(
            (result.completion_logic_only
             - result.completion_reference).total_seconds() / 86400, 1)
    if result.completion_transferred and result.completion_logic_only:
        result.scope_effect_days = round(
            (result.completion_transferred
             - result.completion_logic_only).total_seconds() / 86400, 1)

    # --- calibration: reference run vs the progress donor's P6 forecast --
    p6_fin = progress.project.scheduled_finish if progress.project else None
    if p6_fin and result.completion_reference:
        result.calibration_days = round(
            (result.completion_reference - p6_fin).total_seconds() / 86400,
            1)
        result.warnings.append(
            f"Calibration: this engine schedules '{progress_label}' to "
            f"{result.completion_reference:%Y-%m-%d} vs P6's own "
            f"{p6_fin:%Y-%m-%d} ({result.calibration_days:+.0f}d "
            "approximation error). Judge the network-effect DELTA, not "
            "the absolute dates.")

    # --- milestone comparison --------------------------------------------
    ms_net = {t.task_code: t.name for t in network.tasks
              if not t.is_loe_or_wbs and t.is_milestone}
    rows = [TransferMilestone(code=c, name=n,
                              transferred=EF_t.get(c),
                              reference=EF_r.get(c))
            for c, n in ms_net.items()
            if c in EF_t and c in EF_r]
    rows.sort(key=lambda m: -abs(m.delta_days or 0))
    result.milestones = rows[:top_milestones]

    # --- driving chain of the transferred run ----------------------------
    names = {t.task_code: t.name for t in network.tasks
             if not t.is_loe_or_wbs}
    if EF_t:
        cur = max(EF_t, key=lambda k: EF_t[k])
        chain, seen = [], set()
        while cur and cur not in seen and len(chain) < 400:
            seen.add(cur)
            chain.append({"id": cur, "name": names.get(cur, cur),
                          "start": ES_t.get(cur), "finish": EF_t.get(cur)})
            cur = drv_t.get(cur)
        chain.reverse()
        result.driving_chain = chain

    # --- headline reading: logic/duration effect (scope excluded) --------
    if result.network_effect_days is not None:
        if abs(result.network_effect_days) < 1.0:
            result.warnings.append(
                "Logic/duration effect is negligible: on the activities "
                "the two files share, and with identical progress, both "
                "networks forecast essentially the same completion — "
                "the logic, duration and constraint edits between these "
                "files did not move the forecast.")
        elif result.network_effect_days > 0:
            result.warnings.append(
                f"Logic/duration effect {result.network_effect_days:+.0f}d: "
                f"on the shared activities, with identical progress, "
                f"'{network_label}' forecasts completion "
                f"{result.network_effect_days:+.0f}d later than "
                f"'{progress_label}' schedules itself — the logic, "
                "duration and constraint edits between the files "
                "IMPROVED the forecast by that amount. Cross-check "
                "those edits in the revision-comparison materiality "
                "screening.")
        else:
            result.warnings.append(
                f"Logic/duration effect {result.network_effect_days:+.0f}d: "
                f"on the shared activities, with identical progress, "
                f"'{network_label}' forecasts completion "
                f"{abs(result.network_effect_days):.0f}d earlier than "
                f"'{progress_label}' schedules itself — the network "
                "edits between the files worsened the forecast; the "
                "movement is not explained by progress alone.")
    if (result.scope_effect_days is not None
            and abs(result.scope_effect_days) >= 1.0):
        result.warnings.append(
            f"Scope effect {result.scope_effect_days:+.0f}d ON TOP of the "
            f"logic/duration effect: {result.not_in_progress_file} "
            f"network-donor activities with no counterpart in "
            f"'{progress_label}' (modelled unstarted at full duration) "
            "move the transferred forecast by this further amount. This "
            "is SCOPE change — descoped, replaced or re-coded work — "
            "not re-sequencing, and the two must not be conflated; see "
            "the added/deleted lists in the revision comparison.")
    return result
