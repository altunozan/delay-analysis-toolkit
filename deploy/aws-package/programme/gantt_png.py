"""The step-④ final gantt as a PNG — the exact chart, rasterised.

The Word narrative and the Excel workbook must carry the SAME chart the
analyst sees on screen: measured-delay banner, data columns, planned
dimension line below, hatched as-built bar above (45° dense = late,
135° open = on time — survives greyscale printing), window curtains
labelled with the accrued delay, key-date ◇ planned / ◆ actual
diamonds with the measured gap, dashed data date, section and umbrella
rows. A browser screenshot would need Chromium on the host; this
renders the same geometry with PIL from the same row dicts, so it works
on Streamlit Cloud unchanged.

Pure engine. Consumes exactly what build_apab_gantt_html consumes.
"""

from __future__ import annotations

import io

INK = (20, 50, 74)
PAPER = (252, 252, 250)
PANEL = (241, 245, 249)
MUT = (91, 121, 148)
GRID = (211, 224, 234)
BRICK = (155, 50, 39)
BRICK_L = (201, 133, 124)
GREEN = (63, 107, 79)
GREEN_BG = (232, 240, 234)
ZEBRA = (243, 246, 249)
KD_BG = (247, 235, 233)
UMB_BG = (232, 238, 243)

BAN_H, LEG_H, HDR_H, WIN_H, ROW_H, SEC_H, FOOT_H = 36, 26, 30, 20, 34, 22, 26
CHART_W, PAD_R = 1100, 40
COLS = [("Activity ID", 104), ("Activity name", 232), ("P. start", 76),
        ("P. finish", 76), ("A. start", 76), ("A. finish", 76),
        ("Var d", 52)]
LBL_W = sum(w for _, w in COLS) + 10


def _fmt(d) -> str:
    return f"{d:%Y-%m-%d}" if d else ""


# PIL's default font lacks the drafting glyphs the app uses — swap them
# for ASCII rather than render tofu boxes into a deliverable figure.
_TRANS = str.maketrans({"—": "-", "–": "-", "→": ">", "·": "|",
                        "▣": "#", "↳": "-", "◆": "*", "◇": "*",
                        "×": "x", "⚠": "!"})


def _t(s) -> str:
    return str(s).translate(_TRANS)


def _hatched_bar(Image, w: int, h: int, late: bool):
    """The as-built bar: hatch DIRECTION carries late/on-time."""
    color, bg = (BRICK, BRICK_L) if late else (GREEN, GREEN_BG)
    bar = Image.new("RGB", (max(w, 3), h), bg)
    from PIL import ImageDraw
    dr = ImageDraw.Draw(bar)
    for off in range(-h, bar.width + h, 7):
        if late:                       # 45° dense
            dr.line([(off, h), (off + h, 0)], fill=color, width=3)
        else:                          # 135° open
            dr.line([(off, 0), (off + h, h)], fill=color, width=2)
    dr.rectangle([0, 0, bar.width - 1, h - 1], outline=color)
    return bar


def _diamond(dr, cx: int, cy: int, r: int, fill, outline) -> None:
    dr.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)],
               fill=fill, outline=outline, width=2)


def _dashed_v(dr, x: int, y0: int, y1: int, color, width: int,
              dash: int = 8, gap: int = 5) -> None:
    y = y0
    while y < y1:
        dr.line([(x, y), (x, min(y + dash, y1))], fill=color, width=width)
        y += dash + gap


