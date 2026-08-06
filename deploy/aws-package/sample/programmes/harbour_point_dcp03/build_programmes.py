"""Generator for the Harbour Point DCP-03 demonstration programmes.

Emits two Primavera-compatible .xer files from one activity definition:

  * Baseline Programme Rev 0   — not started, data date = contract start
  * As-Built Programme Rev 12  — every activity complete, data date =
                                 the recorded completion date

Both files come from the SAME network run through the SAME CPM here, so
the pair is internally consistent: the baseline's critical path really
carries zero total float, and the as-built dates really are the product
of the recorded durations and the delay events described in README.md.

Run:  python3 build_programmes.py
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_NAME = "Harbour Point District Cooling Plant DCP-03"
BASE_FILE = "Harbour Point DCP-03 - Baseline Programme Rev 0.xer"
AB_FILE = "Harbour Point DCP-03 - As-Built Programme Rev 12.xer"

CONTRACT_START = date(2024, 1, 8)          # Notice to Proceed (Monday)
P6_EPOCH = date(1899, 12, 30)

# --------------------------------------------------------------------------- #
# Calendars
# --------------------------------------------------------------------------- #
# Mon=0 … Sun=6. Gulf working week: Mon-Fri office, Mon-Sat site.
HOLIDAYS_2024_25 = [
    date(2024, 4, 8), date(2024, 4, 9), date(2024, 4, 10),    # Eid al-Fitr
    date(2024, 6, 16), date(2024, 6, 17), date(2024, 6, 18),  # Eid al-Adha
    date(2024, 12, 2), date(2024, 12, 3),                     # National Day
    date(2025, 1, 1),
    date(2025, 3, 30), date(2025, 3, 31), date(2025, 4, 1),   # Eid al-Fitr
    date(2025, 6, 6), date(2025, 6, 7),                       # Eid al-Adha
]

CALENDARS = {
    "OFF": {"id": "1001", "name": "5-Day Office / Design Week",
            "days": {0, 1, 2, 3, 4}, "hpd": 8.0,
            "holidays": HOLIDAYS_2024_25},
    "CON": {"id": "1002", "name": "6-Day Site Construction Week",
            "days": {0, 1, 2, 3, 4, 5}, "hpd": 8.0,
            "holidays": HOLIDAYS_2024_25},
    "SUP": {"id": "1003", "name": "7-Day Manufacture & Shipping",
            "days": {0, 1, 2, 3, 4, 5, 6}, "hpd": 8.0,
            "holidays": []},
}


def is_working(cal: dict, d: date) -> bool:
    return d.weekday() in cal["days"] and d not in cal["holidays"]


def next_wd(cal: dict, d: date) -> date:
    while not is_working(cal, d):
        d += timedelta(days=1)
    return d


def prev_wd(cal: dict, d: date) -> date:
    while not is_working(cal, d):
        d -= timedelta(days=1)
    return d


def advance(cal: dict, d: date, n: int) -> date:
    """n working days forward from a working day d (n=0 -> d)."""
    d = next_wd(cal, d)
    for _ in range(int(n)):
        d = next_wd(cal, d + timedelta(days=1))
    return d


def retreat(cal: dict, d: date, n: int) -> date:
    d = prev_wd(cal, d)
    for _ in range(int(n)):
        d = prev_wd(cal, d - timedelta(days=1))
    return d


def wd_between(cal: dict, a: date, b: date) -> int:
    """Working days strictly after a, up to and including b (0 if b<=a)."""
    if b <= a:
        return 0
    n, cur = 0, a
    while cur < b:
        cur += timedelta(days=1)
        if is_working(cal, cur):
            n += 1
    return n


# --------------------------------------------------------------------------- #
# Activity definition
# --------------------------------------------------------------------------- #
# (code, name, wbs, cal, dur, preds, phase, disc, area, resp, resources)
#   preds: list of (pred_code, type, lag_days)
#   ab:    as-built behaviour —
#            dd  duration delta (working days, + = longer, - = recovered)
#            sd  start delay: waiting before the activity could start
#            ov  overlap: started this many working days before its
#                predecessor finished (out-of-sequence working)
#            od  original duration revised in the as-built file (scope)
#            new activity exists only in the as-built programme
#            gone activity exists only in the baseline (descoped)
#            ev  delay-event reference recorded as a UDF
M = "TT_Mile"          # start milestone
F = "TT_FinMile"       # finish milestone
T = "TT_Task"
L = "TT_LOE"

ACTS: list[dict] = [
    # ---------------- 1000 Engineering & Design ----------------------
    dict(code="E-1000", name="Notice to Proceed", wbs="1100", cal="OFF",
         dur=0, type=M, preds=[], phase="ENG", disc="MULTI",
         area="SITE", resp="EMP"),
    dict(code="E-1010", name="Mobilise Design Team & Design Kick-off",
         wbs="1100", cal="OFF", dur=10, preds=[("E-1000", "FS", 0)],
         phase="ENG", disc="MULTI", area="OFF", resp="CON",
         res=[("DES", 320)]),
    dict(code="E-1020", name="Concept Design & Basis of Design",
         wbs="1100", cal="OFF", dur=20, preds=[("E-1010", "FS", 0)],
         phase="ENG", disc="MULTI", area="OFF", resp="CON",
         res=[("DES", 640)]),
    dict(code="E-1030", name="Employer Review & Comment - Concept Design",
         wbs="1100", cal="OFF", dur=10, preds=[("E-1020", "FS", 0)],
         phase="ENG", disc="MULTI", area="OFF", resp="EMP",
         res=[("DES", 80)],
         ab=dict(dd=8, ev="DE-01")),
    dict(code="E-1040", name="Detailed Design - Chiller Plant Mechanical",
         wbs="1200", cal="OFF", dur=30, preds=[("E-1030", "FS", 0)],
         phase="ENG", disc="MECH", area="PLANT", resp="CON",
         res=[("DES", 960)],
         ab=dict(dd=2, od=32, ev="DE-02")),
    dict(code="E-1050", name="Detailed Design - Electrical, LV & Controls",
         wbs="1200", cal="OFF", dur=25, preds=[("E-1030", "FS", 0)],
         phase="ENG", disc="ELEC", area="SUB", resp="CON",
         res=[("DES", 800)],
         ab=dict(dd=4, ev="DE-02")),
    dict(code="E-1060", name="Consultant Review & Approval - Detailed Design",
         wbs="1200", cal="OFF", dur=15,
         preds=[("E-1040", "FS", 0), ("E-1050", "FS", 0)],
         phase="ENG", disc="MULTI", area="OFF", resp="EMP",
         res=[("DES", 120)]),
    dict(code="E-1070", name="Issue IFC Drawings - Mechanical Package",
         wbs="1200", cal="OFF", dur=12, preds=[("E-1060", "FS", 0)],
         phase="ENG", disc="MECH", area="OFF", resp="CON",
         res=[("DES", 240)]),
    dict(code="E-1075", name="Issue IFC Drawings - Electrical Package",
         wbs="1200", cal="OFF", dur=10, preds=[("E-1060", "FS", 0)],
         phase="ENG", disc="ELEC", area="OFF", resp="CON",
         res=[("DES", 200)],
         ab=dict(dd=3, ev="DE-03")),
    dict(code="E-1090", name="Builder's Work & Openings Information Issued",
         wbs="1200", cal="OFF", dur=8, preds=[("E-1060", "FS", 0)],
         phase="ENG", disc="CIVIL", area="PLANT", resp="EMP",
         res=[("DES", 120)],
         ab=dict(dd=12, ev="DE-03")),
    dict(code="E-1080", name="Design Freeze - IFC Drawings Issued",
         wbs="1200", cal="OFF", dur=0, type=F,
         preds=[("E-1070", "FS", 0), ("E-1075", "FS", 0)],
         phase="ENG", disc="MULTI", area="OFF", resp="SHARE",
         key=True),

    # ---------------- 2000 Procurement -------------------------------
    dict(code="P-2000", name="Chiller Package - Tender & Technical Evaluation",
         wbs="2100", cal="OFF", dur=20, preds=[("E-1080", "FS", 0)],
         phase="PRO", disc="MECH", area="OFF", resp="CON",
         res=[("PM", 160)]),
    dict(code="P-2010", name="Chiller Package - Award & Purchase Order",
         wbs="2100", cal="OFF", dur=10, preds=[("P-2000", "FS", 0)],
         phase="PRO", disc="MECH", area="OFF", resp="EMP",
         res=[("PM", 80)]),
    dict(code="P-2020", name="Chiller - Vendor Drawings & Approval",
         wbs="2100", cal="OFF", dur=25, preds=[("P-2010", "FS", 0)],
         phase="PRO", disc="MECH", area="OFF", resp="VEN",
         res=[("DES", 200)]),
    dict(code="P-2030", name="Chiller - Manufacture & Assembly",
         wbs="2100", cal="SUP", dur=90, preds=[("P-2020", "FS", 0)],
         phase="PRO", disc="MECH", area="OFF", resp="VEN",
         ab=dict(dd=14, ev="DE-04")),
    dict(code="P-2040", name="Chiller - Factory Acceptance Testing",
         wbs="2100", cal="OFF", dur=10, preds=[("P-2030", "FS", 0)],
         phase="PRO", disc="MECH", area="OFF", resp="VEN",
         res=[("COM", 80)]),
    dict(code="P-2050", name="Chiller - Shipping & Delivery to Site",
         wbs="2100", cal="SUP", dur=35, preds=[("P-2040", "FS", 0)],
         phase="PRO", disc="MECH", area="SITE", resp="VEN",
         ab=dict(dd=5, ev="DE-05")),
    dict(code="P-2060", name="Chillers Delivered to Site",
         wbs="2100", cal="CON", dur=0, type=F,
         preds=[("P-2050", "FS", 0)],
         phase="PRO", disc="MECH", area="SITE", resp="VEN", key=True),
    dict(code="P-2100", name="LV Switchgear - Procure & Deliver",
         wbs="2200", cal="SUP", dur=70, preds=[("E-1075", "FS", 0)],
         phase="PRO", disc="ELEC", area="SUB", resp="CON",
         ab=dict(dd=10, ev="DE-06")),
    dict(code="P-2110", name="Chilled Water Pumps - Procure & Deliver",
         wbs="2200", cal="SUP", dur=60, preds=[("E-1070", "FS", 0)],
         phase="PRO", disc="MECH", area="PLANT", resp="CON"),
    dict(code="P-2120", name="Pipework, Valves & Fittings - Procure & Deliver",
         wbs="2200", cal="SUP", dur=45, preds=[("E-1070", "FS", 0)],
         phase="PRO", disc="MECH", area="PLANT", resp="CON"),
    dict(code="P-2130", name="BMS & Controls Package - Procure & Deliver",
         wbs="2200", cal="SUP", dur=55, preds=[("E-1075", "FS", 0)],
         phase="PRO", disc="CTRL", area="PLANT", resp="CON"),
    dict(code="P-2140", name="Cooling Towers - Procure & Deliver",
         wbs="2200", cal="SUP", dur=65, preds=[("E-1070", "FS", 0)],
         phase="PRO", disc="MECH", area="YARD", resp="CON"),
    dict(code="P-2150", name="Standby Chiller Package - Procure & Deliver",
         wbs="2200", cal="SUP", dur=40, preds=[("E-1070", "FS", 0)],
         phase="PRO", disc="MECH", area="PLANT", resp="CON",
         ab=dict(gone=True, ev="DE-07")),

    # ---------------- 3000 Construction ------------------------------
    dict(code="C-3000", name="Site Establishment & Temporary Works",
         wbs="3100", cal="CON", dur=15, preds=[("E-1000", "FS", 0)],
         phase="CON", disc="CIVIL", area="SITE", resp="CON",
         res=[("LAB", 480)]),
    dict(code="C-3010", name="Plant Room Civil Works & Equipment Plinths",
         wbs="3100", cal="CON", dur=25,
         preds=[("C-3000", "FS", 0), ("E-1090", "FS", 0)],
         phase="CON", disc="CIVIL", area="PLANT", resp="CON",
         res=[("LAB", 1000)],
         ab=dict(dd=8, ev="DE-08")),
    dict(code="C-3020", name="Chiller Offloading, Rigging & Setting to Position",
         wbs="3200", cal="CON", dur=10,
         preds=[("P-2060", "FS", 0), ("C-3010", "FS", 0)],
         phase="CON", disc="MECH", area="PLANT", resp="CON",
         res=[("MEC", 320)]),
    dict(code="C-3030", name="Primary Chilled Water Pipework Installation",
         wbs="3200", cal="CON", dur=35,
         preds=[("C-3020", "FS", 0), ("P-2120", "FS", 0)],
         phase="CON", disc="MECH", area="PLANT", resp="CON",
         res=[("MEC", 1400)],
         ab=dict(dd=9, ev="DE-09")),
    dict(code="C-3035", name="Additional Pipework - Revised Chiller Layout (VO-07)",
         wbs="3200", cal="CON", dur=8, preds=[("C-3030", "FS", 0)],
         phase="CON", disc="MECH", area="PLANT", resp="EMP",
         res=[("MEC", 320)],
         ab=dict(new=True, ev="DE-10")),
    dict(code="C-3040", name="Chiller Mechanical Connections & Valve Sets",
         wbs="3200", cal="CON", dur=20, preds=[("C-3030", "FS", 0)],
         phase="CON", disc="MECH", area="PLANT", resp="CON",
         res=[("MEC", 800)],
         ab=dict(preds=[("C-3035", "FS", 0)])),
    dict(code="C-3050", name="Pipework Insulation & Identification",
         wbs="3200", cal="CON", dur=15, preds=[("C-3040", "FS", 0)],
         phase="CON", disc="MECH", area="PLANT", resp="CON",
         res=[("MEC", 480)],
         ab=dict(ov=3)),
    dict(code="C-3060", name="Pipework Flushing & Chemical Cleaning",
         wbs="3200", cal="CON", dur=12, preds=[("C-3050", "FS", 0)],
         phase="CON", disc="MECH", area="PLANT", resp="CON",
         res=[("MEC", 240)]),
    dict(code="C-3100", name="Electrical Containment & Cable Tray Installation",
         wbs="3300", cal="CON", dur=30, preds=[("C-3010", "FS", 0)],
         phase="CON", disc="ELEC", area="PLANT", resp="CON",
         res=[("ELE", 900)],
         ab=dict(dd=-4, ev="DE-11")),
    dict(code="C-3110", name="LV Switchgear Installation & Alignment",
         wbs="3300", cal="CON", dur=20,
         preds=[("C-3100", "FS", 0), ("P-2100", "FS", 0)],
         phase="CON", disc="ELEC", area="SUB", resp="CON",
         res=[("ELE", 640)],
         ab=dict(dd=6, ev="DE-06")),
    dict(code="C-3120", name="Power Cabling, Glanding & Termination",
         wbs="3300", cal="CON", dur=25, preds=[("C-3110", "FS", 0)],
         phase="CON", disc="ELEC", area="PLANT", resp="CON",
         res=[("ELE", 800)],
         ab=dict(dd=5, ev="DE-06")),
    dict(code="C-3130", name="BMS Field Devices & Control Wiring",
         wbs="3300", cal="CON", dur=25,
         preds=[("C-3120", "FS", 0), ("P-2130", "FS", 0)],
         phase="CON", disc="CTRL", area="PLANT", resp="CON",
         res=[("ELE", 600)],
         ab=dict(dd=4, ev="DE-06")),
    dict(code="C-3200", name="Cooling Tower Installation & Alignment",
         wbs="3200", cal="CON", dur=20,
         preds=[("P-2140", "FS", 0), ("C-3010", "FS", 0)],
         phase="CON", disc="MECH", area="YARD", resp="CON",
         res=[("MEC", 640)]),
    dict(code="C-3210", name="Chilled Water Pump Installation",
         wbs="3200", cal="CON", dur=15,
         preds=[("P-2110", "FS", 0), ("C-3010", "FS", 0)],
         phase="CON", disc="MECH", area="PLANT", resp="CON",
         res=[("MEC", 480)]),
    dict(code="C-3220", name="Fire Protection & Detection Installation",
         wbs="3300", cal="CON", dur=18, preds=[("C-3010", "FS", 0)],
         phase="CON", disc="ELEC", area="PLANT", resp="CON",
         res=[("ELE", 540)]),
    dict(code="C-3230", name="HVAC Ductwork & Plant Room Ventilation",
         wbs="3200", cal="CON", dur=20, preds=[("C-3010", "FS", 0)],
         phase="CON", disc="MECH", area="PLANT", resp="CON",
         res=[("MEC", 600)]),
    dict(code="C-3240", name="Plant Room Painting & Finishes",
         wbs="3100", cal="CON", dur=8, preds=[("C-3050", "FS", 0)],
         phase="CON", disc="CIVIL", area="PLANT", resp="CON",
         res=[("LAB", 360)]),
    dict(code="C-3250", name="Access Platforms, Ladders & Handrails",
         wbs="3100", cal="CON", dur=10, preds=[("C-3010", "FS", 0)],
         phase="CON", disc="CIVIL", area="PLANT", resp="CON",
         res=[("LAB", 300)]),
    dict(code="C-3070", name="Mechanical Completion",
         wbs="3200", cal="CON", dur=0, type=F,
         preds=[("C-3060", "FS", 0), ("C-3130", "FS", 0),
                ("C-3230", "FS", 0), ("C-3240", "FS", 0),
                ("C-3250", "FS", 0)],
         phase="CON", disc="MULTI", area="PLANT", resp="CON", key=True),

    # ---------------- 4000 Testing, Commissioning & Snagging ---------
    dict(code="T-4000", name="Static & Pressure Testing",
         wbs="4000", cal="CON", dur=12, preds=[("C-3070", "FS", 0)],
         phase="TST", disc="MECH", area="PLANT", resp="CON",
         res=[("COM", 240)]),
    dict(code="T-4010", name="Energisation & Pre-Commissioning Checks",
         wbs="4000", cal="CON", dur=10, preds=[("T-4000", "FS", 0)],
         phase="TST", disc="ELEC", area="PLANT", resp="CON",
         res=[("COM", 200)],
         ab=dict(ov=3)),
    dict(code="T-4020", name="Chiller Commissioning - Vendor Attendance",
         wbs="4000", cal="CON", dur=20, preds=[("T-4010", "FS", 0)],
         phase="TST", disc="MECH", area="PLANT", resp="VEN",
         res=[("COM", 400)],
         ab=dict(dd=7, ev="DE-12")),
    dict(code="T-4030", name="Integrated System & Performance Testing",
         wbs="4000", cal="CON", dur=15, preds=[("T-4020", "FS", 0)],
         phase="TST", disc="CTRL", area="PLANT", resp="CON",
         res=[("COM", 300)]),
    dict(code="T-4040", name="Snagging Inspection - Client & Consultant",
         wbs="4000", cal="CON", dur=10, preds=[("T-4030", "FS", 0)],
         phase="SNG", disc="MULTI", area="PLANT", resp="EMP",
         res=[("PM", 120)]),
    dict(code="T-4050", name="Snag Rectification Works",
         wbs="4000", cal="CON", dur=20, preds=[("T-4040", "FS", 0)],
         phase="SNG", disc="MULTI", area="PLANT", resp="CON",
         res=[("MEC", 400), ("ELE", 200)],
         ab=dict(dd=9, ev="DE-13")),
    dict(code="T-4055", name="Second Snag Rectification Pass",
         wbs="4000", cal="CON", dur=6, preds=[("T-4050", "FS", 0)],
         phase="SNG", disc="MULTI", area="PLANT", resp="CON",
         res=[("MEC", 120)],
         ab=dict(new=True, ev="DE-13")),
    dict(code="T-4060", name="Re-inspection & Snag Close-out",
         wbs="4000", cal="CON", dur=8, preds=[("T-4050", "FS", 0)],
         phase="SNG", disc="MULTI", area="PLANT", resp="EMP",
         res=[("PM", 96)],
         ab=dict(preds=[("T-4055", "FS", 0)])),
    dict(code="T-4100", name="Secondary Systems Testing - Towers & Pumps",
         wbs="4000", cal="CON", dur=10,
         preds=[("C-3200", "FS", 0), ("C-3210", "FS", 0)],
         phase="TST", disc="MECH", area="YARD", resp="CON",
         res=[("COM", 160)]),
    dict(code="T-4110", name="Fire System Testing & Certification",
         wbs="4000", cal="CON", dur=8, preds=[("C-3220", "FS", 0)],
         phase="TST", disc="ELEC", area="PLANT", resp="CON",
         res=[("COM", 128)]),
    dict(code="T-4070", name="Systems Accepted - Commissioning Complete",
         wbs="4000", cal="CON", dur=0, type=F,
         preds=[("T-4060", "FS", 0), ("T-4100", "FS", 0),
                ("T-4110", "FS", 0)],
         phase="SNG", disc="MULTI", area="PLANT", resp="SHARE", key=True),

    # ---------------- 5000 Handover & Close-out ----------------------
    dict(code="H-5000", name="O&M Manuals & As-Built Drawings Submission",
         wbs="5000", cal="OFF", dur=20, preds=[("T-4030", "FS", 0)],
         phase="HND", disc="MULTI", area="OFF", resp="CON",
         res=[("DES", 320)]),
    dict(code="H-5010", name="Operator Training",
         wbs="5000", cal="OFF", dur=10, preds=[("T-4070", "FS", 0)],
         phase="HND", disc="MULTI", area="PLANT", resp="CON",
         res=[("COM", 80)]),
    dict(code="H-5020", name="Authority Inspection & Approval",
         wbs="5000", cal="OFF", dur=12,
         preds=[("T-4070", "FS", 0), ("H-5000", "FS", 0)],
         phase="HND", disc="MULTI", area="SITE", resp="AUTH",
         res=[("PM", 96)],
         ab=dict(dd=10, ev="DE-14")),
    dict(code="H-5030", name="Taking-Over Certificate Documentation",
         wbs="5000", cal="OFF", dur=10, preds=[("H-5020", "FS", 0)],
         phase="HND", disc="MULTI", area="OFF", resp="EMP",
         res=[("PM", 80)],
         ab=dict(dd=5, ev="DE-15")),
    dict(code="H-5045", name="Spares & Special Tools Handover",
         wbs="5000", cal="OFF", dur=8, preds=[("T-4070", "FS", 0)],
         phase="HND", disc="MECH", area="PLANT", resp="CON",
         res=[("PM", 64)]),
    dict(code="H-5040", name="Substantial Completion & Taking Over",
         wbs="5000", cal="OFF", dur=0, type=F,
         preds=[("H-5030", "FS", 0), ("H-5010", "FS", 0),
                ("H-5045", "FS", 0)],
         phase="HND", disc="MULTI", area="SITE", resp="SHARE",
         key=True, contract=True),

    # ---------------- 9000 Project management (level of effort) ------
    dict(code="Z-9000", name="Project Management & Site Supervision",
         wbs="9000", cal="OFF", dur=340, type=L,
         preds=[("E-1000", "SS", 0)],
         phase="PM", disc="MULTI", area="SITE", resp="CON"),
    dict(code="Z-9010", name="Site Facilities, Welfare & Security",
         wbs="9000", cal="CON", dur=330, type=L,
         preds=[("C-3000", "SS", 0)],
         phase="PM", disc="MULTI", area="SITE", resp="CON"),
]

WBS = [
    ("1000", "ENG", "Engineering & Design", None),
    ("1100", "CONCEPT", "Concept & Approvals", "1000"),
    ("1200", "DETAIL", "Detailed Design & IFC", "1000"),
    ("2000", "PROC", "Procurement", None),
    ("2100", "CHILLER", "Chiller Package (Long Lead)", "2000"),
    ("2200", "SECOND", "Secondary Packages", "2000"),
    ("3000", "CONST", "Construction & Installation", None),
    ("3100", "CIVIL", "Civil & Structural", "3000"),
    ("3200", "MECH", "Mechanical Installation", "3000"),
    ("3300", "ELEC", "Electrical & Controls Installation", "3000"),
    ("4000", "TCS", "Testing, Commissioning & Snagging", None),
    ("5000", "HAND", "Handover & Close-out", None),
    ("9000", "PM", "Project Management", None),
]

CODE_TYPES = {
    "PHASE": ("Project Phase", {
        "ENG": "Engineering & Design", "PRO": "Procurement",
        "CON": "Construction", "TST": "Testing & Commissioning",
        "SNG": "Snagging & Rectification", "HND": "Handover",
        "PM": "Project Management"}),
    "DISC": ("Discipline", {
        "MECH": "Mechanical", "ELEC": "Electrical", "CIVIL": "Civil",
        "CTRL": "Controls & BMS", "MULTI": "Multi-discipline"}),
    "AREA": ("Area / Location", {
        "PLANT": "Plant Room", "YARD": "Cooling Tower Yard",
        "SUB": "LV Substation", "SITE": "Site-wide", "OFF": "Off-site"}),
    "RESP": ("Responsibility (asserted)", {
        "EMP": "Employer", "CON": "Contractor", "VEN": "Vendor",
        "AUTH": "Authority", "SHARE": "Shared / Joint"}),
}

RESOURCES = {
    "DES": ("Design Engineer", "hour"), "PM": ("Project Management", "hour"),
    "MEC": ("Mechanical Fitter", "hour"), "ELE": ("Electrician", "hour"),
    "COM": ("Commissioning Engineer", "hour"), "LAB": ("General Labour", "hour"),
}

# Delay events referenced by the UDF, for the README narrative.
EVENTS = {
    "DE-01": "Employer's concept design review over-ran (14d)",
    "DE-02": "Design development of revised chiller capacity (4-6d)",
    "DE-03": "Late issue of electrical/builder's work information (8-20d)",
    "DE-04": "Vendor compressor supply shortage in manufacture (12d)",
    "DE-05": "Port congestion on delivery voyage (5d)",
    "DE-06": "Switchgear late delivery and consequent electrical works (10-25d)",
    "DE-07": "Standby chiller package descoped by VO-03",
    "DE-08": "Structural openings released late to civil works (8d)",
    "DE-09": "Pipework installation productivity shortfall (9d)",
    "DE-10": "Additional pipework instructed under VO-07",
    "DE-11": "Contractor resequenced containment - 4d recovered",
    "DE-12": "Vendor commissioning engineer mobilisation delay (7d)",
    "DE-13": "Snag volume required a second rectification pass (12d + 6d)",
    "DE-14": "Authority inspection failed at first attempt (14d)",
    "DE-15": "Taking-over documentation compilation (7d)",
}


# --------------------------------------------------------------------------- #
# CPM
# --------------------------------------------------------------------------- #
def topo(acts: list[dict]) -> list[dict]:
    by = {a["code"]: a for a in acts}
    seen, order = set(), []

    def visit(a):
        if a["code"] in seen:
            return
        seen.add(a["code"])
        for p, _, _ in a.get("preds", []):
            if p in by:
                visit(by[p])
        order.append(a)

    for a in acts:
        visit(a)
    return order


def _succ_start(succ_cal: dict, pred_finish: date, lag: float) -> date:
    """The FS-implied early start of a successor: its next working day."""
    return advance(succ_cal, next_wd(succ_cal, pred_finish + timedelta(days=1)),
                   lag)


def forward(acts: list[dict], start: date, key="dur") -> None:
    """Early start/finish per activity, plus the driving predecessor.

    A finish milestone lands ON its driving predecessor's finish date —
    the convention a completion milestone is read with in a report — so
    a milestone's slippage is exactly its driver's slippage.
    """
    by = {a["code"]: a for a in acts}
    for a in topo(acts):
        cal = CALENDARS[a["cal"]]
        fin_mile = a["type"] == F and a[key] == 0
        es, driver = next_wd(cal, start), None
        for p, ltype, lag in a.get("preds", []):
            pa = by.get(p)
            if pa is None:
                continue
            if ltype == "SS":
                cand = advance(cal, pa["ES"], lag)
            elif fin_mile:                          # same day as its driver
                cand = advance(cal, next_wd(cal, pa["EF"]), lag)
            else:
                cand = _succ_start(cal, pa["EF"], lag)
            if cand > es:
                es, driver = cand, p
        dur = a[key]
        a["ES"] = es
        a["EF"] = es if dur == 0 else advance(cal, es, dur - 1)
        a["driver"] = driver


def backward(acts: list[dict]) -> None:
    """Late dates + total float against the project's own completion.

    The step back across a relationship is taken on the SUCCESSOR's
    calendar — the mirror of the forward pass, which found the
    successor's start on that same calendar. Taking it on the
    predecessor's calendar is what puts a spurious day of float on every
    activity whose successor runs a different working week.
    """
    by = {a["code"]: a for a in acts}
    succs: dict[str, list[tuple[str, str, float]]] = {a["code"]: [] for a in acts}
    for a in acts:
        for p, ltype, lag in a.get("preds", []):
            if p in by:
                succs[p].append((a["code"], ltype, lag))
    finish = max(a["EF"] for a in acts if a["type"] != L)
    for a in reversed(topo(acts)):
        cal = CALENDARS[a["cal"]]
        lf = finish
        for s, ltype, lag in succs[a["code"]]:
            sa = by[s]
            scal = CALENDARS[sa["cal"]]
            if ltype == "SS":
                cand = advance(cal, retreat(scal, sa["LS"], lag),
                               max(a["dur"] - 1, 0))
            elif sa["type"] == F and sa["dur"] == 0:
                cand = retreat(scal, sa["LF"], lag)      # milestone: same day
            else:
                cand = retreat(scal, prev_wd(scal,
                                             sa["LS"] - timedelta(days=1)),
                               lag)
            if cand < lf:
                lf = cand
        a["LF"] = lf
        a["LS"] = lf if a["dur"] == 0 else retreat(cal, lf, a["dur"] - 1)
        a["TF"] = wd_between(cal, a["EF"], a["LF"])


def as_built(acts: list[dict], start: date) -> None:
    """Recorded dates: planned duration + delta, waiting time, overlaps."""
    by = {a["code"]: a for a in acts}
    for a in topo(acts):
        cal = CALENDARS[a["cal"]]
        ab = a.get("ab") or {}
        preds = ab.get("preds") or a.get("preds", [])
        fin_mile = a["type"] == F and a["dur"] == 0
        st, driver = next_wd(cal, start), None
        for p, ltype, lag in preds:
            pa = by.get(p)
            if pa is None:
                continue
            if ltype == "SS":
                cand = advance(cal, pa["AS"], lag)
            elif fin_mile:
                cand = advance(cal, next_wd(cal, pa["AF"]), lag)
            else:
                cand = _succ_start(cal, pa["AF"], lag)
            if cand > st:
                st, driver = cand, p
        if ab.get("sd"):
            st = advance(cal, st, ab["sd"])
        if ab.get("ov") and driver is not None:      # out-of-sequence start
            st = retreat(cal, st, ab["ov"])
        dur = max(a["dur"] + ab.get("dd", 0), 0)
        a["AS"] = st
        a["AF"] = st if a["type"] in (M, F) else advance(cal, st, dur - 1)
        a["ab_dur"] = dur
        a["ab_driver"] = driver


# --------------------------------------------------------------------------- #
# XER writing
# --------------------------------------------------------------------------- #
FIELDS = {
    "CURRTYPE": ["curr_id", "decimal_digit_cnt", "curr_symbol",
                 "decimal_symbol", "digit_group_symbol", "pos_curr_fmt_type",
                 "neg_curr_fmt_type", "curr_type", "curr_short_name",
                 "group_digit_cnt", "base_exch_rate"],
    "OBS": ["obs_id", "parent_obs_id", "guid", "seq_num", "obs_name",
            "obs_descr"],
    "UDFTYPE": ["udf_type_id", "table_name", "udf_type_name",
                "udf_type_label", "logical_data_type", "super_flag",
                "indicator_expression", "summary_indicator_expression",
                "export_flag"],
    "PROJECT": ["proj_id", "fy_start_month_num", "rsrc_self_add_flag",
                "allow_complete_flag", "rsrc_multi_assign_flag",
                "checkout_flag", "project_flag", "step_complete_flag",
                "cost_qty_recalc_flag", "batch_sum_flag", "name_sep_char",
                "def_complete_pct_type", "proj_short_name", "acct_id",
                "orig_proj_id", "source_proj_id", "base_type_id", "clndr_id",
                "sum_base_proj_id", "task_code_base", "task_code_step",
                "priority_num", "wbs_max_sum_level", "strgy_priority_num",
                "last_checksum", "critical_drtn_hr_cnt", "def_cost_per_qty",
                "last_recalc_date", "plan_start_date", "plan_end_date",
                "scd_end_date", "add_date", "last_tasksum_date",
                "fcst_start_date", "def_duration_type", "task_code_prefix",
                "guid", "def_qty_type", "add_by_name", "web_local_root_path",
                "proj_url", "def_rate_type", "add_act_remain_flag",
                "act_this_per_link_flag", "def_task_type", "act_pct_link_flag",
                "critical_path_type", "task_code_prefix_flag",
                "def_rollup_dates_flag", "use_project_baseline_flag",
                "rem_target_link_flag", "reset_planned_flag",
                "allow_neg_act_flag", "sum_assign_level", "last_fin_dates_id",
                "fintmpl_id", "last_baseline_update_date", "cr_external_key",
                "apply_actuals_date", "location_id", "last_schedule_date",
                "loaded_scope_level", "export_flag", "new_fin_dates_id",
                "baselines_to_export", "baseline_names_to_export",
                "next_data_date", "close_period_flag", "sum_refresh_date",
                "trsrcsum_loaded", "sumtask_loaded"],
    "CALENDAR": ["clndr_id", "default_flag", "clndr_name", "proj_id",
                 "base_clndr_id", "last_chng_date", "clndr_type",
                 "day_hr_cnt", "week_hr_cnt", "month_hr_cnt", "year_hr_cnt",
                 "rsrc_private", "clndr_data"],
    "SCHEDOPTIONS": ["schedoptions_id", "proj_id", "sched_outer_depend_type",
                     "sched_open_critical_flag", "sched_lag_early_start_flag",
                     "sched_retained_logic", "sched_setplantoforecast",
                     "sched_float_type", "sched_calendar_on_relationship_lag",
                     "sched_use_expect_end_flag", "sched_progress_override",
                     "level_float_thrs_cnt", "level_outer_assign_flag",
                     "level_outer_assign_priority", "level_over_alloc_pct",
                     "level_within_float_flag", "level_keep_sched_date_flag",
                     "level_all_rsrc_flag",
                     "sched_use_project_end_date_for_float",
                     "enable_multiple_longest_path_calc",
                     "limit_multiple_longest_path_calc",
                     "max_multiple_longest_path",
                     "use_total_float_multiple_longest_paths",
                     "key_activity_for_multiple_longest_paths",
                     "LevelPriorityList"],
    "PROJWBS": ["wbs_id", "proj_id", "obs_id", "seq_num", "est_wt",
                "proj_node_flag", "sum_data_flag", "status_code",
                "wbs_short_name", "wbs_name", "phase_id", "parent_wbs_id",
                "ev_user_pct", "ev_etc_user_value", "orig_cost",
                "indep_remain_total_cost", "ann_dscnt_rate_pct",
                "dscnt_period_type", "indep_remain_work_qty",
                "anticip_start_date", "anticip_end_date", "ev_compute_type",
                "ev_etc_compute_type", "guid", "tmpl_guid", "plan_open_state"],
    "RSRC": ["rsrc_id", "parent_rsrc_id", "clndr_id", "role_id", "shift_id",
             "user_id", "pobs_id", "guid", "rsrc_seq_num", "email_addr",
             "employee_code", "office_phone", "other_phone", "rsrc_name",
             "rsrc_short_name", "rsrc_title_name", "def_qty_per_hr",
             "cost_qty_type", "ot_factor", "active_flag",
             "auto_compute_act_flag", "def_cost_qty_link_flag", "ot_flag",
             "curr_id", "unit_id", "rsrc_type", "location_id", "rsrc_notes",
             "load_tasks_flag", "level_flag", "last_checksum"],
    "ACTVTYPE": ["actv_code_type_id", "actv_short_len", "seq_num",
                 "actv_code_type", "proj_id", "wbs_id",
                 "actv_code_type_scope", "export_flag"],
    "ACTVCODE": ["actv_code_id", "parent_actv_code_id", "actv_code_type_id",
                 "actv_code_name", "short_name", "seq_num", "color",
                 "total_assignments"],
    "TASK": ["task_id", "proj_id", "wbs_id", "clndr_id", "phys_complete_pct",
             "rev_fdbk_flag", "est_wt", "lock_plan_flag",
             "auto_compute_act_flag", "complete_pct_type", "task_type",
             "duration_type", "status_code", "task_code", "task_name",
             "rsrc_id", "total_float_hr_cnt", "free_float_hr_cnt",
             "remain_drtn_hr_cnt", "act_work_qty", "remain_work_qty",
             "target_work_qty", "target_drtn_hr_cnt", "target_equip_qty",
             "act_equip_qty", "remain_equip_qty", "cstr_date",
             "act_start_date", "act_end_date", "late_start_date",
             "late_end_date", "expect_end_date", "early_start_date",
             "early_end_date", "restart_date", "reend_date",
             "target_start_date", "target_end_date", "rem_late_start_date",
             "rem_late_end_date", "cstr_type", "priority_type",
             "suspend_date", "resume_date", "float_path", "float_path_order",
             "guid", "tmpl_guid", "cstr_date2", "cstr_type2",
             "driving_path_flag", "act_this_per_work_qty",
             "act_this_per_equip_qty", "external_early_start_date",
             "external_late_end_date", "create_date", "update_date",
             "create_user", "update_user", "location_id", "crt_path_num"],
    "TASKPRED": ["task_pred_id", "task_id", "pred_task_id", "proj_id",
                 "pred_proj_id", "pred_type", "lag_hr_cnt", "comments",
                 "float_path", "aref", "arls"],
    "TASKRSRC": ["taskrsrc_id", "task_id", "proj_id", "cost_qty_link_flag",
                 "role_id", "acct_id", "rsrc_id", "pobs_id", "skill_level",
                 "remain_qty", "target_qty", "remain_qty_per_hr",
                 "target_lag_drtn_hr_cnt", "target_qty_per_hr", "act_ot_qty",
                 "act_reg_qty", "relag_drtn_hr_cnt", "ot_factor",
                 "cost_per_qty", "target_cost", "act_reg_cost", "act_ot_cost",
                 "remain_cost", "act_start_date", "act_end_date",
                 "restart_date", "reend_date", "target_start_date",
                 "target_end_date", "rem_late_start_date",
                 "rem_late_end_date", "rollup_dates_flag", "target_crv",
                 "remain_crv", "actual_crv", "ts_pend_act_end_flag", "guid",
                 "rate_type", "act_this_per_cost", "act_this_per_qty",
                 "curv_id", "rsrc_type", "cost_per_qty_source_type",
                 "create_user", "create_date", "has_rsrchours",
                 "taskrsrc_sum_id"],
    "TASKACTV": ["task_id", "actv_code_type_id", "actv_code_id", "proj_id"],
    "UDFVALUE": ["udf_type_id", "fk_id", "proj_id", "udf_date", "udf_number",
                 "udf_text", "udf_code_id"],
}

UDF_TYPES = {
    "5001": ("Delay Event Reference", "FT_TEXT"),
    "5002": ("Contract Milestone", "FT_TEXT"),
    "5003": ("Responsible Party (asserted)", "FT_TEXT"),
}


def ordinal(d: date) -> int:
    return (d - P6_EPOCH).days


def clndr_blob(cal: dict) -> str:
    """P6 CalendarData: weekly shift pattern + dated holiday exceptions."""
    days = []
    for p6day in range(1, 8):                    # 1=Sunday … 7=Saturday
        weekday = (p6day + 5) % 7                # -> Mon=0 … Sun=6
        if weekday in cal["days"]:
            days.append(
                f"      (0||{p6day}()("
                "        (0||0(s|08:00|f|12:00)())"
                "        (0||1(s|13:00|f|17:00)())))")
        else:
            days.append(f"      (0||{p6day}()())")
    exc = "".join(f"      (0||{i}(d|{ordinal(h)})())"
                  for i, h in enumerate(cal["holidays"]))
    return ("(0||CalendarData()(    (0||DaysOfWeek()("
            + "".join(days) + ")))    (0||Exceptions()("
            + exc + "))))")


def fmt(d: date | None, hour: str = "00:00") -> str:
    return f"{d:%Y-%m-%d} {hour}" if d else ""


def emit(tables: list[tuple[str, list[dict]]], path: str,
         export_date: date) -> None:
    lines = [f"ERMHDR\t24.12\t{export_date:%Y-%m-%d}\tProject\tADMIN"
             f"\toaltun\tdbxDatabaseNoName\tProject Management\tUSD"]
    for name, rows in tables:
        if not rows:
            continue
        fields = FIELDS[name]
        lines.append(f"%T\t{name}")
        lines.append("%F\t" + "\t".join(fields))
        for r in rows:
            lines.append("%R\t" + "\t".join(str(r.get(f, "") or "")
                                           for f in fields))
    lines.append("%E")
    with open(path, "w", encoding="cp1252", errors="replace") as fh:
        fh.write("\n".join(lines) + "\n")


def build(acts: list[dict], *, proj_id: str, short_name: str, as_built_mode: bool,
          data_date: date, plan_end: date, path: str) -> None:
    wbs_id = {code: str(3000 + i) for i, (code, *_rest) in enumerate(WBS)}
    root_id = "2999"
    task_id = {a["code"]: str(6000 + i) for i, a in enumerate(acts)}
    ctype_id = {k: str(4000 + i) for i, k in enumerate(CODE_TYPES)}
    cval_id: dict[tuple[str, str], str] = {}
    n = 4100
    for k, (_label, values) in CODE_TYPES.items():
        for v in values:
            cval_id[(k, v)] = str(n)
            n += 1
    rsrc_id = {k: str(4500 + i) for i, k in enumerate(RESOURCES)}

    currtype = [dict(curr_id="1", decimal_digit_cnt="2", curr_symbol="$",
                     decimal_symbol="ds_Period",
                     digit_group_symbol="dg_Comma",
                     pos_curr_fmt_type="#1.1", neg_curr_fmt_type="(#1.1)",
                     curr_type="US Dollar", curr_short_name="USD",
                     group_digit_cnt="3", base_exch_rate="1")]
    obs = [dict(obs_id="1", seq_num="1", obs_name="Enterprise",
                obs_descr="")]
    udftype = [dict(udf_type_id=tid, table_name="TASK", udf_type_name=nm,
                    udf_type_label=nm, logical_data_type=dt,
                    super_flag="N", export_flag="Y")
               for tid, (nm, dt) in UDF_TYPES.items()]

    project = [dict(
        proj_id=proj_id, fy_start_month_num="1", rsrc_self_add_flag="N",
        allow_complete_flag="N", rsrc_multi_assign_flag="Y",
        checkout_flag="N", project_flag="Y", step_complete_flag="N",
        cost_qty_recalc_flag="N", batch_sum_flag="N", name_sep_char=".",
        def_complete_pct_type="CP_Drtn", proj_short_name=short_name,
        clndr_id=CALENDARS["OFF"]["id"], task_code_base="1000",
        task_code_step="10", priority_num="10", wbs_max_sum_level="0",
        strgy_priority_num="500", critical_drtn_hr_cnt="0",
        def_cost_per_qty="0",
        last_recalc_date=fmt(data_date, "08:00"),
        plan_start_date=fmt(CONTRACT_START, "08:00"),
        plan_end_date="",
        scd_end_date=fmt(plan_end, "17:00"),
        add_date=fmt(CONTRACT_START, "08:00"),
        def_duration_type="DT_FixedDrtn", task_code_prefix="",
        def_qty_type="QT_Hour", add_by_name="oaltun",
        def_rate_type="COST_PER_QTY", add_act_remain_flag="N",
        act_this_per_link_flag="Y", def_task_type="TT_Task",
        act_pct_link_flag="N", critical_path_type="CT_TotFloat",
        task_code_prefix_flag="N", def_rollup_dates_flag="Y",
        use_project_baseline_flag="N", rem_target_link_flag="Y",
        reset_planned_flag="N", allow_neg_act_flag="N",
        sum_assign_level="SL_Taskrsrc",
        last_schedule_date=fmt(data_date, "08:00"),
        export_flag="Y", close_period_flag="N", trsrcsum_loaded="N",
        sumtask_loaded="N")]

    calendar = [dict(
        clndr_id=c["id"], default_flag="Y" if k == "OFF" else "N",
        clndr_name=c["name"], proj_id="", base_clndr_id="",
        last_chng_date=fmt(CONTRACT_START, "08:00"),
        clndr_type="CA_Base", day_hr_cnt=f"{c['hpd']:g}",
        week_hr_cnt=f"{c['hpd'] * len(c['days']):g}",
        month_hr_cnt=f"{c['hpd'] * len(c['days']) * 4.33:g}",
        year_hr_cnt=f"{c['hpd'] * len(c['days']) * 52:g}",
        rsrc_private="N", clndr_data=clndr_blob(c))
        for k, c in CALENDARS.items()]

    schedoptions = [dict(
        schedoptions_id="1", proj_id=proj_id,
        sched_outer_depend_type="SD_Both", sched_open_critical_flag="N",
        sched_lag_early_start_flag="N", sched_retained_logic="Y",
        sched_setplantoforecast="N", sched_float_type="ST_TotalFloat",
        sched_calendar_on_relationship_lag="rcal_Predecessor",
        sched_use_expect_end_flag="Y", sched_progress_override="N",
        level_float_thrs_cnt="1", level_outer_assign_flag="Y",
        level_outer_assign_priority="5", level_over_alloc_pct="25",
        level_within_float_flag="N", level_keep_sched_date_flag="Y",
        level_all_rsrc_flag="Y", sched_use_project_end_date_for_float="N",
        enable_multiple_longest_path_calc="N",
        limit_multiple_longest_path_calc="N", max_multiple_longest_path="10",
        use_total_float_multiple_longest_paths="N")]

    projwbs = [dict(
        wbs_id=root_id, proj_id=proj_id, obs_id="1", seq_num="1",
        est_wt="1", proj_node_flag="Y", sum_data_flag="Y",
        status_code="WS_Open", wbs_short_name=short_name,
        wbs_name=PROJECT_NAME, parent_wbs_id="",
        ev_user_pct="0.06", ev_etc_user_value="0.88",
        ev_compute_type="EC_Cmp_pct", ev_etc_compute_type="EE_Rem_hr",
        plan_open_state="Open")]
    for i, (code, short, name, parent) in enumerate(WBS):
        projwbs.append(dict(
            wbs_id=wbs_id[code], proj_id=proj_id, obs_id="1",
            seq_num=str((i + 1) * 10), est_wt="1", proj_node_flag="N",
            sum_data_flag="Y", status_code="WS_Open",
            wbs_short_name=short, wbs_name=name,
            parent_wbs_id=wbs_id[parent] if parent else root_id,
            ev_user_pct="0.06", ev_etc_user_value="0.88",
            ev_compute_type="EC_Cmp_pct", ev_etc_compute_type="EE_Rem_hr",
            plan_open_state="Open"))

    rsrc = [dict(
        rsrc_id=rsrc_id[k], clndr_id=CALENDARS["CON"]["id"],
        rsrc_seq_num=str(i + 1), rsrc_name=nm, rsrc_short_name=k,
        rsrc_title_name=nm, def_qty_per_hr="1", cost_qty_type="QT_Hour",
        ot_factor="1", active_flag="Y", auto_compute_act_flag="N",
        def_cost_qty_link_flag="Y", ot_flag="N", curr_id="1",
        rsrc_type="RT_Labor", load_tasks_flag="N", level_flag="Y")
        for i, (k, (nm, _u)) in enumerate(RESOURCES.items())]

    actvtype, actvcode = [], []
    for i, (k, (label, values)) in enumerate(CODE_TYPES.items()):
        actvtype.append(dict(
            actv_code_type_id=ctype_id[k], actv_short_len="8",
            seq_num=str((i + 1) * 10), actv_code_type=label,
            proj_id="", wbs_id="", actv_code_type_scope="AS_Global",
            export_flag="Y"))
        for j, (val, vname) in enumerate(values.items()):
            actvcode.append(dict(
                actv_code_id=cval_id[(k, val)], parent_actv_code_id="",
                actv_code_type_id=ctype_id[k], actv_code_name=vname,
                short_name=val, seq_num=str((j + 1) * 10),
                color="0x0080c0", total_assignments="0"))

    task, taskpred, taskrsrc, taskactv, udfvalue = [], [], [], [], []
    pred_seq, rsrc_seq = 7000, 7500
    for a in acts:
        cal = CALENDARS[a["cal"]]
        hpd = cal["hpd"]
        ab = a.get("ab") or {}
        od_days = ab.get("od", a["dur"]) if as_built_mode else a["dur"]
        # a finish milestone is an instant at the END of its day: starting
        # it at 08:00 would read as 0.4 days of out-of-sequence overlap
        # against the predecessor that finishes 17:00 the same day
        sh = "17:00" if (a["type"] == F and a["dur"] == 0) else "08:00"
        row = dict(
            task_id=task_id[a["code"]], proj_id=proj_id,
            wbs_id=wbs_id[a["wbs"]], clndr_id=cal["id"],
            rev_fdbk_flag="N", est_wt="1", lock_plan_flag="N",
            auto_compute_act_flag="N", complete_pct_type="CP_Drtn",
            task_type=a["type"], duration_type="DT_FixedDrtn",
            task_code=a["code"], task_name=a["name"],
            target_drtn_hr_cnt=f"{od_days * hpd:g}",
            target_work_qty="0", act_work_qty="0", remain_work_qty="0",
            priority_type="PT_Normal", guid="", float_path="",
            create_user="oaltun", update_user="oaltun",
            create_date=fmt(CONTRACT_START, "08:00"))
        if as_built_mode:
            row.update(
                phys_complete_pct="100", status_code="TK_Complete",
                remain_drtn_hr_cnt="0", total_float_hr_cnt="0",
                free_float_hr_cnt="0",
                act_start_date=fmt(a["AS"], sh),
                act_end_date=fmt(a["AF"], "17:00"),
                early_start_date=fmt(a["AS"], sh),
                early_end_date=fmt(a["AF"], "17:00"),
                late_start_date=fmt(a["AS"], sh),
                late_end_date=fmt(a["AF"], "17:00"),
                target_start_date=fmt(a["AS"], sh),
                target_end_date=fmt(a["AF"], "17:00"),
                driving_path_flag="N")
        else:
            row.update(
                phys_complete_pct="0", status_code="TK_NotStart",
                remain_drtn_hr_cnt=f"{a['dur'] * hpd:g}",
                total_float_hr_cnt=f"{a['TF'] * hpd:g}",
                free_float_hr_cnt=f"{a['TF'] * hpd:g}",
                early_start_date=fmt(a["ES"], sh),
                early_end_date=fmt(a["EF"], "17:00"),
                late_start_date=fmt(a["LS"], sh),
                late_end_date=fmt(a["LF"], "17:00"),
                target_start_date=fmt(a["ES"], sh),
                target_end_date=fmt(a["EF"], "17:00"),
                rem_late_start_date=fmt(a["LS"], sh),
                rem_late_end_date=fmt(a["LF"], "17:00"),
                driving_path_flag="Y" if a["TF"] == 0 else "N")
        task.append(row)

        preds = (ab.get("preds") if as_built_mode and ab.get("preds")
                 else a.get("preds", []))
        for p, ltype, lag in preds:
            if p not in task_id:
                continue
            taskpred.append(dict(
                task_pred_id=str(pred_seq), task_id=task_id[a["code"]],
                pred_task_id=task_id[p], proj_id=proj_id,
                pred_proj_id=proj_id, pred_type=f"PR_{ltype}",
                lag_hr_cnt=f"{lag * hpd:g}", comments="", float_path="",
                aref="", arls=""))
            pred_seq += 1

        for rk, qty in a.get("res", []):
            done = as_built_mode
            taskrsrc.append(dict(
                taskrsrc_id=str(rsrc_seq), task_id=task_id[a["code"]],
                proj_id=proj_id, cost_qty_link_flag="Y",
                rsrc_id=rsrc_id[rk], skill_level="1",
                remain_qty="0" if done else f"{qty:g}",
                target_qty=f"{qty:g}",
                act_reg_qty=f"{qty:g}" if done else "0",
                remain_qty_per_hr="0", target_qty_per_hr="1",
                act_ot_qty="0", ot_factor="1", cost_per_qty="0",
                target_cost="0", act_reg_cost="0", act_ot_cost="0",
                remain_cost="0",
                act_start_date=fmt(a["AS"], sh) if done else "",
                act_end_date=fmt(a["AF"], "17:00") if done else "",
                target_start_date=fmt(a["AS"] if done else a["ES"], "08:00"),
                target_end_date=fmt(a["AF"] if done else a["EF"], "17:00"),
                rollup_dates_flag="Y", ts_pend_act_end_flag="N",
                rate_type="COST_PER_QTY", rsrc_type="RT_Labor",
                cost_per_qty_source_type="ST_Resource",
                create_user="oaltun",
                create_date=fmt(CONTRACT_START, "08:00"),
                has_rsrchours="N"))
            rsrc_seq += 1

        for ck, val in (("PHASE", a["phase"]), ("DISC", a["disc"]),
                        ("AREA", a["area"]), ("RESP", a["resp"])):
            if (ck, val) in cval_id:
                taskactv.append(dict(
                    task_id=task_id[a["code"]],
                    actv_code_type_id=ctype_id[ck],
                    actv_code_id=cval_id[(ck, val)], proj_id=proj_id))

        ev = (a.get("ab") or {}).get("ev")
        if as_built_mode and ev:
            udfvalue.append(dict(
                udf_type_id="5001", fk_id=task_id[a["code"]],
                proj_id=proj_id, udf_text=f"{ev} - {EVENTS.get(ev, '')}"))
        if a.get("contract"):
            udfvalue.append(dict(
                udf_type_id="5002", fk_id=task_id[a["code"]],
                proj_id=proj_id,
                udf_text="Contract Completion Date - Clause 8.2"))
        elif a.get("key"):
            udfvalue.append(dict(
                udf_type_id="5002", fk_id=task_id[a["code"]],
                proj_id=proj_id, udf_text="Key Date - phase completion"))
        udfvalue.append(dict(
            udf_type_id="5003", fk_id=task_id[a["code"]], proj_id=proj_id,
            udf_text=CODE_TYPES["RESP"][1].get(a["resp"], a["resp"])))

    emit([("CURRTYPE", currtype), ("OBS", obs), ("UDFTYPE", udftype),
          ("PROJECT", project), ("CALENDAR", calendar),
          ("SCHEDOPTIONS", schedoptions), ("PROJWBS", projwbs),
          ("RSRC", rsrc), ("ACTVTYPE", actvtype), ("ACTVCODE", actvcode),
          ("TASK", task), ("TASKPRED", taskpred), ("TASKRSRC", taskrsrc),
          ("TASKACTV", taskactv), ("UDFVALUE", udfvalue)],
         os.path.join(OUT_DIR, path), data_date)


def main() -> None:
    for a in ACTS:
        a.setdefault("type", T)
        a.setdefault("res", [])

    # ---- baseline: everything as planned ----
    base = [dict(a) for a in ACTS if not (a.get("ab") or {}).get("new")]
    forward(base, CONTRACT_START)
    backward(base)
    plan_end = max(a["EF"] for a in base if a["type"] != L)

    # ---- as-built: recorded durations, waiting time, overlaps ----
    ab = [dict(a) for a in ACTS if not (a.get("ab") or {}).get("gone")]
    as_built(ab, CONTRACT_START)
    ab_end = max(a["AF"] for a in ab if a["type"] != L)

    build(base, proj_id="1801", short_name="HP-DCP03-BL",
          as_built_mode=False, data_date=CONTRACT_START,
          plan_end=plan_end, path=BASE_FILE)
    build(ab, proj_id="1802", short_name="HP-DCP03-AB",
          as_built_mode=True, data_date=ab_end,
          plan_end=ab_end, path=AB_FILE)

    # ---- report the story the files tell ----
    bl = {a["code"]: a for a in base}
    print(f"Baseline   : {CONTRACT_START:%d %b %Y} -> {plan_end:%d %b %Y}")
    print(f"As-built   : {CONTRACT_START:%d %b %Y} -> {ab_end:%d %b %Y}")
    print(f"Overall slip: {(ab_end - plan_end).days} calendar days\n")
    print(f"{'Key date':<10} {'planned':>12} {'as-built':>12} "
          f"{'slip':>6} {'accrued':>8}")
    prev = 0
    for a in ab:
        if not a.get("key"):
            continue
        b = bl.get(a["code"])
        if b is None:
            continue
        slip = (a["AF"] - b["EF"]).days
        print(f"{a['code']:<10} {b['EF']:%d %b %Y} {a['AF']:%d %b %Y} "
              f"{slip:>6} {slip - prev:>8}")
        prev = slip
    cp = [a["code"] for a in base if a["TF"] == 0 and a["type"] != L]
    print(f"\nBaseline critical path (TF=0): {len(cp)} activities")
    print(f"Activities: baseline {len(base)}, as-built {len(ab)}")


if __name__ == "__main__":
    main()
