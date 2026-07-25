"""Self-contained collapsible gantt viewer (HTML/JS component).

Renders the hierarchy overlay from ``programme.hierarchy`` as an
interactive tree-gantt in a print-like, think-cell-inspired style: white
canvas, a two-band year/month timeline header, navy group summary brackets,
status-coloured activity bars, a data-date marker, search (auto-expands
matching branches), zoom, and a frozen tree column with synced scrolling.
No external assets — everything is inlined so it works inside Streamlit's
component iframe (and offline).
"""

from __future__ import annotations

import json

_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  :root {
    --canvas: #FCFCFA; --panel: #F1F5F9; --ink: #14324A; --muted: #5B7994;
    --line: #C6D4E0; --strong: #8FA9BE; --navy: #14324A;
    --done: #2f9e44; --done-b: #23763375;
    --active: #f2a33c; --active-b: #b9770e75;
    --future: #4c8ede; --future-b: #2f5f9e75;
    --dd: #d64545;
  }
  * { box-sizing: border-box;
      font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; }
  body { margin: 0; background: var(--canvas); color: var(--ink); }
  #toolbar { display: flex; gap: 10px; align-items: center; padding: 8px 12px;
             background: var(--panel); border-bottom: 1px solid var(--line);
             flex-wrap: wrap; position: sticky; top: 0; z-index: 40; }
  #toolbar input[type=text] { background: var(--panel); color: var(--ink);
             border: 1px solid var(--strong); border-radius: 4px;
             padding: 5px 9px; width: 220px; font-size: 12px; }
  #toolbar button { background: var(--panel); color: var(--navy);
             border: 1px solid var(--strong); border-radius: 4px;
             padding: 5px 12px; cursor: pointer; font-size: 12px;
             font-weight: 600; }
  #toolbar button:hover { background: var(--panel); border-color: var(--navy); }
  .lg { display: inline-flex; align-items: center; gap: 5px;
        font-size: 11px; color: var(--muted); }
  .sw { width: 11px; height: 11px; border-radius: 2px; display: inline-block;
        border: 1px solid #00000022; }
  #wrap { overflow: auto; height: calc(100vh - 48px); position: relative; }
  #head { position: sticky; top: 0; z-index: 30; width: max-content;
          min-width: 100%; background: var(--canvas); }
  #years, #months { display: flex; margin-left: var(--treew);
          width: max-content; }
  #years { border-bottom: 1px solid var(--strong); }
  #months { border-bottom: 2px solid var(--navy); }
  .ycell { border-left: 2px solid var(--strong); color: var(--navy);
           font-size: 12px; font-weight: 700; padding: 4px 0 3px 6px;
           overflow: hidden; white-space: nowrap; flex: none;
           background: var(--panel); }
  .mcell { border-left: 1px solid var(--line); color: var(--muted);
           font-size: 10px; padding: 3px 0 3px 4px; overflow: hidden;
           white-space: nowrap; flex: none; }
  .hcorner { position: absolute; left: 0; top: 0; width: var(--treew);
             height: 100%; background: var(--panel); z-index: 31;
             border-right: 2px solid var(--navy);
             border-bottom: 2px solid var(--navy);
             display: flex; align-items: flex-end; padding: 0 0 4px 10px;
             font-size: 11px; font-weight: 700; color: var(--navy); }
  .row { display: flex; width: max-content; min-width: 100%; height: 26px; }
  .row:nth-child(even) .lane { background-color: #F5F8FB; }
  .row:hover .lane, .row:hover .label { background-color: #E8F0F7; }
  .label { position: sticky; left: 0; z-index: 10; width: var(--treew);
           flex: none; background: var(--canvas); display: flex;
           align-items: center; font-size: 12px; white-space: nowrap;
           overflow: hidden; text-overflow: ellipsis;
           border-right: 2px solid var(--navy);
           border-bottom: 1px solid var(--line); cursor: default; }
  .label.grp { cursor: pointer; font-weight: 700; color: var(--navy);
               background: var(--panel); }
  .caret { display: inline-block; width: 15px; text-align: center;
           color: var(--navy); flex: none; font-size: 10px; }
  .cnt { color: var(--muted); font-weight: 400; margin-left: 6px;
         font-size: 10px; }
  .aid { width: 108px; flex: none; color: var(--muted);
         overflow: hidden; text-overflow: ellipsis;
         font-size: 11px; }
  .anm { flex: 1 1 auto; overflow: hidden;
         text-overflow: ellipsis; min-width: 0; }
  .adt { width: 78px; flex: none; color: var(--muted);
         font-size: 10.5px; font-variant-numeric: tabular-nums; }
  #corner { flex-direction: column; align-items: stretch;
            justify-content: flex-end; }
  .colhdr { display: flex; width: 100%; font-size: 10px;
            color: var(--muted); font-weight: 400; }
  .lane { position: relative; flex: none;
          border-bottom: 1px solid var(--line);
          background-image: var(--grid); background-size: var(--gridsize);
          background-repeat: repeat; }
  .bar { position: absolute; top: 7px; height: 12px; border-radius: 2px;
         border: 1px solid transparent; }
  .bar.sum { top: 10px; height: 6px; background: var(--navy);
             border-radius: 1px; border: none; }
  .bar.sum::before, .bar.sum::after { content: ""; position: absolute;
             top: 0; width: 2px; height: 13px; background: var(--navy); }
  .bar.sum::before { left: 0; } .bar.sum::after { right: 0; }
  .ms { position: absolute; top: 7px; width: 11px; height: 11px;
        transform: rotate(45deg); border-radius: 1px;
        border: 1px solid #00000033; }
  .ddline { position: absolute; top: 0; width: 0; height: 100%;
            border-left: 2px dashed var(--dd); z-index: 5;
            pointer-events: none; }
  .ddtag { position: sticky; top: 54px; z-index: 25; }
</style></head><body>
<div id="toolbar">
  <input id="q" type="text" placeholder="Search groups / activities…">
  <button id="exp">Expand all</button>
  <button id="col">Collapse all</button>
  <span class="lg">Zoom <input id="zoom" type="range" min="10" max="120"
        value="__ZOOM__" style="width:120px"></span>
  <span class="lg"><span class="sw" style="background:var(--navy)"></span>
    group summary</span>
  <span id="legend" style="display:inline-flex;gap:10px"></span>
  <span class="lg" style="color:var(--dd)" id="ddlg"></span>
  <span class="lg" id="meta"></span>
</div>
<div id="wrap">
  <div id="head"><div class="hcorner" id="corner"></div>
    <div id="years"></div><div id="months"></div></div>
  <div id="rows" style="position:relative"></div>
</div>
<script>
const TREE = __TREE__;
const DATA_DATE = __DATA_DATE__;
const TITLE = __TITLE__;
const TREEW = 600;
document.documentElement.style.setProperty("--treew", TREEW + "px");
document.getElementById("corner").innerHTML = esc(TITLE) +
  '<div class="colhdr"><span class="caret"></span>' +
  '<span class="aid">Activity ID</span>' +
  '<span class="anm">Activity name</span>' +
  '<span class="adt">Start</span>' +
  '<span class="adt">Finish</span></div>';
const DAY = 86400000;
const CATS = __CATS__;
const FILL = {}, EDGE = {};
const legendEl = document.getElementById("legend");
for (const c of CATS) {
  FILL[c.key] = c.color;
  EDGE[c.key] = c.color + "80";
  const chip = document.createElement("span");
  chip.className = "lg";
  chip.innerHTML = `<span class="sw" style="background:${c.color}"></span>` +
                   `${c.label}`;
  legendEl.appendChild(chip);
}

// -- date range over the whole tree ---------------------------------------
let dmin = null, dmax = null;
(function scan(n){
  for (const k of ["start","finish"]) if (n[k]) {
    const t = Date.parse(n[k]);
    if (dmin === null || t < dmin) dmin = t;
    if (dmax === null || t > dmax) dmax = t;
  }
  (n.children||[]).forEach(scan);
  (n.activities||[]).forEach(a => { for (const k of ["start","finish"])
    if (a[k]) { const t = Date.parse(a[k]);
      if (dmin === null || t < dmin) dmin = t;
      if (dmax === null || t > dmax) dmax = t; } });
})(TREE);
if (dmin === null) { dmin = Date.now(); dmax = dmin + 30*DAY; }
dmin -= 10*DAY; dmax += 10*DAY;
if (DATA_DATE) {
  document.getElementById("ddlg").textContent =
    "┊ data date " + DATA_DATE;
}

let ppm = __ZOOM__;                     // pixels per month (zoom unit)
const pxPerDay = () => ppm / 30.44;
const X = t => (t - dmin) / DAY * pxPerDay();
const totalW = () => Math.ceil((dmax - dmin) / DAY * pxPerDay());

// -- state ------------------------------------------------------------------
TREE.children.forEach(c => c._open = true);        // level 0 open by default
let query = "";

function matches(n, isAct) {
  if (!query) return true;
  const hay = (isAct ? (n.id + " " + n.name) : n.name).toLowerCase();
  return hay.includes(query);
}
function branchHasMatch(n) {
  if (!query) return true;
  if (matches(n, false)) return true;
  if ((n.activities||[]).some(a => matches(a, true))) return true;
  return (n.children||[]).some(branchHasMatch);
}

// -- render -------------------------------------------------------------------
const rowsEl = document.getElementById("rows");
const monthsEl = document.getElementById("months");
const yearsEl = document.getElementById("years");

function ticks() {
  const months = [], years = {};
  const d = new Date(dmin); d.setUTCDate(1); d.setUTCHours(0,0,0,0);
  while (d.getTime() < dmax) {
    const t0 = Math.max(d.getTime(), dmin);
    const m = new Date(d); m.setUTCMonth(m.getUTCMonth() + 1);
    const w = (Math.min(m.getTime(), dmax) - t0)/DAY*pxPerDay();
    months.push({w, lbl: d.toLocaleDateString("en-GB",
                 {month:"short", timeZone:"UTC"})});
    const y = d.getUTCFullYear();
    years[y] = (years[y] || 0) + w;
    d.setUTCMonth(d.getUTCMonth() + 1);
  }
  return {months, years};
}

function bar(cls, s, f, fill, edge, tip) {
  const t0 = Date.parse(s), t1 = f ? Date.parse(f) : t0;
  const el = document.createElement("div");
  el.className = cls;
  el.style.left = X(t0) + "px";
  el.style.width = Math.max((t1 - t0)/DAY*pxPerDay(), 3) + "px";
  if (fill) el.style.background = fill;
  if (edge) el.style.borderColor = edge;
  el.title = tip;
  return el;
}

function render() {
  document.documentElement.style.setProperty("--grid",
    "linear-gradient(90deg, #dfe5ee 1px, transparent 1px)");
  document.documentElement.style.setProperty("--gridsize",
    Math.max(ppm, 6) + "px 100%");

  const tk = ticks();
  yearsEl.innerHTML = ""; monthsEl.innerHTML = "";
  for (const [y, w] of Object.entries(tk.years)) {
    const c = document.createElement("div");
    c.className = "ycell"; c.style.width = w + "px";
    if (w > 34) c.textContent = y;
    yearsEl.appendChild(c);
  }
  for (const m of tk.months) {
    const c = document.createElement("div");
    c.className = "mcell"; c.style.width = m.w + "px";
    if (m.w > 24) c.textContent = m.lbl;
    monthsEl.appendChild(c);
  }

  rowsEl.innerHTML = "";
  let shown = 0;
  const W = totalW();
  const REG = {}, LINKS = [];
  function addRow(labelHtml, indent, isGroup, onclick, laneKids) {
    const row = document.createElement("div"); row.className = "row";
    const lab = document.createElement("div");
    lab.className = "label" + (isGroup ? " grp" : "");
    lab.style.paddingLeft = (8 + indent*16) + "px";
    lab.innerHTML = labelHtml;
    if (onclick) lab.onclick = onclick;
    const lane = document.createElement("div");
    lane.className = "lane";
    lane.style.width = W + "px";
    laneKids.forEach(k => lane.appendChild(k));
    row.appendChild(lab); row.appendChild(lane);
    rowsEl.appendChild(row); shown++;
  }

  (function walk(n, depth) {
    for (const c of (n.children||[])) {
      if (!branchHasMatch(c)) continue;
      const open = query ? true : !!c._open;
      const caret = (c.children.length || c.activities.length)
        ? (open ? "▼" : "►") : "·";
      const kids = [];
      if (c.start) kids.push(bar("bar sum", c.start, c.finish, null, null,
        `${c.name}  ${c.start} → ${c.finish || "?"}  (${c.count} activities,` +
        ` ${c.complete} complete)`));
      addRow(`<span class="caret">${caret}</span>${esc(c.name)}` +
             `<span class="cnt">${c.count}</span>`,
             depth, true,
             () => { c._open = !c._open; render(); }, kids);
      if (!open) continue;
      walk(c, depth + 1);
      for (const a of (c.activities||[])) {
        if (query && !matches(a, true) && !matches(c, false)) continue;
        if (!a.start) continue;
        const kidz = [];
        const tip = `${a.id} — ${a.name}\\n${a.start} → ${a.finish || "…"}` +
                    `\\nstatus: ${a.status}`;
        if (a.milestone) {
          const el = document.createElement("div");
          el.className = "ms";
          el.style.left = (X(Date.parse(a.finish || a.start)) - 5) + "px";
          el.style.background = "var(--navy)"; el.title = tip;
          kidz.push(el);
        } else {
          kidz.push(bar("bar", a.start, a.finish || a.start,
                        FILL[a.status] || "#9aa4b2",
                        EDGE[a.status] || "#9aa4b280", tip));
        }
        if (a.lid) {
          const t0 = Date.parse(a.start);
          const t1 = Date.parse(a.finish || a.start);
          REG[a.lid] = {y: shown * 26 + 13, xs: X(t0),
                        xe: X(t0) + Math.max((t1 - t0)/DAY*pxPerDay(), 3)};
          for (const tgt of (a.links || [])) LINKS.push([a.lid, tgt]);
        }
        addRow(`<span class="caret"></span><span class="aid">${esc(a.id)}</span><span class="anm">${esc(a.name)}</span><span class="adt">${a.start || ""}</span><span class="adt">${a.finish || ""}</span>`,
               depth + 1, false, null, kidz);
      }
    }
  })(TREE, 0);

  // logic connectors between linked bars (drawn over the lanes)
  const wires = LINKS.filter(([s, t]) => REG[s] && REG[t]);
  if (wires.length) {
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("width", W);
    svg.setAttribute("height", shown * 26);
    svg.style.cssText = "position:absolute;top:0;left:" + TREEW +
      "px;pointer-events:none;z-index:4";
    const defs = document.createElementNS(NS, "defs");
    defs.innerHTML = '<marker id="arr" markerWidth="7" markerHeight="7"' +
      ' refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 z"' +
      ' fill="#7c8798"/></marker>';
    svg.appendChild(defs);
    for (const [s, t] of wires) {
      const A = REG[s], B = REG[t];
      const midx = A.xe + 7;
      const p = document.createElementNS(NS, "path");
      p.setAttribute("d", `M ${A.xe} ${A.y} H ${midx} V ${B.y} ` +
                          `H ${Math.max(B.xs - 2, midx)}`);
      p.setAttribute("fill", "none");
      p.setAttribute("stroke", "#7c8798");
      p.setAttribute("stroke-width", "1.3");
      p.setAttribute("marker-end", "url(#arr)");
      svg.appendChild(p);
    }
    rowsEl.appendChild(svg);
  }
  // data-date marker spanning all rows
  if (DATA_DATE) {
    const dd = document.createElement("div");
    dd.className = "ddline";
    dd.style.left = (TREEW + X(Date.parse(DATA_DATE))) + "px";
    dd.title = "Data date " + DATA_DATE;
    rowsEl.appendChild(dd);
  }
  document.getElementById("meta").textContent = shown + " rows";
}
function esc(s){ return s.replace(/[&<>"]/g,
  ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[ch])); }

function setAll(open){
  (function w(n){ (n.children||[]).forEach(c => { c._open = open; w(c); }); })(TREE);
  render();
}
document.getElementById("exp").onclick = () => setAll(true);
document.getElementById("col").onclick = () => setAll(false);
document.getElementById("zoom").oninput = e => { ppm = +e.target.value; render(); };
document.getElementById("q").oninput = e => {
  query = e.target.value.trim().toLowerCase(); render(); };
render();
</script></body></html>"""


STATUS_CATEGORIES = [
    {"key": "complete", "label": "complete", "color": "#2f9e44"},
    {"key": "in progress", "label": "in progress", "color": "#f2a33c"},
    {"key": "not started", "label": "not started", "color": "#4c8ede"},
]


def build_gantt_html(tree: dict, zoom_px_per_month: int = 34,
                     data_date: str | None = None,
                     title: str = "Programme",
                     categories: list[dict] | None = None) -> str:
    """Full HTML document for st.iframe.

    ``tree`` — from hierarchy.tree_to_dict or group_tree below.
    ``categories`` — bar colour scheme: [{key, label, color}] matched
    against each activity's ``status``; defaults to activity status.
    ``data_date`` — ISO date for the dashed marker line.
    """
    return (_TEMPLATE
            .replace("__TREE__", json.dumps(tree))
            .replace("__ZOOM__", str(int(zoom_px_per_month)))
            .replace("__DATA_DATE__", json.dumps(data_date))
            .replace("__CATS__", json.dumps(categories or STATUS_CATEGORIES))
            .replace("__TITLE__", json.dumps(title[:44])))


def group_tree(groups: list[dict]) -> dict:
    """Build the component's tree schema from plain nested group dicts.

    Each group: {"name", "children": [groups], "activities":
    [{"id","name","start","finish","milestone","status"}]} with datetime
    (or None) dates. Rollups (span, counts) are computed here; activities
    keep their given order.
    """
    def iso(d):
        return d.strftime("%Y-%m-%d") if d else None

    def node(g, level):
        acts = []
        starts, finishes = [], []
        for a in g.get("activities", []):
            if a.get("start"):
                starts.append(a["start"])
            if a.get("finish"):
                finishes.append(a["finish"])
            acts.append({"id": a.get("id", ""), "name": a.get("name", ""),
                         "start": iso(a.get("start")),
                         "finish": iso(a.get("finish")),
                         "milestone": bool(a.get("milestone")),
                         "status": a.get("status", ""),
                         "lid": a.get("lid", ""),
                         "links": list(a.get("links", []))})
        kids = [node(c, level + 1) for c in g.get("children", [])]
        count = len(acts) + sum(k["count"] for k in kids)
        complete = (sum(1 for a in acts if a["status"] == "complete")
                    + sum(k["complete"] for k in kids))
        for k in kids:
            if k["start"]:
                starts.append(__import__("datetime").datetime.strptime(
                    k["start"], "%Y-%m-%d"))
            if k["finish"]:
                finishes.append(__import__("datetime").datetime.strptime(
                    k["finish"], "%Y-%m-%d"))
        return {"name": g.get("name", ""), "level": level,
                "start": iso(min(starts)) if starts else None,
                "finish": iso(max(finishes)) if finishes else None,
                "count": count, "complete": complete,
                "children": kids, "activities": acts}

    kids = [node(g, 0) for g in groups]
    starts = [k["start"] for k in kids if k["start"]]
    fins = [k["finish"] for k in kids if k["finish"]]
    return {"name": "root", "level": -1,
            "start": min(starts) if starts else None,
            "finish": max(fins) if fins else None,
            "count": sum(k["count"] for k in kids),
            "complete": sum(k["complete"] for k in kids),
            "children": kids, "activities": []}


def build_apab_gantt_html(
    rows: list[dict],
    keydates: dict[str, str] | None = None,
    overall_delay_days: float | None = None,
    title: str = "As-Planned vs As-Built",
    max_rows: int = 250,
) -> str:
    """Comparison gantt: as-built bar ABOVE, as-planned bar BELOW, per
    activity — with data columns, key-date markers (planned vs actual
    finish) and the per-activity / overall delay measurement.

    ``rows`` come from programme.variance.planned_vs_actual.
    Dark-themed to match the app; server-rendered static HTML.
    """
    from datetime import datetime as _dt

    keydates = keydates or {}
    use = [r for r in rows
           if r.get("planned_start") or r.get("actual_start")][:max_rows]
    dates = [d for r in use for d in (
        r.get("planned_start"), r.get("planned_finish"),
        r.get("actual_start"), r.get("actual_finish")) if d]
    if not use or not dates:
        return ("<body style='background:#FCFCFA;color:#5B7994;"
                "font-family:sans-serif'>No dated activities to draw."
                "</body>")
    t0, t1 = min(dates), max(dates)
    span = max((t1 - t0).days, 1)
    ppd = max(min(1100.0 / span, 12.0), 1100.0 / span)   # fit ~1100px

    def x(d) -> float:
        return (d - t0).days * ppd

    def f(d) -> str:
        return f"{d:%Y-%m-%d}" if d else ""

    # month grid
    grid = []
    cur = _dt(t0.year, t0.month, 1)
    while cur <= t1:
        grid.append((x(cur), f"{cur:%b %y}"))
        cur = (_dt(cur.year + 1, 1, 1) if cur.month == 12
               else _dt(cur.year, cur.month + 1, 1))
    W = span * ppd + 40

    head = ""
    if overall_delay_days is not None:
        head = (f"<div class='banner'>MEASURED DELAY: "
                f"<b>{overall_delay_days:+.0f} calendar days</b> "
                "(as-built vs as-planned completion of the section)"
                "</div>")

    parts = ["""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
  body { margin:0; background:#FCFCFA; color:#14324A;
         font-family:"Segoe UI","Helvetica Neue",Arial,sans-serif;
         background-image:linear-gradient(#E4EDF4 1px,transparent 1px),
                          linear-gradient(90deg,#E4EDF4 1px,transparent 1px);
         background-size:22px 22px; }
  .banner { background:#FCFCFA; border-bottom:2px solid #14324A;
            padding:7px 14px; font-size:12px; color:#14324A;
            position:sticky; top:0; z-index:20; font-weight:600;
            text-transform:uppercase; letter-spacing:.07em; }
  .banner b { color:#9B3227; font-size:14px; }
  #wrap { overflow:auto; }
  table.cmp { border-collapse:collapse; }
  .lbl { position:sticky; left:0; background:#FCFCFA; z-index:10;
         border-right:1.5px solid #14324A; }
  .lbl div { display:flex; gap:8px; align-items:center;
             padding:0 8px; font-size:11.5px; white-space:nowrap; }
  .aid { width:104px; color:#5B7994; overflow:hidden; flex:none;
         font-family:ui-monospace,"SF Mono",Menlo,monospace; font-size:10.5px; }
  .anm { width:230px; overflow:hidden; text-overflow:ellipsis; flex:none; }
  .adt { width:74px; color:#5B7994; font-size:10.5px; flex:none;
         font-family:ui-monospace,"SF Mono",Menlo,monospace;
         font-variant-numeric:tabular-nums; }
  .var { width:52px; text-align:right; font-weight:700; flex:none;
         font-family:ui-monospace,"SF Mono",Menlo,monospace;
         font-variant-numeric:tabular-nums; }
  .late { color:#9B3227; } .early { color:#3F6B4F; }
  .hdr .lbl div { color:#5B7994; font-size:9.5px; font-weight:600;
                  border-bottom:2px solid #14324A; height:26px;
                  text-transform:uppercase; letter-spacing:.09em;
                  font-family:ui-monospace,"SF Mono",Menlo,monospace; }
  tr.r { height:34px; }
  tr.r:nth-child(even) td { background:rgba(20,50,74,.028); }
  tr.kd td { background:rgba(155,50,39,.055) !important; }
  .lane { position:relative; border-bottom:1px solid #DDE7EF;
          background-image:repeating-linear-gradient(90deg,
            #EDF3F8 0 1px, transparent 1px 100%); }
  .bar { position:absolute; }
  .pl  { top:12px; height:0; border-top:1.5px solid #14324A; }
  .pl::before, .pl::after { content:""; position:absolute; top:-4px;
                            width:1.5px; height:9px; background:#14324A; }
  .pl::before { left:0; } .pl::after { right:0; }
  .ab  { top:19px; height:7px; }
  .dia { position:absolute; width:10px; height:10px; top:11px;
         transform:rotate(45deg); }
  .conn { position:absolute; top:15px; border-top:1.5px dashed #5B7994; }
  .dlab { position:absolute; top:5px; font-size:9.5px; font-weight:700;
          white-space:nowrap;
          font-family:ui-monospace,"SF Mono",Menlo,monospace; }
  .leg { padding:5px 14px; font-size:10px; color:#5B7994;
         background:#F1F5F9; border-bottom:1px solid #C6D4E0;
         text-transform:uppercase; letter-spacing:.08em;
         font-family:ui-monospace,"SF Mono",Menlo,monospace; }
  .sw { display:inline-block; width:14px; height:7px; margin:0 4px;
        vertical-align:middle; }
  .mon { position:absolute; top:0; bottom:0; border-left:1px solid #D3E0EA;
         color:#5B7994; font-size:9px; padding-left:3px;
         font-family:ui-monospace,"SF Mono",Menlo,monospace; }
  .tblock { display:flex; border-top:2px solid #14324A; background:#FCFCFA;
            font-family:ui-monospace,"SF Mono",Menlo,monospace; font-size:9px;
            flex-wrap:wrap; }
  .tblock div { border-right:1px solid #14324A; padding:4px 9px; }
  .tblock div:last-child { border-right:0; }
  .tblock span { display:block; color:#5B7994; letter-spacing:.11em;
                 font-size:7.5px; text-transform:uppercase; }
  .tblock b { font-size:10px; letter-spacing:.02em; }
</style></head><body>""", head, """
<div class='leg'>
<span class='sw' style='background:repeating-linear-gradient(45deg,#9B3227 0 3px,#C9857C 3px 6px);border:.5px solid #9B3227'></span>as-built late (45&#176; dense)
<span class='sw' style='background:repeating-linear-gradient(135deg,#3F6B4F 0 2px,transparent 2px 5px),#E8F0EA;border:.5px solid #3F6B4F'></span>as-built on time (135&#176; open)
<span class='sw' style='height:0;border-top:1.5px solid #14324A'></span>as-planned
<span style='color:#14324A'>&#9670;</span> key date actual
<span style='color:#5B7994'>&#9671;</span> planned</div>
<div id='wrap'><table class='cmp'>"""]

    hdr_cells = ("<td class='lbl'><div><span class='aid'>Activity ID"
                 "</span><span class='anm'>Activity name</span>"
                 "<span class='adt'>P. start</span>"
                 "<span class='adt'>P. finish</span>"
                 "<span class='adt'>A. start</span>"
                 "<span class='adt'>A. finish</span>"
                 "<span class='var'>Var d</span></div></td>")
    mon = "".join(f"<div class='mon' style='left:{mx:.0f}px'>{lbl}</div>"
                  for mx, lbl in grid)
    mon_body = "".join(f"<div class='mon' style='left:{mx:.0f}px'></div>"
                       for mx, _ in grid)
    parts.append(f"<tr class='hdr'>{hdr_cells}"
                 f"<td class='lane' style='min-width:{W:.0f}px;"
                 f"height:26px'>{mon}</td></tr>")

    for r in use:
        code = r["task_code"]
        is_kd = code in keydates
        var = r.get("finish_var_days")
        var_cls = "late" if (var or 0) > 0 else "early"
        var_txt = f"{var:+.0f}" if var is not None else ""
        lbl = (f"<td class='lbl'><div><span class='aid'>{code}</span>"
               f"<span class='anm'>{r['name'][:60]}</span>"
               f"<span class='adt'>{f(r.get('planned_start'))}</span>"
               f"<span class='adt'>{f(r.get('planned_finish'))}</span>"
               f"<span class='adt'>{f(r.get('actual_start'))}</span>"
               f"<span class='adt'>{f(r.get('actual_finish'))}</span>"
               f"<span class='var {var_cls}'>{var_txt}</span></div></td>")
        kids = [mon_body]
        ps, pf = r.get("planned_start"), r.get("planned_finish")
        as_, af = r.get("actual_start"), r.get("actual_finish")
        if ps and pf:
            kids.append(f"<div class='bar pl' style='left:{x(ps):.0f}px;"
                        f"width:{max(x(pf)-x(ps),3):.0f}px' "
                        f"title='{code} planned {f(ps)} → {f(pf)}'>"
                        "</div>")
        if as_:
            ae = af or as_
            # Hatch DIRECTION carries late/on-time, not colour alone:
            # 45° dense = late, 135° open = on time — survives greyscale
            # printing and red-green colour blindness.
            if (var or 0) > 0:
                col = ("repeating-linear-gradient(45deg,#9B3227 0 3px,"
                       "#C9857C 3px 6px)")
                edge = "#9B3227"
            else:
                col = ("repeating-linear-gradient(135deg,#3F6B4F 0 2px,"
                       "transparent 2px 5px), #E8F0EA")
                edge = "#3F6B4F"
            kids.append(f"<div class='bar ab' style='left:{x(as_):.0f}px;"
                        f"width:{max(x(ae)-x(as_),3):.0f}px;"
                        f"background:{col};border:.5px solid {edge}' "
                        f"title='{code} as-built "
                        f"{f(as_)} → {f(af)}'></div>")
        if is_kd and pf and af:
            xa, xp = x(af), x(pf)
            kids.append(f"<div class='dia' style='left:{xp-5:.0f}px;"
                        "outline:1.5px solid #5B7994'></div>")
            kids.append(f"<div class='dia' style='left:{xa-5:.0f}px;"
                        "background:#14324A'></div>")
            lo, hi = min(xa, xp), max(xa, xp)
            if hi - lo > 2:
                kids.append(f"<div class='conn' style='left:{lo:.0f}px;"
                            f"width:{hi-lo:.0f}px'></div>")
            kids.append(f"<div class='dlab {var_cls}' "
                        f"style='left:{hi+8:.0f}px'>{var_txt}d</div>")
        parts.append(f"<tr class='r{' kd' if is_kd else ''}'>{lbl}"
                     f"<td class='lane' style='min-width:{W:.0f}px'>"
                     + "".join(kids) + "</td></tr>")

    parts.append("</table></div>")
    _late = sum(1 for r in use if (r.get("finish_var_days") or 0) > 0)
    parts.append(
        "<div class='tblock'>"
        f"<div><span>Analysis</span><b>{title}</b></div>"
        f"<div><span>Activities</span><b>{len(use)}</b></div>"
        f"<div><span>Later than planned</span><b>{_late}</b></div>"
        f"<div><span>Key dates</span><b>{len(keydates)}</b></div>"
        "<div><span>Basis</span><b>Calendar days, as recorded</b></div>"
        "</div></body></html>")
    return "".join(parts)
