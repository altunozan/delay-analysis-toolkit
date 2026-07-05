"""CLI test harness for the programme modules (no Streamlit needed).

Runs the intake, milestone-shift, and variance engines against the bundled
multi-revision fixtures in sample/revisions/.

Usage:
    python3 test_programme.py
"""

import glob
import os

from dcma import parse_xer
from programme import (
    activity_code_types,
    build_inventory,
    compute_variance,
    track_milestone_shifts,
)

REV_DIR = os.path.join(os.path.dirname(__file__), "sample", "revisions")


def load_revisions():
    files = []
    for path in sorted(glob.glob(os.path.join(REV_DIR, "*.xer"))):
        with open(path, "rb") as fh:
            files.append((os.path.basename(path), parse_xer(fh.read())))
    return files


def main():
    files = load_revisions()
    assert files, f"no .xer fixtures found in {REV_DIR}"

    # Module 0 — inventory.
    inv = build_inventory(files, has_contract=True)
    assert inv.baseline is not None, "baseline should be auto-assigned"
    assert inv.current is not None, "current should be the latest data date"
    assert inv.baseline.data_date < inv.current.data_date
    print(f"Inventory: {len(inv.revisions)} revisions, "
          f"baseline={inv.baseline.label}, current={inv.current.label}")

    # Module 3 — milestone shifts.
    revs = [(r.label, r.data_date, data)
            for r, (_, data) in zip(inv.revisions, files)]
    shifts = track_milestone_shifts(revs)
    pc = next(s for s in shifts.series if s.key == "MS1000")
    assert pc.total_shift_days and pc.total_shift_days > 0, "PC should slip later"
    sect = next(s for s in shifts.series if s.key == "MS0500")
    assert sect.is_achieved, "sectional completion should be achieved in rev C"
    print(f"Milestones: PC slips {pc.total_shift_days:+.0f}d; "
          f"sectional achieved={sect.is_achieved}")

    # Module 4 — variance.
    baseline = inv.baseline
    base_data = dict(files)[baseline.file_name]
    cur_data = dict(files)[inv.current.file_name]
    ctypes = activity_code_types(base_data)
    assert ctypes, "fixtures should carry activity codes"
    var = compute_variance(base_data, cur_data, ctypes[0].type_id, ctypes[0].name)
    zone_b = next(g for g in var.groups if g.code_value == "Zone B")
    assert zone_b.finish_delta_days and zone_b.finish_delta_days > 0
    assert var.caveats, "variance must always emit standing caveats"
    print(f"Variance by {var.code_type_name}: "
          f"Zone B finish delta {zone_b.finish_delta_days:+.0f}d")

    print("\nAll programme-engine assertions passed.")


if __name__ == "__main__":
    main()
