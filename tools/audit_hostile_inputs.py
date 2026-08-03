"""Audit part 2: report-assembler parity + hostile-input fuzzing."""
import sys

sys.path.insert(0, ".")

from streamlit.testing.v1 import AppTest

from dcma import parse_xer
from programme import build_inventory, extract_asbuilt_longest_path
import state as sk

ROOT = "./sample/"
BASE_F = "Harbour Point DCP-03 - Baseline Programme Rev 0.xer"
BUILT_F = "Harbour Point DCP-03 - As-Built Programme Rev 12.xer"
MS = "H-5040"
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}"
          + (f" — {detail}" if detail and not cond else ""))


RAW = {n: open(ROOT + n, "rb").read() for n in (BASE_F, BUILT_F)}
POOL = [(n, parse_xer(RAW[n])) for n in (BASE_F, BUILT_F)]
INV = build_inventory(POOL)
built = POOL[1][1]
trace = extract_asbuilt_longest_path(built, end_task_code=MS)
ADOPTED = {MS: [(a.task_code, a.name) for a in trace.activities]}


def _report_page():
    import sys
    sys.path.insert(0, ".")
    from views.report import report_tab
    report_tab()


print("\n=== Report Assembler: APvAB section parity ===")
# without an adopted path the section must NOT appear (no invented method)
at = AppTest.from_function(_report_page, default_timeout=300)
at.session_state[sk.XER_POOL] = POOL
at.session_state[sk.INVENTORY] = INV
at.run()
check("report renders with no APvAB run", not at.exception,
      str(at.exception)[:200] if at.exception else "")
labels_before = " ".join(
    str(getattr(cb, "label", "")) for cb in at.checkbox)
check("no As-planned vs as-built section before adoption",
      "as-planned vs as-built" not in labels_before.lower(),
      labels_before[:200])

# with an adopted path it MUST appear
at2 = AppTest.from_function(_report_page, default_timeout=300)
at2.session_state[sk.XER_POOL] = POOL
at2.session_state[sk.INVENTORY] = INV
at2.session_state["apab2_paths"] = ADOPTED
at2.session_state["apab2_basis"] = {
    MS: "as-built longest path (recorded logic)"}
at2.session_state["apab2_date_basis"] = "late"
at2.run()
check("report renders with an adopted APvAB path", not at2.exception,
      str(at2.exception)[:300] if at2.exception else "")
labels_after = " ".join(
    str(getattr(cb, "label", "")) for cb in at2.checkbox)
check("As-planned vs as-built section offered after adoption",
      "as-planned vs as-built" in labels_after.lower(),
      labels_after[:300])

# the assembled WORD FILE must carry the same +92 d finding the
# method page reports (findings live in the docx, not the page)
btn = [b for b in at2.button if b.key == "rep_build"]
check("assemble-report button present", bool(btn))
if btn:
    btn[0].click()
    at2.run()
    check("assembly exception-free", not at2.exception,
          str(at2.exception)[:300] if at2.exception else "")
    docx = (at2.session_state["rep_docx"]
            if "rep_docx" in at2.session_state else None)
    check("assembled Word report produced",
          bool(docx) and len(docx) > 10_000,
          f"{len(docx) if docx else 0} bytes")
    if docx:
        import zipfile as _z
        import io as _io
        with _z.ZipFile(_io.BytesIO(docx)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        check("report contains the As-Planned vs As-Built section",
              "As-Planned vs As-Built" in xml)
        check("report carries the +92 d finding",
              "+92 days" in xml or "+92" in xml,
              [s for s in xml.split("<") if "92" in s][:3])

print("\n=== Hostile / malformed inputs (parser must not crash) ===")
CASES = {
    "empty bytes": b"",
    "garbage": b"\x00\x01\x02notanxer\xff\xfe",
    "header only": b"ERMHDR\t19.12\t2024-01-01\n",
    "truncated mid-table": RAW[BUILT_F][:len(RAW[BUILT_F]) // 3],
    "no TASK rows": b"ERMHDR\t19.12\n%T\tPROJECT\n%F\tproj_id\n%R\t1\n",
    "huge single line": b"ERMHDR\t19.12\n" + b"A" * 500_000,
    "null bytes inside": RAW[BUILT_F][:2000] + b"\x00" * 100
    + RAW[BUILT_F][2000:6000],
    "utf16 mislabelled": RAW[BUILT_F][:4000].decode(
        "utf-8", "ignore").encode("utf-16"),
}
for name, blob in CASES.items():
    try:
        d = parse_xer(blob)
        check(f"parser survives {name}", True)
        # anything that parses must also survive the inventory builder
        try:
            build_inventory([("f.xer", d)])
            check(f"inventory survives {name}", True)
        except Exception as exc:
            check(f"inventory survives {name}", False,
                  f"{type(exc).__name__}: {exc}")
    except Exception as exc:
        # a clean, typed refusal is acceptable; a crash is not
        ok = isinstance(exc, (ValueError, UnicodeDecodeError))
        check(f"parser survives {name}", ok,
              f"{type(exc).__name__}: {exc}")

print("\n=== Injection / escaping gates ===")
from programme import build_simple_xlsx
import zipfile
import io
rows = [{"Activity": "=cmd|'/c calc'!A1", "Note": "@SUM(1+1)",
         "X": "+1+1", "Y": "-1-1"}]
wb = build_simple_xlsx("inj", sheets={"S": rows}, notes=["n"])
with zipfile.ZipFile(io.BytesIO(wb)) as z:
    sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8", "ignore")
# the evidence text must survive VERBATIM (an activity name is
# evidence and may not be altered) while carrying no formula typing —
# so Excel renders it as literal text and nothing executes
import re as _re
check("no cell is written as an Excel formula",
      len(_re.findall(r"<f[ >]", sheet)) == 0)
check("hostile text is preserved verbatim as a string cell",
      "=cmd|&#39;/c calc&#39;!A1" in sheet or "=cmd" in sheet)
check("hostile cells are typed inlineStr, not formula",
      sheet.count('t="inlineStr"') >= 4)

from path_studio import PathDraft, dataset_from_xer, \
    build_path_studio_html, validate_draft
import dataclasses as _dc
ds = dataset_from_xer(built, path_codes=[MS], basis="b",
                      milestone_code=MS, baseline=POOL[0][1])
ds = _dc.replace(ds, title="</script><img src=x onerror=alert(1)>")
d = PathDraft(ds.analysis_id, (MS,), "b")
html = build_path_studio_html(ds, d, validate_draft(ds, d))
check("path gantt escapes script breakout in XER text",
      "</script><img" not in html and "\\u003c/script>" in html)

print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} FAILED")
if FAIL:
    print("FAILURES:")
    for f in FAIL:
        print("  -", f)
sys.exit(1 if FAIL else 0)
