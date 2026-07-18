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
    --canvas: #ffffff; --panel: #f6f8fb; --ink: #1f2733; --muted: #6b7686;
    --line: #dfe5ee; --strong: #b8c2d1; --navy: #1f3864;
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
  #toolbar input[type=text] { background: #fff; color: var(--ink);
             border: 1px solid var(--strong); border-radius: 4px;
             padding: 5px 9px; width: 220px; font-size: 12px; }
  #toolbar button { background: #fff; color: var(--navy);
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
  .row:nth-child(even) .lane { background-color: #f7f9fc; }
  .row:hover .lane, .row:hover .label { background-color: #edf3fb; }
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
const TREEW = 340;
document.documentElement.style.setProperty("--treew", TREEW + "px");
document.getElementById("corner").textContent = TITLE;
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
        addRow(`<span class="caret"></span>${esc(a.id)} · ${esc(a.name)}`,
               depth + 1, false, null, kidz);
      }
    }
  })(TREE, 0);

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
    """Full HTML document for st.components.v1.html.

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
                         "status": a.get("status", "")})
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
