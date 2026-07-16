"""Self-contained collapsible gantt viewer (HTML/JS component).

Renders the hierarchy overlay from ``programme.hierarchy`` as an
interactive tree-gantt: collapsible groups with summary rollup bars on
every level, activity bars beneath the lowest level, search (auto-expands
matching branches), zoom, and a frozen tree column with synced scrolling.
No external assets — everything is inlined so it works inside Streamlit's
component iframe (and offline).
"""

from __future__ import annotations

import json

_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  :root {
    --bg: #0f1117; --panel: #161b22; --ink: #c9d1d9; --muted: #8b949e;
    --line: #2d333b; --summary: #6e7f96;
    --done: #2ea043; --active: #e8a33d; --future: #58a6ff;
  }
  * { box-sizing: border-box; font-family: "Segoe UI", system-ui, sans-serif; }
  body { margin: 0; background: var(--bg); color: var(--ink); }
  #toolbar { display: flex; gap: 8px; align-items: center; padding: 8px 10px;
             background: var(--panel); border-bottom: 1px solid var(--line);
             flex-wrap: wrap; position: sticky; top: 0; z-index: 30; }
  #toolbar input[type=text] { background: var(--bg); color: var(--ink);
             border: 1px solid var(--line); border-radius: 6px;
             padding: 4px 8px; width: 210px; }
  #toolbar button { background: var(--bg); color: var(--ink);
             border: 1px solid var(--line); border-radius: 6px;
             padding: 4px 10px; cursor: pointer; }
  #toolbar button:hover { border-color: var(--muted); }
  .lg { display: inline-flex; align-items: center; gap: 4px;
        font-size: 11px; color: var(--muted); }
  .sw { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
  #wrap { overflow: auto; height: calc(100vh - 46px); position: relative; }
  #months { position: sticky; top: 0; z-index: 20; display: flex;
            margin-left: var(--treew); background: var(--bg);
            border-bottom: 1px solid var(--line); width: max-content; }
  .mcell { border-left: 1px solid var(--line); color: var(--muted);
           font-size: 10px; padding: 3px 0 3px 4px; overflow: hidden;
           white-space: nowrap; flex: none; }
  .row { display: flex; width: max-content; min-width: 100%; height: 24px; }
  .row:hover { background: #ffffff0d; }
  .label { position: sticky; left: 0; z-index: 10; width: var(--treew);
           flex: none; background: var(--panel); display: flex;
           align-items: center; font-size: 12px; white-space: nowrap;
           overflow: hidden; text-overflow: ellipsis;
           border-right: 1px solid var(--line);
           border-bottom: 1px solid #2d333b55; cursor: default; }
  .label.grp { cursor: pointer; font-weight: 600; }
  .caret { display: inline-block; width: 14px; text-align: center;
           color: var(--muted); flex: none; }
  .cnt { color: var(--muted); font-weight: 400; margin-left: 6px;
         font-size: 10px; }
  .lane { position: relative; flex: none;
          border-bottom: 1px solid #2d333b55;
          background-image: var(--grid); background-size: var(--gridsize);
          background-repeat: repeat; }
  .bar { position: absolute; top: 7px; height: 10px; border-radius: 3px; }
  .bar.sum { top: 9px; height: 6px; background: var(--summary);
             border-radius: 1px; }
  .bar.sum::before, .bar.sum::after { content: ""; position: absolute;
             top: 0; width: 2px; height: 12px; background: var(--summary); }
  .bar.sum::before { left: 0; } .bar.sum::after { right: 0; }
  .ms { position: absolute; top: 7px; width: 10px; height: 10px;
        transform: rotate(45deg); border-radius: 1px; }
  .dim { opacity: 0.25; }
</style></head><body>
<div id="toolbar">
  <input id="q" type="text" placeholder="Search groups / activities…">
  <button id="exp">Expand all</button>
  <button id="col">Collapse all</button>
  <span class="lg">Zoom <input id="zoom" type="range" min="2" max="60"
        value="__ZOOM__" style="width:110px"></span>
  <span class="lg"><span class="sw" style="background:var(--summary)"></span>
    group summary</span>
  <span class="lg"><span class="sw" style="background:var(--done)"></span>
    complete</span>
  <span class="lg"><span class="sw" style="background:var(--active)"></span>
    in progress</span>
  <span class="lg"><span class="sw" style="background:var(--future)"></span>
    not started</span>
  <span class="lg" id="meta"></span>
</div>
<div id="wrap"><div id="months"></div><div id="rows"></div></div>
<script>
const TREE = __TREE__;
const TREEW = 340;
document.documentElement.style.setProperty("--treew", TREEW + "px");
const DAY = 86400000;
const COLORS = {complete: "var(--done)", "in progress": "var(--active)",
                "not started": "var(--future)"};

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
dmin -= 7*DAY; dmax += 7*DAY;

let ppm = __ZOOM__;                     // pixels per month-ish (zoom unit)
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

function monthTicks() {
  const out = [];
  const d = new Date(dmin); d.setUTCDate(1); d.setUTCHours(0,0,0,0);
  while (d.getTime() < dmax) {
    const t0 = Math.max(d.getTime(), dmin);
    const m = new Date(d); m.setUTCMonth(m.getUTCMonth() + 1);
    out.push({t: d.getTime(), w: (Math.min(m.getTime(), dmax) - t0)/DAY*pxPerDay(),
              lbl: d.toLocaleDateString("en-GB", {month:"short", year:"2-digit",
                                                  timeZone:"UTC"})});
    d.setUTCMonth(d.getUTCMonth() + 1);
  }
  return out;
}

function bar(cls, s, f, color, tip) {
  const t0 = Date.parse(s), t1 = f ? Date.parse(f) : t0;
  const el = document.createElement("div");
  el.className = cls;
  el.style.left = X(t0) + "px";
  el.style.width = Math.max((t1 - t0)/DAY*pxPerDay(), 3) + "px";
  if (color) el.style.background = color;
  el.title = tip;
  return el;
}

function render() {
  const gridStep = Math.max(ppm, 8);
  document.documentElement.style.setProperty("--grid",
    "linear-gradient(90deg, #2d333b40 1px, transparent 1px)");
  document.documentElement.style.setProperty("--gridsize",
    gridStep + "px 100%");

  monthsEl.innerHTML = "";
  for (const m of monthTicks()) {
    const c = document.createElement("div");
    c.className = "mcell"; c.style.width = m.w + "px";
    if (m.w > 26) c.textContent = m.lbl;
    monthsEl.appendChild(c);
  }

  rowsEl.innerHTML = "";
  let shown = 0;
  const W = totalW();
  function addRow(labelHtml, indent, isGroup, onclick, laneKids, dimmed) {
    const row = document.createElement("div"); row.className = "row";
    const lab = document.createElement("div");
    lab.className = "label" + (isGroup ? " grp" : "") + (dimmed ? " dim" : "");
    lab.style.paddingLeft = (6 + indent*16) + "px";
    lab.innerHTML = labelHtml;
    if (onclick) lab.onclick = onclick;
    const lane = document.createElement("div");
    lane.className = "lane" + (dimmed ? " dim" : "");
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
        ? (open ? "▾" : "▸") : "·";
      const kids = [];
      if (c.start) kids.push(bar("bar sum", c.start, c.finish, null,
        `${c.name}  ${c.start} → ${c.finish || "?"}  (${c.count} activities,` +
        ` ${c.complete} complete)`));
      addRow(`<span class="caret">${caret}</span>${esc(c.name)}` +
             `<span class="cnt">${c.count}</span>`,
             depth, true,
             () => { c._open = !c._open; render(); }, kids, false);
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
          el.style.background = COLORS[a.status]; el.title = tip;
          kidz.push(el);
        } else {
          kidz.push(bar("bar", a.start, a.finish || a.start,
                        COLORS[a.status], tip));
        }
        addRow(`<span class="caret"></span>${esc(a.id)} · ${esc(a.name)}`,
               depth + 1, false, null, kidz, false);
      }
    }
  })(TREE, 0);

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


def build_gantt_html(tree: dict, zoom_px_per_month: int = 24) -> str:
    """Full HTML document for st.components.v1.html (tree from
    hierarchy.tree_to_dict)."""
    return (_TEMPLATE
            .replace("__TREE__", json.dumps(tree))
            .replace("__ZOOM__", str(int(zoom_px_per_month))))
