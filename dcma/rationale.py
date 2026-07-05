"""Static DCMA rationale text: why each check's target matters.

Used by the Excel report (rationale column) and as grounding context for
the AI narrative generator.
"""

CHECK_RATIONALE: dict[int, str] = {
    1: (
        "Activities without predecessors/successors are disconnected from the "
        "network. Dangling logic breaks critical-path continuity and lets the "
        "schedule show dates that no logic actually drives."
    ),
    2: (
        "Leads (negative lags) force successor work to start before its "
        "predecessor finishes, obscuring true sequence and distorting float. "
        "DCMA expects zero; preferred practice is to split activities instead."
    ),
    3: (
        "Lags are invisible, un-resourced 'black box' durations. Excessive "
        "lags hide real work or waiting time and make the critical path hard "
        "to defend in a delay claim."
    ),
    4: (
        "Finish-to-Start is the clearest, most defensible relationship type. "
        "Heavy use of SS/FF (and any SF) links complicates logic tracing and "
        "can conceal out-of-sequence conditions."
    ),
    5: (
        "Hard constraints override network logic and pin dates artificially. "
        "They can suppress or fabricate float, mask delays, and are a classic "
        "flag for schedule manipulation in forensic review."
    ),
    6: (
        "Very high float usually signals missing logic rather than genuine "
        "flexibility. It undermines confidence that the network models how "
        "the work will actually be performed."
    ),
    7: (
        "Negative float means the schedule cannot meet a constrained date — "
        "the plan is already in delay against a commitment. It quantifies the "
        "recovery needed and drives claims exposure."
    ),
    8: (
        "Long-duration activities hide detail and reduce statusing accuracy. "
        "Breaking them down improves progress measurement and critical-path "
        "visibility."
    ),
    9: (
        "Actual dates in the future or forecast dates in the past contradict "
        "the data date and corrupt the CPM calculation. They are a basic "
        "integrity failure that invalidates downstream analysis."
    ),
    10: (
        "Un-resourced activities cannot be cost- or effort-validated. A "
        "resource-loaded schedule supports earned value and makes durations "
        "defensible."
    ),
    11: (
        "Missed tasks measure execution against the baseline plan. A high "
        "miss rate signals systemic slippage rather than isolated variance."
    ),
    12: (
        "A valid, continuous critical path is the backbone of any delay "
        "analysis. If no coherent zero-float path exists, the schedule cannot "
        "reliably forecast completion or apportion delay."
    ),
    13: (
        "CPLI measures how efficiently the remaining critical path must be "
        "executed to hit the target finish. Below 0.95 means the project "
        "must out-perform its own plan to finish on time."
    ),
    14: (
        "BEI compares tasks completed against tasks planned to be complete. "
        "Below 0.95 indicates the project is not executing to baseline, an "
        "early warning of cumulative delay."
    ),
}
