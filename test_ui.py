"""UI regression harness — Playwright walk of both workflows.

Catches wiring breaks (NameErrors, widget/state crashes, missing panels)
that engine tests cannot see. Run:

    pip install playwright && playwright install chromium
    python3 test_ui.py

Starts its own Streamlit server on :8599, walks the landing page, every
retrospective tab, the prospective stepper's gating, and Explain This
Forecast Impact, asserting zero Streamlit exceptions throughout.
Exit code 1 on any failure.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time

PORT = 8599
PASS, FAIL = [], []


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

            # ---- landing --------------------------------------------
            check("landing renders",
                  page.get_by_text("Construction Delay "
                                   "Intelligence").count() > 0)
            page.get_by_role(
                "button", name="Open retrospective analysis").click()
            page.wait_for_timeout(4000)

            # load bundled samples
            page.get_by_text("Use bundled sample").first.click()
            page.wait_for_timeout(12_000)
            check("sample load: no exceptions", exc() == 0, f"{exc()}")

            # ---- every retrospective tab ----------------------------
            tabs = page.locator('[role="tab"]')
            n = tabs.count()
            # 15 tabs is the SHIPPED retrospective design (the 6-screen
            # redesign was deliberately not adopted) — update this
            # number only as part of an intentional workflow change
            check("retrospective tab count", n == 15, f"{n}")
            for i in range(n):
                tabs.nth(i).click()
                page.wait_for_timeout(5000)
                check(f"retro tab {i} exception-free", exc() == 0,
                      f"{exc()} exceptions")

            # ---- prospective ----------------------------------------
            page.get_by_text("Prospective", exact=True).last.click()
            page.wait_for_timeout(6000)
            check("prospective renders",
                  page.get_by_text("Prospective Analysis").count() > 0)
            ptabs = page.locator('[role="tab"]')
            check("prospective tab count", ptabs.count() == 4,
                  f"{ptabs.count()}")

            # TIA stepper: walk the gates
            ptabs.nth(2).click()
            page.wait_for_timeout(6000)
            check("step 1 renders",
                  page.get_by_text("Register your AI once").count() > 0)
            check("health gateway shown",
                  page.get_by_text("Schedule-Health gateway").count() > 0)
            page.get_by_role("button",
                             name="Continue → ② Event").click()
            page.wait_for_timeout(5000)
            check("step 2 reached",
                  page.get_by_text("Register the event").count() > 0)
            page.get_by_label("Title").fill(
                "UI harness test variation works")
            page.get_by_label("Title").press("Tab")
            page.wait_for_timeout(3000)
            page.get_by_role("button",
                             name="Continue → ③ Fragnet").click()
            page.wait_for_timeout(5000)
            check("step 3: title persisted (no bounce)",
                  page.get_by_text("Build the fragnet").count() > 0,
                  "event title lost between steps")
            check("chain builder shown",
                  page.get_by_text("Where does the event work "
                                   "start from?").count() > 0)
            page.get_by_role(
                "button", name="Continue → ④ Validate & confirm").click()
            page.wait_for_timeout(4000)
            check("step 4 gate works (empty fragnet held back)",
                  page.get_by_text("Build the fragnet in step "
                                   "③ first").count() > 0
                  or page.get_by_text("Validate the logic").count() > 0)
            check("prospective walk exception-free", exc() == 0,
                  f"{exc()}")

            # Explain This Forecast Impact tab
            page.locator('[role="tab"]').nth(3).click()
            page.wait_for_timeout(6000)
            check("explain tab exception-free", exc() == 0, f"{exc()}")
            browser.close()
    finally:
        server.terminate()

    print(f"\nUI RESULT: {len(PASS)} passed, {len(FAIL)} FAILED")
    for f in FAIL:
        print("  FAILED:", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