def build_apab_gantt_png(
    rows: list[dict],
    keydates: dict[str, str] | None = None,
    overall_delay_days: float | None = None,
    title: str = "As-Planned vs As-Built",
    windows: list[dict] | None = None,
    data_date=None,
    max_rows: int = 250,
    scale: int = 2,
) -> bytes | None:
    """Rasterise the step-④ comparison gantt. Same inputs as
    build_apab_gantt_html; returns PNG bytes, or None when nothing is
    dated. ``scale`` oversamples for print sharpness."""
    from PIL import Image, ImageDraw, ImageFont

    keydates = keydates or {}
    windows = windows or []
    use = [r for r in rows
           if r.get("planned_start") or r.get("actual_start")
           or r.get("row_kind") == "section"][:max_rows]
    dates = [d for r in use for d in (
        r.get("planned_start"), r.get("planned_finish"),
        r.get("actual_start"), r.get("actual_finish")) if d]
    for w in windows:
        dates += [d for d in (w.get("start"), w.get("end")) if d]
    if data_date is not None:
        dates.append(data_date)
    if not use or not dates:
        return None
    t0, t1 = min(dates), max(dates)
    span = max((t1 - t0).days, 1)
    ppd = CHART_W / span
    S = scale

    def X(d) -> int:
        return int((LBL_W + (d - t0).days * ppd) * S)

    def F(sz: int):
        try:
            return ImageFont.load_default(size=sz * S)
        except TypeError:                        # very old pillow
            return ImageFont.load_default()

    f9, f10, f11, f12 = F(9), F(10), F(11), F(13)
    heights = [SEC_H if r.get("row_kind") == "section" else ROW_H
               for r in use]
    win_h = WIN_H if windows else 0
    W = (LBL_W + CHART_W + PAD_R) * S
    H = (BAN_H + LEG_H + HDR_H + win_h + sum(heights) + FOOT_H) * S
    img = Image.new("RGB", (W, H), PAPER)
    dr = ImageDraw.Draw(img)

    # ---- banner ------------------------------------------------------
    y = 0
    if overall_delay_days is not None:
        dr.rectangle([0, 0, W, BAN_H * S], fill=PAPER)
        dr.text((12 * S, 9 * S), "MEASURED DELAY:", font=f11, fill=INK)
        tw = dr.textlength("MEASURED DELAY:", font=f11)
        dr.text((12 * S + tw + 8 * S, 8 * S),
                f"{overall_delay_days:+.0f} calendar days", font=f12,
                fill=BRICK)
        dr.text((12 * S + tw + 8 * S
                 + dr.textlength(f"{overall_delay_days:+.0f} calendar "
                                 "days", font=f12) + 10 * S, 10 * S),
                "(as-built vs as-planned completion of the section)",
                font=f9, fill=MUT)
    dr.line([(0, BAN_H * S - 2), (W, BAN_H * S - 2)], fill=INK,
            width=2 * S)
    y = BAN_H * S

    # ---- legend ------------------------------------------------------
    dr.rectangle([0, y, W, y + LEG_H * S], fill=PANEL)
    lx, ly = 12 * S, y + 7 * S
    img.paste(_hatched_bar(Image, 16 * S, 8 * S, True), (lx, ly))
    lx += 20 * S
    dr.text((lx, ly - 2 * S), "as-built late", font=f9, fill=MUT)
    lx += int(dr.textlength("as-built late", font=f9)) + 14 * S
    img.paste(_hatched_bar(Image, 16 * S, 8 * S, False), (lx, ly))
    lx += 20 * S
    dr.text((lx, ly - 2 * S), "as-built on time", font=f9, fill=MUT)
    lx += int(dr.textlength("as-built on time", font=f9)) + 14 * S
    dr.line([(lx, ly + 4 * S), (lx + 16 * S, ly + 4 * S)], fill=INK,
            width=2 * S)
    lx += 20 * S
    dr.text((lx, ly - 2 * S), "as-planned", font=f9, fill=MUT)
    lx += int(dr.textlength("as-planned", font=f9)) + 14 * S
    _diamond(dr, lx + 5 * S, ly + 4 * S, 5 * S, None, MUT)
    dr.text((lx + 13 * S, ly - 2 * S), "key date planned", font=f9,
            fill=MUT)
    lx += 13 * S + int(dr.textlength("key date planned", font=f9)) \
        + 14 * S
    _diamond(dr, lx + 5 * S, ly + 4 * S, 5 * S, INK, INK)
    dr.text((lx + 13 * S, ly - 2 * S), "key date actual", font=f9,
            fill=MUT)
    lx += 13 * S + int(dr.textlength("key date actual", font=f9)) \
        + 14 * S
    if data_date is not None:
        _dashed_v(dr, lx + 2 * S, ly, ly + 9 * S, BRICK, 2 * S, 4, 3)
        dr.text((lx + 9 * S, ly - 2 * S),
                f"data date {_fmt(data_date)}", font=f9, fill=BRICK)
    y += LEG_H * S

    # ---- header: column titles + month scale ------------------------
    hdr_y = y
    cx0 = 8 * S
    for name, wd in COLS:
        dr.text((cx0, y + 10 * S), name.upper(), font=f9, fill=MUT)
        cx0 += wd * S
    from datetime import datetime as _dt
    months = []
    cur = _dt(t0.year, t0.month, 1)
    while cur <= t1:
        months.append(cur)
        cur = (_dt(cur.year + 1, 1, 1) if cur.month == 12
               else _dt(cur.year, cur.month + 1, 1))
    rows_top = y + HDR_H * S
    rows_bot = rows_top + (win_h + sum(heights)) * S
    for m in months:
        mx = X(m)
        if mx < LBL_W * S:
            continue
        dr.line([(mx, y), (mx, rows_bot)], fill=GRID, width=1)
        if ppd * 30 * S > 24 * S:
            dr.text((mx + 3 * S, y + 10 * S), f"{m:%b %y}", font=f9,
                    fill=MUT)
    dr.line([(0, rows_top - 2), (W, rows_top - 2)], fill=INK,
            width=2 * S)
    y = rows_top

    # ---- window curtains (translucent overlay over all rows) --------
    if windows:
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        for i, w in enumerate(windows):
            ws_, we_ = w.get("start"), w.get("end")
            if not (ws_ and we_):
                continue
            x0, x1 = X(ws_), max(X(we_), X(ws_) + 2)
            tint = ((155, 50, 39, 20) if i % 2 else (20, 50, 74, 22))
            od.rectangle([x0, y, x1, rows_bot], fill=tint)
            od.line([(x0, y), (x0, rows_bot)], fill=(91, 121, 148, 160),
                    width=1 * S)
        img = Image.alpha_composite(img.convert("RGBA"), ov).convert(
            "RGB")
        dr = ImageDraw.Draw(img)
        for i, w in enumerate(windows):
            ws_, we_ = w.get("start"), w.get("end")
            if not (ws_ and we_):
                continue
            d = w.get("delay_days")
            lab = w.get("label", f"W{i + 1}")
            txt = f"{lab}: {d:+.0f}d" if d is not None else lab
            dr.text((X(ws_) + 3 * S, y + 4 * S), txt, font=f10,
                    fill=INK)
        dr.text((8 * S, y + 5 * S),
                "ANALYSIS WINDOWS - project start > key dates "
                "(label = delay accrued in the window)", font=f9,
                fill=MUT)
        y += WIN_H * S

    # ---- rows --------------------------------------------------------
    zebra = 0
    for r, rh in zip(use, heights):
        ry, rb = y, y + rh * S
        kind = r.get("row_kind") or ""
        if kind == "section":
            dr.rectangle([0, ry, W, rb], fill=INK)
            dr.text((10 * S, ry + 5 * S), _t(r["name"])[:90].upper(),
                    font=f10, fill=PAPER)
            y = rb
            continue
        code = r["task_code"]
        is_kd = code in keydates
        # row background (label panel only — curtains own the lanes)
        if is_kd:
            dr.rectangle([0, ry, LBL_W * S, rb], fill=KD_BG)
        elif kind == "umbrella":
            dr.rectangle([0, ry, LBL_W * S, rb], fill=UMB_BG)
        elif zebra % 2:
            dr.rectangle([0, ry, LBL_W * S, rb], fill=ZEBRA)
        zebra += 1
        var = r.get("finish_var_days")
        var_col = BRICK if (var or 0) > 0 else GREEN
        name = ((">> " if kind == "umbrella" else
                 "    - " if kind == "member" else "")
                + _t(r["name"])[:40])
        cells = [code[:16], name, _fmt(r.get("planned_start")),
                 _fmt(r.get("planned_finish")),
                 _fmt(r.get("actual_start")),
                 _fmt(r.get("actual_finish")),
                 f"{var:+.0f}" if var is not None else ""]
        cx0 = 8 * S
        for (colname, wd), val in zip(COLS, cells):
            col = (var_col if colname == "Var d"
                   else INK if colname in ("Activity ID",
                                           "Activity name") else MUT)
            fnt = f10 if colname == "Activity name" else f9
            dr.text((cx0, ry + 10 * S), val, font=fnt, fill=col)
            cx0 += wd * S
        dr.line([(0, rb - 1), (W, rb - 1)], fill=(221, 231, 239),
                width=1)
        # planned dimension line (below-centre)
        ps, pf = r.get("planned_start"), r.get("planned_finish")
        if ps and pf:
            py = ry + 12 * S
            dr.line([(X(ps), py), (X(pf), py)], fill=INK, width=2 * S)
            for tx in (X(ps), X(pf)):
                dr.line([(tx, py - 4 * S), (tx, py + 4 * S)], fill=INK,
                        width=1 * S)
        # as-built hatched bar (above-centre)
        as_, af = r.get("actual_start"), r.get("actual_finish")
        if as_:
            ae = af or as_
            bw = max(X(ae) - X(as_), 3 * S)
            bar = _hatched_bar(Image, bw, 8 * S, (var or 0) > 0)
            img.paste(bar, (X(as_), ry + 18 * S))
        # key-date markers + measured gap
        if is_kd and pf and af:
            xa, xp = X(af), X(pf)
            cyd = ry + 12 * S
            lo, hi = min(xa, xp), max(xa, xp)
            if hi - lo > 2 * S:
                _dashed_v_h = lo
                while _dashed_v_h < hi:          # dashed connector
                    dr.line([(_dashed_v_h, cyd),
                             (min(_dashed_v_h + 5 * S, hi), cyd)],
                            fill=MUT, width=1 * S)
                    _dashed_v_h += 8 * S
            _diamond(dr, xp, cyd, 5 * S, None, MUT)
            _diamond(dr, xa, cyd, 5 * S, INK, INK)
            if var is not None:
                dr.text((hi + 8 * S, ry + 5 * S), f"{var:+.0f}d",
                        font=f10, fill=var_col)
        y = rb

    # ---- data date over everything ----------------------------------
    if data_date is not None:
        _dashed_v(dr, X(data_date), rows_top, rows_bot, BRICK, 2 * S)

    # ---- footer ------------------------------------------------------
    dr.line([(0, rows_bot + 1), (W, rows_bot + 1)], fill=INK,
            width=2 * S)
    n_late = sum(1 for r in use if (r.get("finish_var_days") or 0) > 0)
    dr.text((10 * S, rows_bot + 8 * S),
            _t(f"{title}   |   {len(use)} rows   |   {n_late} later "
               f"than planned   |   {len(keydates)} key date(s)   |   "
               "basis: calendar days, as recorded"), font=f9, fill=MUT)

    # frozen-panel divider
    dr.line([(LBL_W * S, BAN_H * S), (LBL_W * S, rows_bot)], fill=INK,
            width=1 * S)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
