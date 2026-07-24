"""UI regression harness — Playwright walk of the grouped navigation.

Catches wiring breaks (NameErrors, widget/state crashes, missing panels)
that engine tests cannot see. Run:

    pip install playwright && playwright install chromium
    python3 test_ui.py

Starts its own Streamlit server on :8599, loads the bundled samples, then
visits every page in the three sidebar groups (Forensic Programme
Analysis / Retrospective / Prospective) asserting zero Streamlit
exceptions, plus targeted checks on the DCMA traceback, the OOS repair
page, and the TIA stepper gating. Exit code 1 on any failure.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time

PORT = 8599
PASS, FAIL = [], []

# Every page title in sidebar order. Update this list only as part of an
# intentional navigation change.
TOOLS = [
    "Data Intake & Inventory", "DCMA 14-Point", "Baseline Critical Path",
    "Revision Comparison", "Out-of-Sequence Repair", "Float Erosion",
    "Progress S-Curve", "Resource Loading", "Sequence Coding",
    "Hierarchy Rebuild", "Report Assembler",
]
RETRO = [
    "As-Planned vs As-Recorded", "Milestone Shift Tracker",
    "Windows Analysis", "As-Built Critical Path", "Progress Transfer",
    "Impacted As-Planned", "Concurrency Screening",
    "Explain This Delay",
]
PROSPECTIVE = ["Time Impact Analysis"]
ALL_PAGES = TOOLS + RETRO + PROSPECTIVE


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}"
          + (f" — {detail}" if detail and not cond else ""))


def wait_port(port: int, timeout: float = 60) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), 1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed — run:\n"
              "  pip install playwright && playwright install chromium")
        return 0                       # skip, don't fail CI-less setups

    server = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py",
         "--server.port", str(PORT), "--server.headless", "true"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert wait_port(PORT), "server did not start"
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1500,
                                              "height": 950})
            page.goto(f"http://127.0.0.1:{PORT}", timeout=60_000)
            page.wait_for_timeout(6000)

            def exc() -> int:
                return page.locator(
                    '[data-testid="stException"]').count()

            def goto(title: str) -> None:
                # nav-link accessible name includes the Material-icon
                # token, so match on the title as a substring.
                page.get_by_role("link", name=title).first.click()
                page.wait_for_timeout(4500)

            # ---- default page is Data Intake (no landing, no radio) ---
            check("boots into Data Intake (default page)",
                  page.get_by_text("Data Intake & Inventory").count() > 0)
            check("status strip shows empty state",
                  page.get_by_text("No programmes loaded").count() > 0)
            # all three sidebar group headers present (expanded nav)
            navtext = page.locator(
                '[data-testid="stSidebarNav"]').inner_text()
            for grp in ("Forensic Programme Analysis", "Retrospective",
                        "Prospective"):
                check(f"sidebar group '{grp}' present", grp in navtext,
                      "not in nav; still collapsed?")
            check("no 'View more' collapse (all pages visible)",
                  "View" not in navtext or "more" not in navtext.lower())

            # load bundled samples on the intake page
            page.get_by_text("Use bundled sample").first.click()
            page.wait_for_timeout(12_000)
            check("sample load: no exceptions", exc() == 0, f"{exc()}")
            check("status strip populates after load",
                  page.get_by_text("baseline", exact=False).count() > 0)

            # ---- walk every page in all three groups ----------------
            for title in ALL_PAGES:
                goto(title)
                check(f"page '{title}' exception-free", exc() == 0,
                      f"{exc()} exceptions")

            # ---- targeted checks ------------------------------------
            goto("DCMA 14-Point")
            check("DCMA traceback section renders",
                  page.get_by_text("Forensic Traceback").count() > 0)

            goto("Out-of-Sequence Repair")
            check("OOS repair plan renders",
                  page.get_by_text("As-built repair plan").count() > 0)

            # TIA stepper gating (Prospective group)
            goto("Time Impact Analysis")
            page.wait_for_timeout(3000)
            check("TIA step 1 renders",
                  page.get_by_text("Register your AI once").count() > 0)
            check("health gateway shown",
                  page.get_by_text("Schedule-Health gateway").count() > 0)
            page.get_by_role("button",
                             name="Continue → ② Event").click()
            page.wait_for_timeout(4000)
            check("TIA step 2 reached",
                  page.get_by_text("Register the event").count() > 0)
            check("prospective walk exception-free", exc() == 0,
                  f"{exc()}")

            browser.close()
    finally:
        server.terminate()

    print(f"\nUI RESULT: {len(PASS)} passed, {len(FAIL)} FAILED")
    for f in FAIL:
        print("  FAILED:", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
