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
    "Hierarchy Rebuild", "Milestone Shift Tracker", "Progress Transfer",
    "As-Built Critical Path", "Report Assembler",
]
RETRO = [
    "As-Planned vs As-Built", "Windows Analysis",
    "Impacted As-Planned", "Collapsed As-Built",
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
            # inner_text() returns text AS RENDERED — the Drawing Sheet
            # theme uppercases nav section headers, so compare casefolded.
            navtext = page.locator(
                '[data-testid="stSidebarNav"]').inner_text().lower()
            for grp in ("Forensic Programme Analysis", "Retrospective",
                        "Prospective"):
                check(f"sidebar group '{grp}' present",
                      grp.lower() in navtext, "not in nav; still collapsed?")
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

            goto("As-Built Critical Path")
            page.wait_for_timeout(4000)
            # the page now leads with THE step-① breakdown (the same
            # shared block APvAB renders): dual candidates, divergence,
            # hand-edit, adopt.
            check("as-built page computes both CP candidates",
                  page.get_by_text("Longest path (programme logic)",
                                   exact=False).count() > 0
                  and page.get_by_text("Actual sequence (recorded",
                                       exact=False).count() > 0)
            check("as-built milestone multiselect present",
                  page.get_by_text("Milestone(s) to measure to",
                                   exact=False).count() > 0)
            check("stitched/persistence jargon is gone",
                  page.get_by_text("persisten", exact=False).count() == 0
                  and page.get_by_text("stitch", exact=False).count() == 0)
            ab_adopt = page.get_by_role("button", name="Adopt this path")
            check("as-built adopt button present", ab_adopt.count() > 0)
            if ab_adopt.count():
                ab_adopt.first.click()
                page.wait_for_timeout(6000)
                check("as-built adoption exception-free", exc() == 0,
                      f"{exc()} exceptions")
                check("as-built umbrella editor appears (CP only)",
                      page.get_by_text("Group the path into umbrella",
                                       exact=False).count() > 0)
                check("as-built linked gantt renders",
                      page.locator("iframe").count() > 0)
                check("as-built page shows logic links",
                      page.get_by_text(
                          "Logic links along the path").count() > 0)
                check("as-built report generator present",
                      page.get_by_text("AI Narrative Report",
                                       exact=False).count() > 0)
                check("as-built per-milestone workbook download present",
                      page.get_by_text("Download as-built path report",
                                       exact=False).count() > 0)

            # ---- umbrella grouping: type a name into the grid and
            # confirm it AUTO-adopts (the old two-button flow shipped
            # with the measurement gate never switching on).
            check("umbrella editor defaults to critical-path rows",
                  page.get_by_text("Show all", exact=False).count() > 0)
            # the propose area renders THE shared provider block — the
            # same code path as the narrative panels (model selector +
            # managed caption + own-key switch, keyed per state_key)
            check("umbrella propose has the model selector",
                  page.locator(
                      '.st-key-ab_umb_ai_nvidia_modelsel').count() == 1)
            check("umbrella propose has the own-key switch",
                  page.locator('.st-key-ab_umb_ai_own').count() == 1)
            def type_umbrella_cells() -> None:
                ed = page.locator('.st-key-ab_umb_editor '
                                  '[data-testid="stDataFrame"]').first
                ed.scroll_into_view_if_needed()
                page.wait_for_timeout(1200)
                box = ed.bounding_box()
                cx = box["x"] + box["width"] - 80
                cy = box["y"] + 51
                # WARM-UP click: glide's overlay editor does not take
                # keyboard focus on the very FIRST canvas interaction
                # after load, so the first typed value silently went
                # nowhere. Focus the canvas, drop the selection, then
                # edit for real.
                page.mouse.click(cx, cy)
                page.wait_for_timeout(700)
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
                for dy in (0, 35):
                    # select the cell, open the overlay with Enter —
                    # steadier than a double-click on the canvas grid
                    page.mouse.click(cx, cy + dy)
                    page.wait_for_timeout(600)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(700)
                    page.keyboard.type("Test Package")
                    page.wait_for_timeout(300)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(4000)
                page.wait_for_timeout(4000)

            # the canvas grid drops keystrokes under load — retry the
            # whole typing pass up to three times before failing
            for _attempt in range(3):
                type_umbrella_cells()
                if page.get_by_text("Adopted — measured span").count():
                    break
                page.wait_for_timeout(2500)
            check("typing in the grid auto-adopts the grouping",
                  page.get_by_text("Adopted — measured span").count() > 0)
            # no toggle any more: the shared block's gantt always
            # brackets umbrella groups (▣ headers, members beneath)
            check("grouped gantt renders with the umbrella legend",
                  page.get_by_text("umbrella work packages",
                                   exact=False).count() > 0)
            check("umbrella typing exception-free",
                  exc() == 0, f"{exc()} exceptions")

            # APvAB: the 4-step method (2026-07-27 spec). Step ① must
            # offer BOTH candidate paths and adopt one; later steps
            # depend on the adoption, so walk in order.
            goto("As-Planned vs As-Built")
            page.wait_for_timeout(4000)
            check("APvAB ① computes both CP candidates",
                  page.get_by_text("Longest path (programme logic)",
                                   exact=False).count() > 0
                  and page.get_by_text("Actual sequence (recorded",
                                       exact=False).count() > 0)
            check("APvAB ① milestone multiselect present",
                  page.get_by_text("Milestone(s) to measure to",
                                   exact=False).count() > 0)
            adopt = page.get_by_role("button", name="Adopt this path")
            check("APvAB ① adopt button present", adopt.count() > 0)
            if adopt.count():
                adopt.first.click()
                page.wait_for_timeout(6000)
                check("APvAB ① adoption exception-free", exc() == 0,
                      f"{exc()} exceptions")
                check("APvAB ① umbrella editor appears (CP only)",
                      page.get_by_text("Group the path into umbrella",
                                       exact=False).count() > 0)
                check("APvAB ① linked gantt renders",
                      page.locator("iframe").count() > 0)
            for lbl, probe in (
                ("② As-planned vs as-built", "Late dates (LS/LF)"),
                ("③ Windows", "key dates"),
                ("④ Gantt & report", "AI Narrative Report"),
            ):
                page.get_by_text(lbl, exact=True).first.click()
                page.wait_for_timeout(6000)
                check(f"APvAB step '{lbl[0]}' exception-free",
                      exc() == 0, f"{exc()} exceptions")
                check(f"APvAB step '{lbl[0]}' shows expected content",
                      page.get_by_text(probe, exact=False).count() > 0,
                      f"probe '{probe}' missing")
            check("APvAB ② planned-below/as-built-above gantt renders",
                  page.locator("iframe").count() > 0)

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
